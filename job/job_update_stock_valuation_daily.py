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
    """抓单只 A 股的估值并落库。上游 500 / 无 pe_ttm 时跳过（静默，不拖垮整批）。

    落库后把 PE-TTM 最新值**回写 stocks.pe_ratio**（个股监控列表直接读这张表，
    避免列表接口对每只票再查估值表造成 N+1，见 StockValuationService.sync_latest_to_stocks）。
    """
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
    ok = StockValuationService.upsert_daily(
        symbol=symbol,
        trade_date=trade_date,
        pe_ttm=pe_ttm,
        pb=info.get('pb'),
        total_volume=info.get('total_volume'),
    )
    if ok:
        # 最新值回写 stocks 表（列表接口零查询读取）
        StockValuationService.sync_latest_to_stocks(symbol, pe_ttm)
    return ok


def _collect_etf_constituents() -> set:
    """汇总系统内全部 ETF（watchlist ∪ rotation_pool）的 A 股成分代码（6 位，去后缀）。

    供「ETF 市盈率」因子(etf_pe_ttm)使用：该因子把成分股 PE 按权重聚合，
    而 `stock_daily_valuation` 原本只覆盖 A 股监控池，ETF 成分股大多不在其中
    → etf_pe_ttm 会整段为空。把成分股纳入估值落库范围即可。

    防御：单只 ETF / 单只成分收集失败都静默跳过，绝不拖垮整批。
    """
    try:
        from service.etf_service import EtfService
        from service.etf_rotation_service import EtfRotationService
        from service.etf_valuation_service import list_etf_astock_constituents
        etf_symbols = sorted(
            set(EtfService.list_all_symbols())
            | set(EtfRotationService.list_all_pool_symbols())
        )
    except Exception as e:
        logger.warning(f'收集 ETF 代码失败（估值覆盖扩展跳过）: {e}')
        return set()
    if not etf_symbols:
        return set()

    out = set()
    for sym in etf_symbols:
        try:
            out |= list_etf_astock_constituents(sym)
        except Exception as e:
            logger.warning(f'ETF {sym} 成分收集失败: {e}')
    return out


def job_update_stock_valuation_daily(override=False):
    """每日盘后更新 A 股估值快照（PE-TTM / PB），落库到 `stock_daily_valuation`。

    覆盖两类标的：
      1. `stocks.market='cn'` 且 monitoring=1 的 A 股监控池（个股监控列表 PE 直接读这张表）；
      2. 系统内全部 ETF（watchlist ∪ rotation_pool）的 A 股成分股 —— 供 etf_pe_ttm
         因子把成分股 PE 按权重聚合成「ETF 市盈率」。

    上游只对 A 股给 PE（港股/美股/ETF 调用直接 500），所以两类枚举都只含 A 股，
    枚举了非 A 股也只会白打一堆 500（_fetch_and_upsert 已按 pe_ttm 为空静默跳过）。
    同一天重复触发由唯一键幂等兜住。

    ⚠️ 顺序依赖：本任务须先于因子日更（job_update_factors）跑，否则当天的
    etf_pe_ttm 算出来会缺成分股 PE。两者都在盘后调度，本任务排在前。
    """
    stocks = StockService.search_stocks(
        securities_type='stock', monitoring=1, per_page=10000, market='cn')
    pool_symbols = [s['symbol'] for s in stocks]

    # ETF 成分股（A 股）作为额外覆盖，与监控池去重（避免重复打接口）
    etf_constituents = _collect_etf_constituents()
    etf_only = sorted(etf_constituents - set(pool_symbols))

    if not pool_symbols and not etf_only:
        logger.info('估值日更：无可覆盖标的，跳过')
        return

    ok = 0
    # 1) 监控池（个股列表 PE 的来源，保持原有路径不变，必须当天同步完成）
    for symbol in pool_symbols:
        if _fetch_and_upsert(symbol):
            ok += 1

    # 2) ETF 成分股（etf_pe_ttm 的 PE 来源；跨境/商品 ETF 的成分不在此列，已过滤）
    #    ⚠️ 改为 job server 异步并发：成分股规模 800~1200 只，若在此同步顺序打
    #    get_stock_info 会长时间阻塞主任务。改为投递 job，由多个 worker 并发消费。
    #    - 单只 job 幂等（upsert），重复执行无害；
    #    - 按 symbol 加当日 NX 冷却，避免重复触发（scheduler 重跑 / 手动重跑）重复打接口；
    #    - 因子日更(job_update_factors)的 etf_pe_ttm 聚合对「当天尚未落库的成分」自动
    #      跳过并权重重归一（见 update_etf_pe_factor），容忍短暂延迟；scheduler 已把因子
    #      日更排在估值日更之后，且 job 消费通常数分钟内完成。
    _dispatch_etf_constituent_jobs(etf_only)

    last_date = StockValuationService.get_last_trade_date()
    logger.info(
        f"估值日更完成：监控池同步 {len(pool_symbols)} 只（成功 {ok}），"
        f"ETF 成分 {len(etf_only)} 只已投递 job server 异步处理，最新估值日 {last_date}"
    )


def job_update_etf_constituent_valuation(symbol: str) -> None:
    """单只 ETF 成分股(A股)估值落库任务（job server 并发消费）。

    供 etf_pe_ttm 因子把成分股 PE 按权重聚合。单只失败不影响整批——
    worker 已捕获异常并 ACK 丢弃；upsert 幂等，重复执行无害。

    ⚠️ 本函数由 job_server worker 调用，签名必须与 dispatch 的 job_args 完全一致
    （仅 symbol 一个键），否则旧 worker 会 TypeError 丢弃消息。
    """
    try:
        _fetch_and_upsert(symbol)
    except Exception as e:
        logger.warning(f'[etf-constituent-valuation] {symbol} 落库失败: {e}')


def _dispatch_etf_constituent_jobs(symbols: list) -> int:
    """把 ETF 成分股估值任务投递到 job server（并发消费），返回成功投递数。

    单只按 symbol 加当日 NX 冷却，避免重复触发（scheduler 重跑 / 手动重跑）重复打接口；
    job 幂等，重复消费无害。投递失败时放开冷却键，允许下次重试。
    """
    if not symbols:
        return 0
    try:
        from service import JobService
        from utils.redis_obj import redis_obj
        dispatched = 0
        skipped = 0
        for symbol in symbols:
            cooldown_key = f'alphalom:etf_valuation:{symbol}'
            if not redis_obj.set(cooldown_key, '1', nx=True, ex=86400):
                skipped += 1
                continue
            try:
                JobService.send_job({
                    'job_func': 'job_update_etf_constituent_valuation',
                    'job_args': {'symbol': symbol},
                })
                dispatched += 1
            except Exception as e:
                logger.warning(f'[etf-constituent-valuation] 投递 {symbol} 失败: {e}')
                # 投递失败：放开冷却键，允许下次重试
                try:
                    redis_obj.delete(cooldown_key)
                except Exception:
                    pass
        logger.info(
            f'估值日更：ETF 成分股投递 job {dispatched} 只，冷却跳过 {skipped} 只')
        return dispatched
    except Exception as e:
        logger.warning(f'ETF 成分股估值 job 投递失败（整批）: {e}')
        return 0


if __name__ == '__main__':
    job_update_stock_valuation_daily()
