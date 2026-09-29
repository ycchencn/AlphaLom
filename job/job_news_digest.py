"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 新闻流 AI 速览（事件驱动页顶部「AI 推荐」卡片的数据来源）。

 做一件事：把「最近 N 小时」的新闻流交给大模型，压成**前三条头条**
 （每条 = 主题 + 关键词 + 一句话总结），落库到 `news_digest` 表，
 前端 `/#/market/news_flow` 顶部置顶展示，每小时滚动刷新。

 调度在 `job/news_server.py`（与新闻采集同一个进程），
 时间口径的单一真源是 `service/news_digest_service.py` 顶部的 REFRESH_* 常量。

 手动执行（在仓库根目录）：
     python -m job.job_news_digest            # 常规跑一轮
     python -m job.job_news_digest --force    # 忽略「新闻太少」门槛，强行跑一轮
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llms import get_model_by_setting
from prompts.prompt_generator import load_prompt_template
from service import MarketNewsService, NewsDigestService
from service.news_digest_service import MAX_HEADLINES
from utils.common import extract_json_object
from utils.logger import logger

CURRENT_DIR = Path(__file__).parent
PROMPT_FILE = CURRENT_DIR / 'prompt_news_digest.md'
prompt_template = load_prompt_template(template_path=PROMPT_FILE)

# MARK: - 配置常量 ----------------------------------------------------------
# 窗口逐级放宽：一小时内的新闻太少（夜间、采集延迟、上游断流）时退到更大的窗口，
# 让卡片尽量有内容。连最大窗口都凑不够 MIN_NEWS_FOR_DIGEST 条 → 整轮跳过：
# 宁可让卡片继续显示上一轮的时间，也不要拿两三条新闻硬编出「三大头条」。
WINDOW_STEPS_HOURS = (1, 2, 4, 8, 24)
MIN_NEWS_FOR_DIGEST = 5

# 交给模型的新闻条数上限（控 token）。
# 高关联新闻优先占 MAX_RELEVANT_SLOTS 个名额，剩下的按时间倒序补足。
MAX_NEWS_IN_PROMPT = 50
MAX_RELEVANT_SLOTS = 35
# relation_level >= 该值视为「与市场强相关」，优先送进模型
RELEVANT_LEVEL = 3

MAX_KEYWORDS = 8
MAX_HIGHLIGHTS = 5
DIGEST_TITLE = '新闻流速览'


# MARK: - 取数 --------------------------------------------------------------
def _fetch_news(start: datetime, end: datetime) -> List[dict]:
    """取窗口内的新闻（含未关联个股的宏观新闻，按 news_time 倒序）。"""
    result = MarketNewsService.search(
        start_time=start,
        end_time=end,
        page=1,
        page_size=200,          # 服务层上限 MAX_PAGE_SIZE=200；超出部分只取最新的 200 条
        relation_level_only=False,
    )
    return (result or {}).get('items') or []


def _dedupe(items: List[dict]) -> List[dict]:
    """
    按摘要文本去重。

    采集侧只按「原文内容 MD5」去重，同一事件被不同源改写后 MD5 不同，会重复入库。
    这里在送模型之前先做一层浅去重，省 token 也让关键词统计更准。
    """
    seen = set()
    unique = []
    for item in items:
        key = ' '.join((item.get('digest') or '').split())
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _select_for_prompt(items: List[dict]) -> List[dict]:
    """
    混选送模型的新闻：先按市场关联度取，再用最新新闻补足名额。

    为什么不能只按时间取最新 N 条：采集任务是**批量写入**，同一批次的时间戳高度集中，
    只按时间截断等于在一批里随机取样，看不到窗口内真正重要的消息。
    为什么也不能只按关联度取：隔夜外盘、宏观政策这类「读者很关心」的新闻关联度往往不高，
    只按关联度会把它们全部丢掉。所以两路都要，且高关联优先。
    """
    def level(item: dict) -> int:
        try:
            return int(item.get('relation_level') or 0)
        except (TypeError, ValueError):
            return 0

    # sorted 是稳定排序：同一关联度内保持传入的「时间倒序」
    relevant = sorted([it for it in items if level(it) >= RELEVANT_LEVEL], key=level, reverse=True)
    others = [it for it in items if level(it) < RELEVANT_LEVEL]

    picked = relevant[:MAX_RELEVANT_SLOTS]
    picked += others[:max(0, MAX_NEWS_IN_PROMPT - len(picked))]
    return picked[:MAX_NEWS_IN_PROMPT]


def _format_news_lines(items: List[dict]) -> str:
    """把新闻条目压成紧凑的单行文本，喂给模型。"""
    lines = []
    for idx, item in enumerate(items, start=1):
        raw_time = item.get('news_time') or ''
        # to_dict() 给的是 ISO 字符串（2026-09-29T15:32:00），只留到分钟
        hhmm = raw_time[11:16] if isinstance(raw_time, str) and len(raw_time) >= 16 else '--:--'
        digest = ' '.join((item.get('digest') or '').split())
        tags = '、'.join([str(t) for t in (item.get('tags') or [])[:6]])
        level = item.get('relation_level')
        bullish = item.get('bullish_level')
        parts = [f'{idx}. [{hhmm}] {digest}']
        if tags:
            parts.append(f'标签:{tags}')
        parts.append(f"关联度:{level if isinstance(level, int) else '-'}")
        parts.append(f"利好度:{bullish:+d}" if isinstance(bullish, int) else '利好度:-')
        lines.append(' | '.join(parts))
    return '\n'.join(lines)


# MARK: - 模型调用 ----------------------------------------------------------
def _normalize_result(data: Any) -> Optional[Dict[str, Any]]:
    """
    把模型输出收敛成可落库的形状；不可用返回 None。

    这里做「宽进严出」：模型可能少给字段、把 keywords 写成字符串、把 summary 写超长，
    都在这里洗掉；但**绝不编造内容**（缺的关键词就空着，缺的头条就不补），
    否则卡片上会出现新闻里根本没有的「关键词」。
    """
    if not isinstance(data, dict):
        return None

    headlines = []
    raw_headlines = data.get('headlines')
    if isinstance(raw_headlines, list):
        for item in raw_headlines:
            if not isinstance(item, dict):
                continue

            keywords = []
            raw_keywords = item.get('keywords')
            if isinstance(raw_keywords, str):
                # 模型偶尔把数组写成「A、B、C」字符串
                raw_keywords = raw_keywords.replace('，', '、').replace(',', '、').split('、')
            if isinstance(raw_keywords, list):
                for kw in raw_keywords:
                    text = str(kw).strip().strip('、，,;； ')
                    if text and text not in keywords:
                        keywords.append(text)

            summary = ' '.join(str(item.get('summary') or '').split())
            if not keywords and not summary:
                continue

            headlines.append({
                'topic': (str(item.get('topic') or '').strip() or '重点')[:10],
                'keywords': keywords[:MAX_KEYWORDS],
                'summary': summary,
            })
            if len(headlines) >= MAX_HEADLINES:
                break

    if not headlines:
        return None

    highlights = []
    raw_highlights = data.get('highlights')
    if isinstance(raw_highlights, list):
        for item in raw_highlights:
            text = ' '.join(str(item).split())
            if text:
                highlights.append(text)
            if len(highlights) >= MAX_HIGHLIGHTS:
                break

    return {
        'title': (str(data.get('title') or '').strip() or DIGEST_TITLE)[:60],
        'headlines': headlines,
        'highlights': highlights,
    }


def _ask_digest(prompt: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    调用大模型生成速览。

    先用 JSON 模式（模型直接吐结构化结果，免解析）；拿到的内容解析不出来时，
    退到文本模式再问一次 —— 文本模式没有 json_object 的格式约束，反而常能拿到完整的 JSON。
    两次都失败返回 (None, None)，由调用方跳过本轮，不落半成品。

    :return: (归一化后的结果, 实际使用的模型名)
    """
    staff = get_model_by_setting('news_digest')
    model_name = getattr(staff, 'model', None)

    staff.set_response_json()
    raw = staff.ask(prompt)
    result = _normalize_result(extract_json_object(raw))
    if result:
        return result, model_name

    logger.warning(
        f'news_digest: JSON 模式未拿到可用结果，改用文本模式重试一次。原始片段：{(raw or "")[:200]}'
    )
    staff.set_response_text()
    raw = staff.ask(prompt)
    result = _normalize_result(extract_json_object(raw))
    if result:
        return result, model_name

    logger.error(f'news_digest: 两次调用都没拿到可用结果，本轮跳过。原始片段：{(raw or "")[:200]}')
    return None, None


# MARK: - 主流程 ------------------------------------------------------------
def build_news_digest(trigger_type: str = 'auto', force: bool = False) -> Optional[Dict[str, Any]]:
    """
    生成一条新闻速览并落库。

    :param trigger_type: `auto`-定时任务 / `manual`-页面手动刷新（只作落库标记，便于区分来源）
    :param force: True 时忽略「新闻条数不足」的门槛（给手动刷新一个「至少试试」的机会）
    :return: 落库后的 dict；本轮跳过（新闻不足 / 模型没给结果 / 落库失败）返回 None
    """
    now = datetime.now()

    # 1) 选窗口：从 1 小时开始逐级放宽，取第一个「条数够用」的
    items: List[dict] = []
    used_hours: Optional[int] = None
    for hours in WINDOW_STEPS_HOURS:
        items = _dedupe(_fetch_news(now - timedelta(hours=hours), now))
        if len(items) >= MIN_NEWS_FOR_DIGEST:
            used_hours = hours
            break

    if used_hours is None:
        if not force:
            logger.warning(
                f'news_digest: 近 {WINDOW_STEPS_HOURS[-1]} 小时仅 {len(items)} 条新闻，'
                f'低于阈值 {MIN_NEWS_FOR_DIGEST}，本轮跳过（卡片保持上一轮结果）'
            )
            return None
        used_hours = WINDOW_STEPS_HOURS[-1]
        logger.info(f'news_digest: 手动强制生成，窗口放宽到 {used_hours} 小时（{len(items)} 条）')

    if not items:
        logger.warning('news_digest: 窗口内没有任何新闻，本轮跳过')
        return None

    # 2) 组 prompt
    window_start = now - timedelta(hours=used_hours)
    selected = _select_for_prompt(items)
    prompt = prompt_template.safe_substitute(
        digest_date=now.strftime('%Y-%m-%d %H:%M'),
        window_desc=(
            f"{window_start.strftime('%m-%d %H:%M')} ~ {now.strftime('%m-%d %H:%M')}"
            f"（近 {used_hours} 小时）"
        ),
        news_count=len(selected),
        news_list=_format_news_lines(selected),
    )

    # 3) 调模型 + 落库
    result, model_name = _ask_digest(prompt)
    if not result:
        return None

    saved = NewsDigestService.create(
        headlines=result['headlines'],
        highlights=result['highlights'],
        title=result['title'],
        window_start=window_start,
        window_end=now,
        news_count=len(selected),
        model=model_name,
        trigger_type=trigger_type,
        generated_at=now,
    )
    if saved:
        logger.info(
            f"✅ 新闻速览生成完成：窗口 {used_hours}h / 候选 {len(items)} 条 / 送模型 {len(selected)} 条 / "
            f"头条 {len(saved['headlines'])} 条"
        )
    return saved


def job_news_digest_hourly() -> None:
    """
    定时任务入口（每小时，活跃时段）。

    ⚠️ 调度器里跑的东西**绝不能让异常逃出去**：一个未捕获异常在 APScheduler 里只会
    打一行日志，但如果是 import 期或首轮就炸，很容易被当成「任务没生效」而不是「任务失败」。
    所以这里把全部异常收敛成一条日志。
    """
    try:
        build_news_digest(trigger_type='auto')
        # 顺手清理过期历史（低频维护，放这里省一个调度条目）
        NewsDigestService.prune()
    except Exception as e:
        logger.error(f'❌ 新闻速览任务执行失败：{e}', exc_info=True)


if __name__ == '__main__':
    # 手动执行：python -m job.job_news_digest [--force]
    _force = '--force' in sys.argv
    _saved = build_news_digest(trigger_type='manual', force=_force)
    if _saved:
        print(f"生成成功：id={_saved['id']} 覆盖 {_saved['news_count']} 条新闻")
        for _i, _h in enumerate(_saved['headlines'], 1):
            print(f"  {_i}. {_h['topic']}：{'、'.join(_h['keywords'])}")
            if _h.get('summary'):
                print(f"     {_h['summary']}")
    else:
        print('本轮未生成（新闻不足或模型未返回可用结果），详见日志')
