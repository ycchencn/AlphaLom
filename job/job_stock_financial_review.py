"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股「巴菲特视角 AI 财务点评」每日批量生成任务。

链路：
    fetch_review_data(拉 4 张核心报表最近 N 期)
      -> 若已存点评的 report_date 与本次最新财报期一致 → 跳过（财报空窗期不重复烧 token）
      -> generate_review(系统 LLM 场景 stock_financial_review，非流式产出全文)
      -> StockFinancialReviewService.save(symbol, review_date) 幂等落库

## 与股吧情绪任务（job_stock_guba_sentiment）的异同
- 同：**每日批量、单只失败隔离、不投队列**（队列 prefetch=1 串行会堵住其它任务）。
- 异：本任务按「财务期是否变化」做增量跳过 —— 财报一年才更新几次，两次财报之间
      每天重跑会得到几乎一样的点评，纯粹浪费 token，所以比对 report_date 后跳过。
      首次运行（无历史）或新财报期出现时才会真正调用 LLM。

## 失败处理
- 取数失败 / LLM 失败 / 落库失败 → 只记日志、不抛异常、不落库，单只失败不影响整批。
- 这与股吧任务一致：批量任务里「少一个数据点」远好过「填假值」或「拖垮整批」。
"""

import json
from datetime import date
from typing import Any, Dict, Optional

from config import fin_review_max_symbols
from models.database import db_session
from service import StockService
from service.stock_financial_review import StockFinancialReviewService
from utils.logger import logger


# ---------------------------------------------------------------- 单只流程

def analyze_symbol(symbol: str, periods: int = 12) -> Optional[Dict[str, Any]]:
    """分析单只股票并落库。返回落库记录；跳过/失败返回 None。"""
    symbol = str(symbol or '').strip()
    if not symbol:
        logger.warning('[fin_review] 空 symbol，跳过')
        return None

    # 1) 取财务数据
    try:
        data = StockFinancialReviewService.fetch_review_data(symbol, periods)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[fin_review] {symbol} 取数失败，跳过：{e}')
        return None

    latest_date = data.get('latest_date') or ''
    if not latest_date:
        logger.info(f'[fin_review] {symbol} 暂无财务数据，跳过（不落库）')
        return None

    # 2) 增量跳过：财务期没变化就不重跑（省 token）
    try:
        existing = StockFinancialReviewService.get_latest(symbol)
    except Exception:  # noqa: BLE001
        existing = None
    if existing and existing.get('report_date') == latest_date:
        logger.info(f'[fin_review] {symbol} 财务期 {latest_date} 已点评，跳过')
        return None

    # 3) 生成（非流式）
    try:
        result = StockFinancialReviewService.generate_review(symbol, stock_name='', periods=periods)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[fin_review] {symbol} 生成失败，跳过：{e}')
        return None

    # 4) 落库
    ok = StockFinancialReviewService.save(
        symbol=symbol,
        content=result['content'],
        model=result.get('model'),
        report_date=result.get('report_date'),
        review_date=date.today(),
    )
    if not ok:
        return None

    logger.info(
        f"[fin_review] {symbol} 已生成点评（财务期 {result.get('report_date')}，"
        f"模型 {result.get('model')}）"
    )
    result.update({'symbol': symbol, 'review_date': date.today().isoformat()})
    return result


# ---------------------------------------------------------------- job 入口

def job_stock_financial_review(_stock_code: str):
    """单只股票的分析 job（供手动触发 / 调试）。参数名与 JobService.send_job 对齐。"""
    analyze_symbol(_stock_code)
    db_session.remove()


def job_stock_financial_review_daily():
    """每日批量：枚举监控池，逐只生成巴菲特视角财务点评。

    ⚠️ 与股吧任务一致，**不投递到 job 队列**：本任务单只耗时长（4 次取数 + 一次长文 LLM），
    投队列会串行占用 prefetch=1 的消费槽，把其它用户的任务堵在后面。这里在调度进程里
    同步跑，单只失败已隔离，整批耗时可预期。
    """
    try:
        stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[fin_review] 取监控池失败，本日任务中止：{e}')
        return

    symbols = [s.get('symbol') for s in stocks if s.get('symbol')]
    db_session.remove()  # 释放 search_stocks 占用的会话
    if not symbols:
        logger.info('[fin_review] 监控池为空，跳过')
        return

    limit = max(1, int(fin_review_max_symbols))
    if len(symbols) > limit:
        logger.warning(
            f'[fin_review] 监控池 {len(symbols)} 只超过上限 {limit} 只，'
            f'本次只处理前 {limit} 只'
        )
        symbols = symbols[:limit]

    logger.info(f'[fin_review] 开始每日批量，共 {len(symbols)} 只')
    ok_cnt = skip_cnt = fail_cnt = 0

    for symbol in symbols:
        try:
            result = analyze_symbol(symbol)
            if result:
                ok_cnt += 1
            else:
                skip_cnt += 1
        except Exception as e:  # noqa: BLE001
            fail_cnt += 1
            logger.error(f'[fin_review] {symbol} 分析异常：{e}')
        finally:
            # 单只失败不能留下坏事务，否则后续股票全部连坐
            db_session.remove()

    logger.info(f'[fin_review] 每日批量结束：成功 {ok_cnt} / 跳过 {skip_cnt} / 失败 {fail_cnt}')


if __name__ == '__main__':
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else '600519'
    print(json.dumps(analyze_symbol(target), ensure_ascii=False, indent=2, default=str))
