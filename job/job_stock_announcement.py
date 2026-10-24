"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

公司公告同步任务（巨潮资讯网 → DataBull → 本地 `stock_announcements`）。

链路：
    枚举监控池（A 股）
      -> 逐只：翻页拉取 /cn/stock/announcements（page_size=100）
      -> normalize + 标题关键词分类
      -> INSERT ... ON DUPLICATE KEY UPDATE 幂等落库
      -> 记录每只票的同步状态（ok/empty/error/skipped）

## 为什么是「翻页到已入库日期为止」而不是按日期过滤

上游 `start_date` / `end_date` 参数**实际不生效**（实测传 2026-10-01 后 total 不变），
唯一可用的截断信号是「翻到的页面里出现已入库的最新日期」。所以每只票的增量逻辑是：
  1. 取该票已入库的最大公告日期作为锚点（`get_last_announce_dates`）；
  2. 从第 1 页往回翻，某页出现 `announce_date <= 锚点` 的行就停（说明已接上历史）；
  3. 没有锚点（首次）则按 `announcement_backfill_pages` 多翻几页做回填。
正常情况下第 1 页就停 —— 每天每只票只多花 1 次请求。

## 为什么不用 job 队列

同 `job_stock_guba_sentiment`：队列是 prefetch=1 串行消费，几百只票 × 0.5 秒间隔会
把其它分析任务堵在后面。这里在调度进程里同步跑，单只失败已隔离，整批耗时可预期
（200 只 × 1.5 秒 ≈ 5 分钟）。单只票的手动刷新才走队列（见 job_stock_announcement_sync_symbol）。

## 失败与「空」必须分开

上游覆盖不完整（600519 / 600036 等恒为空），空数组是**合法结果**，状态记 `empty`；
网络/HTTP 异常才记 `error` 并在下一轮优先重试。混为一谈会让「上游没收录」被误判成
「同步挂了」，运维时看不出真问题。
"""

import time
from datetime import date
from typing import Any, Dict, List, Optional

from config import (
    announcement_backfill_pages,
    announcement_retention_days,
    announcement_sync_interval,
    announcement_sync_max_pages,
    announcement_sync_page_size,
    announcement_sync_symbol_limit,
)
from models import UserStockPool
from models.database import db_session
from service import StockService
from service.stock_announcement_service import (
    StockAnnouncementService,
    default_retention_cutoff,
    is_a_share_symbol,
    normalize_row,
)
from utils.data_loader import databull
from utils.logger import logger


def _is_a_share(symbol: str) -> bool:
    """是否为可同步的 A 股（排除港股/美股、ETF 号段）。

    判定统一走 service 里的 `is_a_share_symbol` —— 页面上的「非 A 股不在覆盖范围」
    提示用的是同一个函数，避免两处口径漂移。
    """
    return is_a_share_symbol(symbol)


def _pool_symbols() -> List[str]:
    """同步范围 = 监控池并集（`stocks.monitoring=1` ∪ 所有用户的股票池）。

    ⚠️ 两个来源都要取：`monitoring` 是给任务用的并集标记，靠
    `StockService.sync_monitoring_flag` 维护，理论上等价于 user_stock_pool 的并集；
    但它是「派生状态」，历史上出现过没同步上的情况（用户自己的票在池里、标记却没置 1）。
    公告同步是公共数据，多抓一只票的成本只是 1 次请求，比漏掉一个用户的票划算。
    """
    symbols: Dict[str, None] = {}

    try:
        stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
        for s in stocks:
            code = str(s.get('symbol') or '').strip()
            if code:
                symbols[code] = None
    except Exception as e:  # noqa: BLE001
        logger.warning(f'[announcement] 取监控池失败（继续用用户股票池兜底）：{e}')

    try:
        rows = db_session.query(UserStockPool.symbol).distinct().all()
        for (code,) in rows:
            code = str(code or '').strip()
            if code:
                symbols[code] = None
    except Exception as e:  # noqa: BLE001
        logger.warning(f'[announcement] 取用户股票池失败（继续用监控池）：{e}')
        db_session.rollback()
    finally:
        # scoped_session 是线程级的，任务里用完即还，避免把事务状态带给下一个 job
        db_session.remove()

    return [code for code in symbols if _is_a_share(code)]


# ---------------------------------------------------------------- 单只同步

def sync_symbol(symbol: str, *, max_pages: Optional[int] = None,
                anchor: Optional[date] = None, interval: Optional[float] = None,
                record_state: bool = True) -> Dict[str, Any]:
    """同步单只股票的公告，返回结果摘要（不抛异常）。

    :param max_pages: 本次最多翻几页；None 时按「有无锚点」自动选
                      （有锚点 = 增量页数，无锚点 = 回填页数）
    :param anchor: 已入库的最新公告日期；None 时内部查库
    :param interval: 页间间隔秒数；None 取配置
    :param record_state: 是否写 `stock_announcement_sync`（批量任务写，临时调用可不写）
    """
    symbol = str(symbol or '').strip()
    result: Dict[str, Any] = {
        'symbol': symbol, 'status': 'error', 'pages': 0, 'rows': 0,
        'last_date': None, 'error': None,
    }
    if not _is_a_share(symbol):
        result['status'] = 'skipped'
        result['error'] = '非 A 股代码，上游不覆盖'
        return result

    if anchor is None:
        anchor = StockAnnouncementService.get_last_announce_dates([symbol]).get(symbol)
    if max_pages is None:
        max_pages = announcement_sync_max_pages if anchor else announcement_backfill_pages
    page_size = max(1, min(int(announcement_sync_page_size), 100))  # 上游上限 100
    gap = announcement_sync_interval if interval is None else interval

    collected: Dict[str, Dict[str, Any]] = {}   # announcement_id -> row（页间可能重叠）
    pages = 0
    error: Optional[str] = None

    for page in range(1, int(max_pages) + 1):
        try:
            items, meta = databull.get_stock_announcements_paged(
                stock=symbol, page=page, page_size=page_size)
        except Exception as e:  # noqa: BLE001
            # 失败不丢已抓到的数据：部分页也可能有价值，先把手上有的写进去
            error = str(e)[:200]
            logger.warning(f'[announcement] {symbol} 第 {page} 页拉取失败：{error}')
            break

        pages += 1
        if not items:
            break

        page_dates: List[date] = []
        for raw in items:
            row = normalize_row(raw, symbol)
            if not row:
                continue
            collected[row['announcement_id']] = row
            page_dates.append(row['announce_date'])

        # 停止条件：本页已出现「早于/等于锚点」的公告 → 历史已接上
        if anchor and page_dates and min(page_dates) <= anchor:
            break
        if not meta.get('has_more'):
            break
        if page < int(max_pages) and gap > 0:
            time.sleep(gap)

    rows = list(collected.values())
    written = StockAnnouncementService.upsert_many(rows) if rows else 0
    last_date = max((r['announce_date'] for r in rows), default=None)

    if error:
        status = 'error'
    elif not rows:
        # 上游确实没收录这只票的公告 —— 合法结果，不是失败
        status = 'empty'
    else:
        status = 'ok'

    result.update({
        'status': status,
        'pages': pages,
        'rows': written,
        'last_date': last_date.isoformat() if last_date else None,
        'error': error,
    })

    if record_state:
        StockAnnouncementService.upsert_sync_state(
            symbol, status,
            last_announce_date=last_date,
            error=error,
            pages=pages,
            rows=written,
        )
    return result


# ---------------------------------------------------------------- job 入口

def job_stock_announcement_sync_symbol(_stock_code: str):
    """单只票同步（手动刷新入口，走 job 队列）。参数名与 JobService.send_job 对齐。"""
    try:
        result = sync_symbol(_stock_code)
        logger.info(f'[announcement] 手动同步完成 {result}')
    finally:
        db_session.remove()


def job_stock_announcement_sync_daily(max_symbols: Optional[int] = None,
                                      retention_days: Optional[int] = None):
    """每日批量：枚举监控池 A 股，逐只增量同步。

    - 单只失败隔离（只记状态，不中断整批）；
    - 池内票数超过 `announcement_sync_symbol_limit` 时按「最久未同步」排序截断，
      避免池子异常膨胀时一轮把配额打满（没轮到的下一轮优先）。
    """
    symbols = _pool_symbols()
    if not symbols:
        logger.info('[announcement] 监控池为空，跳过本轮同步')
        return

    limit = int(max_symbols or announcement_sync_symbol_limit or 0)
    if limit > 0 and len(symbols) > limit:
        # 优先同步「从没同步过 / 最久没同步」的票：按 last_sync_time 升序，None 排最前
        states = StockAnnouncementService.get_sync_states(symbols)
        symbols.sort(key=lambda s: (states.get(s, {}) or {}).get('last_sync_time') or '')
        logger.warning(f'[announcement] 池内 {len(symbols)} 只超过单轮上限 {limit}，'
                       f'本轮只处理最久未同步的 {limit} 只')
        symbols = symbols[:limit]

    anchors = StockAnnouncementService.get_last_announce_dates(symbols)
    logger.info(f'[announcement] 开始同步，共 {len(symbols)} 只 A 股'
                f'（其中 {len(anchors)} 只有历史数据，其余走回填）')

    ok = empty = fail = 0
    started = time.time()
    for idx, symbol in enumerate(symbols, 1):
        try:
            result = sync_symbol(symbol, anchor=anchors.get(symbol))
        except Exception as e:  # noqa: BLE001
            # sync_symbol 内部已兜底，这里再兜一层：任何未预期异常都不能拖垮整批
            fail += 1
            logger.error(f'[announcement] {symbol} 同步异常：{e}')
            db_session.remove()
            continue

        if result['status'] == 'ok':
            ok += 1
        elif result['status'] == 'empty':
            empty += 1
        else:
            fail += 1

        if idx % 20 == 0:
            logger.info(f'[announcement] 进度 {idx}/{len(symbols)}（ok={ok} empty={empty} fail={fail}）')

    # 清理超期数据（默认 3 年；0 = 关闭）
    keep_days = announcement_retention_days if retention_days is None else retention_days
    cutoff = default_retention_cutoff(keep_days)
    if cutoff:
        StockAnnouncementService.purge_before(cutoff)

    elapsed = round(time.time() - started, 1)
    logger.info(f'[announcement] 同步结束：成功 {ok} / 无公告 {empty} / 失败 {fail}，'
                f'耗时 {elapsed}s')


if __name__ == '__main__':
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else '300750'
    print(json.dumps(sync_symbol(target), ensure_ascii=False, indent=2, default=str))
