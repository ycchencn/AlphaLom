"""
 * @author Yc
 * A 股每日估值快照落库（PE-TTM / PB），支撑个股详情页顶部报价与基本面走势图。

 * 数据来源 databull `get_stock_info`（返回 pe_ttm / pb / valuation_date）。
 * ⚠️ **只对 A 股**：上游对港股/美股/ETF 调用直接 500（实测），本任务只枚举
 * `stocks.market='cn'` 的监控池标的，天然与产品口径「PE-TTM 只做 A 股」一致。
 *
 * ⚠️ 逐日累积、必须幂等：像板块快照一样，今天不跑今天的数据就永久缺失，
 * 走势图会断档。任务按 (symbol, trade_date) 幂等 upsert（见
 * service/stock_valuation_service.py），重复触发不报错。
"""

from datetime import date

from service import StockService
from service.stock_valuation_service import StockValuationService
from utils.data_loader import databull
from utils.logger import logger


def _parse_valuation_date(raw) -> date | None:
    """上游 valuation_date 可能是 '2026-10-09' / date / None。"""
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, str):
        return raw
    s = str(raw).strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        # '20261009' 兼容
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        logger.warning(f'无法解析 valuation_date: {raw!r}')
        return None


def _fetch_and_upsert(symbol: str) -> bool:
    """抓单只 A 股的估值并落库。上游 500 / 无 pe_ttm 时跳过（静默，不拖垮整批）。"""
    try:
        info = databull.get_stock_info(symbol=symbol)
    except Exception as e:
        # get_stock_info 对非 A 股 / 无数据标的会抛错，单只失败不能中断整批
        logger.warning(f'get_stock_info failed for {symbol}: {e}')
        return False
    if not isinstance(info, dict):
        return False

    # 上游对非 A 股会 500，但防御性再确认一下有没有 pe_ttm
    pe_ttm = info.get('pe_ttm')
    if pe_ttm is None:
        logger.info(f'{symbol} 无 pe_ttm，跳过（非 A 股或暂无估值）')
        return False

    trade_date = _parse_valuation_date(info.get('valuation_date')) or date.today()
    return StockValuationService.upsert_daily(
        symbol=symbol,
        trade_date=trade_date,
        pe_ttm=pe_ttm,
        pb=info.get('pb'),
        total_volume=info.get('total_volume'),
    )


def job_update_stock_valuation_daily(override=False):
    """每日盘后更新 A 股监控池的 PE-TTM / PB 估值快照。

    只枚举 `stocks.market='cn'` 且 monitoring=1 的标的（A 股）；上游不给港股/美股
    PE，枚举了也只会白打一堆 500。同一天重复触发由唯一键幂等兜住。
    """
    stocks = StockService.search_stocks(
        securities_type='stock', monitoring=1, per_page=10000, market='cn')
    symbols = [s['symbol'] for s in stocks]
    if not symbols:
        logger.info('估值日更：A 股监控池为空，跳过')
        return

    ok = 0
    for symbol in symbols:
        if _fetch_and_upsert(symbol):
            ok += 1

    last_date = StockValuationService.get_last_trade_date()
    logger.info(f"估值日更完成：A 股 {len(symbols)} 只，成功 {ok} 只，最新估值日 {last_date}")


if __name__ == '__main__':
    job_update_stock_valuation_daily()
