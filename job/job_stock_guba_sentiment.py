"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股散户情绪分析任务（东方财富股吧发帖 → LLM 三分类 → 落库）。

链路：
    fetch_posts(股吧列表页，只取标题)
      -> sample_posts(按互动量分层采样，控制 token 与信噪比)
      -> LLM(输出 看多/中性/看空 三分类占比 + 置信度 + 归因)
      -> StockGubaSentimentService.compute_score(后端公式算总分)
      -> upsert(symbol, trade_date) 幂等落库

## 关键设计：置信度在代码侧再兜一次

prompt 里写了「按有效帖数封顶」的硬规则，但**模型不保证遵守**——POC 实测出现过
4 条样本给 65 分置信度的情况。置信度直接决定前端是否给用户看结论，所以不能只靠 prompt，
这里对模型返回的 confidence 再按样本量取一次 min。

## 失败处理

抓取被反爬拦截 / LLM 解析失败 → 只记日志、不落库、不抛异常。
理由：这是每日批量任务，单只票失败不该拖垮整批；而且情绪指标缺失是「少一个数据点」，
不是「数据错误」，空着比填假值安全。抓取器的冷却机制会保证不会反复触发封锁。
"""

import json
from datetime import date, datetime
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

from config import guba_max_posts_for_llm, guba_max_symbols
from llms import get_model_by_setting
from models.database import db_session
from service import JobService, StockService
from service.eastmoney_guba import (
    GubaBlockedError,
    GubaRateLimited,
    fetch_posts,
    sample_posts,
)
from service.stock_guba_sentiment_service import StockGubaSentimentService
from utils.common import extract_json_object
from utils.logger import logger

CURRENT_DIR = Path(__file__).parent
PROMPT_PATH = CURRENT_DIR.parent / 'llms' / 'templates' / 'prompt_guba_sentiment.md'


# ---------------------------------------------------------------- 内部工具

def _build_posts_block(posts: List[Dict[str, Any]]) -> str:
    """把帖子压成 prompt 里的一行行文本。

    只放标题——正文要逐帖再发一次请求（请求量 ×8），单 IP 不可持续，
    实测标题已足够支撑三分类判断（标题均值 25 字，散户立场基本写在标题里）。
    """
    lines = []
    for p in posts:
        flag = 'T' if p.get('is_top') else '-'
        # 作者名带「资讯/财经/证券」时加标记，帮模型识别资讯号（它也会自己看标题风格）
        author = p.get('author') or ''
        author_tag = ''
        if any(k in author for k in ('资讯', '财经', '证券')):
            author_tag = f'|{author}'
        lines.append(
            f"[{p.get('publish_time', '')[5:16]}|{p.get('click', 0)}|{p.get('comment', 0)}|{flag}]"
            f" {p.get('title', '')}{author_tag}"
        )
    return '\n'.join(lines)


def _normalize_ratios(data: Dict[str, Any]) -> Tuple[float, float, float]:
    """把三个占比归一化到合计 100。

    模型经常给出 27+60+13=100 之外的组合（27+60+14=101、或直接给小数）。
    这里按比例缩放；全为 0 时退化为 (33.3, 33.4, 33.3)，避免除零。
    """
    def _get(key: str) -> float:
        try:
            return max(0.0, float(data.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0

    b, n, s = _get('bullish_ratio'), _get('neutral_ratio'), _get('bearish_ratio')
    total = b + n + s

    if total <= 0:
        return 33.3, 33.4, 33.3

    b, n = b * 100.0 / total, n * 100.0 / total
    s = 100.0 - b - n  # 用减法兜尾差，保证三者严格相加为 100
    return round(b, 2), round(n, 2), round(max(0.0, s), 2)


def _clamp_confidence(raw: Any, effective_count: int) -> float:
    """按有效帖数给置信度封顶（与 prompt 里的表一致，这里是代码侧兜底）。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(100.0, value))

    n = max(0, int(effective_count or 0))
    if n == 0:
        cap = 0
    elif n <= 4:
        cap = 20
    elif n <= 14:
        cap = 40
    elif n <= 29:
        cap = 60
    elif n <= 59:
        cap = 80
    else:
        cap = 95
    return round(min(value, cap), 2)


def _resolve_trade_date() -> date:
    """采集归属日期。

    用采集当日而不是「最近交易日」：本指标是 24h 滚动窗口，周末/节假日也会采到真实发帖，
    强行归到上个交易日会造成同一日期多行互相覆盖。前端展示时再按日期对齐 K 线。
    """
    return datetime.now().date()


# ---------------------------------------------------------------- 主流程

def analyze_symbol(symbol: str, hours: int = 24) -> Optional[Dict[str, Any]]:
    """分析单只股票的散户情绪并落库。返回落库的记录；无样本或失败返回 None。"""
    symbol = str(symbol or '').strip()
    if not symbol:
        logger.warning('[guba_sentiment] 空 symbol，跳过')
        return None

    # 1) 抓取
    try:
        posts = fetch_posts(symbol, hours=hours)
    except GubaRateLimited as e:
        logger.warning(f'[guba_sentiment] {symbol} 跳过：{e}')
        return None
    except GubaBlockedError as e:
        # 已写冷却键，后续调用会被 _check_block_cooldown 直接挡住
        logger.error(f'[guba_sentiment] {symbol} 抓取被拦截，中止本只：{e}')
        return None
    except Exception as e:  # noqa: BLE001
        logger.error(f'[guba_sentiment] {symbol} 抓取异常：{e}')
        return None

    if not posts:
        logger.info(f'[guba_sentiment] {symbol} 24h 内无帖子，跳过（不落库）')
        return None

    # 2) 采样
    sampled = sample_posts(posts, guba_max_posts_for_llm)
    top_count = sum(1 for p in sampled if p.get('is_top'))
    logger.info(f'[guba_sentiment] {symbol} 原始 {len(posts)} 条，采样 {len(sampled)} 条（置顶 {top_count} 条）')

    # 3) LLM
    try:
        template_text = PROMPT_PATH.read_text(encoding='utf-8')
        prompt = Template(template_text).safe_substitute(posts=_build_posts_block(sampled))

        staff = get_model_by_setting(_setting_name='stock_retail_sentiment')
        staff.role_base = (
            '你是严谨的 A 股散户情绪分析师。只依据给定帖子内容判断，'
            '不引入外部股价知识，严格按要求的 JSON 格式输出。'
        )
        staff.set_response_json()
        content = staff.ask(prompt)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[guba_sentiment] {symbol} LLM 调用失败：{e}')
        return None

    data = extract_json_object(content)
    if not data:
        logger.error(f'[guba_sentiment] {symbol} 未产出合法 JSON，跳过入库：{str(content)[:200]}')
        return None

    # 4) 归一并算分
    bullish, neutral, bearish = _normalize_ratios(data)
    try:
        effective_count = int(data.get('effective_count') or 0)
    except (TypeError, ValueError):
        effective_count = 0
    confidence = _clamp_confidence(data.get('confidence'), effective_count)
    score = StockGubaSentimentService.compute_score(bullish, neutral, bearish)

    trade_date = _resolve_trade_date()
    payload = {
        'bullish_ratio': bullish,
        'neutral_ratio': neutral,
        'bearish_ratio': bearish,
        'sentiment_score': score,
        'confidence': confidence,
        'heat_level': str(data.get('heat_level') or StockGubaSentimentService.derive_heat_level(len(posts)))[:10],
        'post_count': len(posts),
        'sample_size': len(sampled),
        'effective_count': effective_count,
        'dominant_topic': (data.get('dominant_topic') or '')[:255] or None,
        'reasoning': data.get('reasoning'),
        'keywords': data.get('keywords') if isinstance(data.get('keywords'), list) else [],
        'notable_posts': data.get('notable_posts') if isinstance(data.get('notable_posts'), list) else [],
        'model': getattr(staff, 'model', None),
    }

    ok = StockGubaSentimentService.upsert(symbol, trade_date, payload)
    if not ok:
        return None

    logger.info(
        f'[guba_sentiment] {symbol} {trade_date} 情绪分={score} 置信度={confidence} '
        f'占比={bullish}/{neutral}/{bearish} 样本={len(sampled)}/{len(posts)}'
    )
    payload.update({'symbol': symbol, 'trade_date': trade_date.isoformat()})
    return payload


# ---------------------------------------------------------------- job 入口

def job_stock_guba_sentiment(_stock_code: str):
    """单只股票的分析 job（供队列或手动触发）。参数名与 JobService.send_job 对齐。"""
    analyze_symbol(_stock_code)
    # scoped_session 是线程级的：这里不清会把这个 job 的事务状态带给下一个 job
    db_session.remove()


def job_stock_guba_sentiment_daily():
    """每日批量：枚举监控池，逐只分析。

    ⚠️ 刻意**不投递到 job 队列**：队列是 prefetch=1 串行消费，几十只票各占用
    20 秒限速等待，会把其它用户的分析任务堵在后面。这里在调度进程里同步跑，
    单只失败已隔离，整批耗时可预期（50 只 × 20 秒 ≈ 17 分钟）。
    """
    try:
        stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[guba_sentiment] 取监控池失败，本日任务中止：{e}')
        return

    symbols = [s.get('symbol') for s in stocks if s.get('symbol')]
    if not symbols:
        logger.info('[guba_sentiment] 监控池为空，跳过')
        return

    limit = max(1, int(guba_max_symbols))
    if len(symbols) > limit:
        logger.warning(
            f'[guba_sentiment] 监控池 {len(symbols)} 只超过单 IP 上限 {limit} 只，'
            f'本次只处理前 {limit} 只（扩大覆盖需配代理池，见可行性报告）'
        )
        symbols = symbols[:limit]

    logger.info(f'[guba_sentiment] 开始每日批量，共 {len(symbols)} 只')
    ok_cnt = skip_cnt = fail_cnt = 0

    for symbol in symbols:
        try:
            result = analyze_symbol(symbol)
            if result:
                ok_cnt += 1
            else:
                skip_cnt += 1
        except GubaRateLimited:
            logger.warning('[guba_sentiment] 处于冷却期，提前结束批量')
            break
        except Exception as e:  # noqa: BLE001
            fail_cnt += 1
            logger.error(f'[guba_sentiment] {symbol} 分析失败：{e}')
            # 单只失败不能留下坏事务，否则后续股票全部连坐
            db_session.remove()

    logger.info(f'[guba_sentiment] 每日批量结束：成功 {ok_cnt} / 跳过 {skip_cnt} / 失败 {fail_cnt}')


if __name__ == '__main__':
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else '000001'
    print(json.dumps(analyze_symbol(target), ensure_ascii=False, indent=2, default=str))
