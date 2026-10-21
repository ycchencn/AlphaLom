"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股「巴菲特视角 AI 财务点评」定时批量生成任务。

链路（单只）：
    fetch_review_data(拉 4 张核心报表最近 N 期)
      -> 无财务数据则跳过
      -> generate_review(系统 LLM 场景 stock_financial_review，非流式产出全文)
      -> StockFinancialReviewService.save(symbol, review_date) 幂等落库

调度节奏（见 scheduler_jobs.yaml）：
    **每小时触发一次**，每次从监控池里挑「近 interval 天（默认 7 天）内没点评过的」最多
    per_run 只（默认 5 只）生成点评。靠「一周内点评过的不在候选」实现每票每周最多一次，
    池子较大时多轮即可在数天内铺满一轮，之后整周静默直到下一周。

## 与股吧情绪任务（job_stock_guba_sentiment）的异同
- 同：**批量、单只失败隔离、不投队列**（队列 prefetch=1 串行会堵住其它任务）。
- 异：本任务单只更重（4 次财务取数 + 一次长文 LLM），token 消耗显著，所以按「7 天间隔 +
      每轮限量」节流，而不是一次性把池子跑完。

## 失败处理
- 取数失败 / LLM 失败 / 落库失败 → 只记日志、不抛异常、不落库，单只失败不影响整批。
- 这与股吧任务一致：批量任务里「少一个数据点」远好过「填假值」或「拖垮整批」。
"""

import json
from datetime import date
from typing import Any, Dict, Optional

from config import fin_review_max_symbols, fin_review_per_run, fin_review_interval_days
from models.database import db_session
from service import StockService
from service.stock_financial_review import StockFinancialReviewService
from utils.logger import logger


# ---------------------------------------------------------------- 单只流程

def analyze_symbol(symbol: str, periods: int = 12) -> Optional[Dict[str, Any]]:
    """分析单只股票并落库。返回落库记录；跳过/失败返回 None。

    ⚠️ 本函数只负责「有数据就生成」；是否「到了该点评的时间」由调用方（job 入口）用
    7 天间隔过滤，不在本函数内做节流，避免单只被反复挑中却反复空跑。
    """
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

    # 2) 生成（非流式）
    try:
        result = StockFinancialReviewService.generate_review(symbol, stock_name='', periods=periods)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[fin_review] {symbol} 生成失败，跳过：{e}')
        return None

    # 3) 落库
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


def job_stock_financial_review_hourly():
    """每小时批量：从监控池挑「近 interval 天内未点评」的最多 per_run 只生成点评。

    ⚠️ 与股吧任务一致，**不投递到 job 队列**：本任务单只耗时长（4 次取数 + 一次长文 LLM），
    投队列会串行占用 prefetch=1 的消费槽，把其它用户的任务堵在后面。这里在调度进程里
    同步跑，单只失败已隔离，整批耗时可预期。
    """
    interval = max(1, int(fin_review_interval_days))
    per_run = max(1, int(fin_review_per_run))

    try:
        stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    except Exception as e:  # noqa: BLE001
        logger.error(f'[fin_review] 取监控池失败，本次任务中止：{e}')
        return

    symbols = [s.get('symbol') for s in stocks if s.get('symbol')]
    db_session.remove()  # 释放 search_stocks 占用的会话
    if not symbols:
        logger.info('[fin_review] 监控池为空，跳过')
        return

    # 监控池上限：只在前 N 只里挑（N 通常远大于单轮 per_run，保证多轮能覆盖）
    pool_limit = max(1, int(fin_review_max_symbols))
    if len(symbols) > pool_limit:
        logger.info(f'[fin_review] 监控池 {len(symbols)} 只超过上限 {pool_limit} 只，只在前 {pool_limit} 只内挑选')
        symbols = symbols[:pool_limit]

    # 候选过滤：剔除近 interval 天内已点评过的（实现「一周内点评过的不再点评」）
    try:
        reviewed = StockFinancialReviewService.get_reviewed_symbols_within_days(interval)
    except Exception:  # noqa: BLE001
        reviewed = set()
    candidates = [s for s in symbols if s not in reviewed]

    if not candidates:
        logger.info(f'[fin_review] 近 {interval} 天内均已点评过，本轮无可点评候选，跳过')
        return

    batch = candidates[:per_run]
    logger.info(
        f'[fin_review] 每小时批量：池 {len(symbols)} 只 / 近 {interval} 天已点评 {len(reviewed)} 只 / '
        f'本轮挑选 {len(batch)} 只：{batch}'
    )

    ok_cnt = skip_cnt = fail_cnt = 0
    for symbol in batch:
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

    logger.info(f'[fin_review] 本轮结束：成功 {ok_cnt} / 跳过 {skip_cnt} / 失败 {fail_cnt}')


if __name__ == '__main__':
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else '600519'
    print(json.dumps(analyze_symbol(target), ensure_ascii=False, indent=2, default=str))
