"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from service import FactorValueService
from utils.common import get_today, get_date_by_n
from utils.beta_calculate import calculate_beta
from service.stock import StockService
from utils.data_loader import databull
from utils.logger import logger

import pandas as pd

# 全局配置：根据数据源接口限流、数据库连接池大小调整，IO密集型场景建议16~32，不要超过64避免打崩下游
MAX_WORKERS = 16

def job_update_stock_beta_all():
    market_index = "000001"
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    start_date = "20260101"
    end_date = get_today()
    trade_date = get_today(_format='%Y-%m-%d')
    
    # 过滤仅A股标的，减少无效任务
    cn_stocks = [s for s in stocks if s.get('market') == 'cn']
    total_cnt = len(cn_stocks)
    success_cnt = 0
    fail_cnt = 0

    logger.info(f"开始多线程计算全市场A股Beta，标的总数：{total_cnt}，并发数：{MAX_WORKERS}")

    # 线程池并行执行Beta计算+入库
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_map = {
            executor.submit(__beta_task, stock, market_index, start_date, end_date, trade_date): stock
            for stock in cn_stocks
        }
        # 收集执行结果
        for future in as_completed(future_map):
            try:
                res = future.result()
                if res:
                    success_cnt += 1
                else:
                    fail_cnt +=1
            except Exception as e:
                fail_cnt +=1
                stock_code = future_map[future].get('symbol')
                logger.error(f"标的{stock_code} Beta计算执行异常: {str(e)}")
    
    logger.info(f"全市场Beta计算任务完成，总标的{total_cnt}，成功{success_cnt}，失败{fail_cnt}")

# 子任务抽离，隔离单标的逻辑
def __beta_task(stock, market_index, start_date, end_date, trade_date):
    stock_code = stock.get('symbol')
    beta = calculate_beta(stock_code, market_index, start_date=start_date, end_date=end_date)
    if beta is None or abs(beta) > 10: # 异常值过滤，避免脏数据入库
        logger.warning(f"标的{stock_code} Beta值异常({beta})，跳过入库")
        return False
    logger.debug(f"The Beta of #({stock_code}) relative to {market_index} is: {beta:.3f}")
    FactorValueService.create(
        trade_date=trade_date,
        ticker=stock_code,
        factor_name='beta',
        value=beta
    )
    return True


def job_fix_ohlc_last_all():
    markets = ['cn', 'us', 'hk']
    # (symbol, market) 成对收集：美股/港股必须显式带 market，走各自的日线接口
    # （get_us_stock_history / get_hk_stock_history）取最新一根 K 线对齐格式；
    # 复用 cn 的实时接口（默认 market='cn'）会取不到数据、ohlc_last 恒为空。
    all_stocks = []
    for market in markets:
        stocks = StockService.get_monitoring_stock_pool(market=market, per_page=10000)
        all_stocks.extend([(s['symbol'], market) for s in stocks])

    total_cnt = len(all_stocks)
    success_cnt = 0
    fail_cnt = 0
    logger.info(f"开始多线程更新全市场最新行情快照，标的总数：{total_cnt}，并发数：{MAX_WORKERS}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(job_fix_ohlc_last, symbol, market): symbol
            for symbol, market in all_stocks
        }
        for future in as_completed(future_map):
            try:
                future.result()
                success_cnt +=1
            except Exception as e:
                fail_cnt +=1
                stock_code = future_map[future]
                logger.error(f"标的{stock_code} 更新最新行情异常: {str(e)}")

    logger.info(f"全市场最新行情更新任务完成，总标的{total_cnt}，成功{success_cnt}，失败{fail_cnt}")


def _strip_market_suffix(symbol: str) -> str:
    """美股/港股代码可能带 .US / .HK 后缀（如 AAPL.US、00700.HK）。

    databull 的 us/hk 行情接口只认裸码（AAPL、00005，港股保留前导零），
    带后缀会稳定 400。库内现有记录多为裸码，这里兜底再剥一层，避免
    「新增入库的票带了后缀」时直接 400 拿不到数据。
    """
    s = (symbol or '').strip().upper()
    if s.endswith('.US') or s.endswith('.HK'):
        return s[:-3]
    return s


def _ohlc_last_from_daily(df):
    """把美股/港股日线 DataFrame 的最新一根 K 线，映射成与 A 股 get_realtime
    同构的 ohlc_last 字典（前端 WatchList / StockDetail / WatchlistPanel 等
    都按 lastPrice / lastClose / close / chg_pct 读取，字段必须对齐）。

    databull 日线列：timestamp, open, close, high, low, volume, change_amount,
    chg_pct, amplitude。其中 change_amount = close - 前收，与 A 股实时接口的
    lastClose 语义一致；lastClose 优先取上一根收盘，缺失时回退 change_amount。
    """
    if df is None or len(df) == 0:
        return None
    df = df.sort_index()  # 按日期升序，最后一行即最新
    last = df.iloc[-1]
    close = float(last['close'])
    if len(df) >= 2:
        last_close = float(df.iloc[-2]['close'])
    else:
        change_amount = float(last['change_amount']) if pd.notna(last.get('change_amount')) else 0.0
        last_close = close - change_amount
    chg_pct = (close - last_close) / last_close * 100 if last_close else 0.0

    def _num(v):
        return float(v) if pd.notna(v) else None

    return {
        'time': int(last['timestamp']) if pd.notna(last.get('timestamp')) else None,
        'lastPrice': close,
        'lastClose': last_close,
        'open': _num(last.get('open')),
        'high': _num(last.get('high')),
        'low': _num(last.get('low')),
        'volume': _num(last.get('volume')),
        'amount': None,  # 日线接口不返回成交额字段
        'close': close,
        'chg_pct': chg_pct,
    }


def job_fix_ohlc_last(stock_code, market=None):
    # market 未显式传入时，从库内标的记录回查（新增入库的票 market 已落库）。
    if market is None:
        rec = StockService.get_stock_by_symbol(stock_code, fields=['market'])
        market = (rec or {}).get('market') or 'cn'

    # A 股：实时接口（/cn/stock/tick）正常返回 lastPrice / lastClose，沿用原逻辑。
    if market == 'cn':
        tick_last = databull.get_realtime(symbol=stock_code, market='cn')
        if 'lastPrice' not in tick_last:
            return False
        tick_last['close'] = tick_last['lastPrice']
        tick_last['chg_pct'] = (tick_last['lastPrice'] - tick_last['lastClose']) / tick_last['lastClose'] * 100
        StockService.upsert_stock({
            'symbol': stock_code,
            'ohlc_last': tick_last
        })
        logger.debug(f"更新个股信息, {stock_code}, {tick_last}")
        return True

    # 美股 / 港股：databull 实时接口（/us/stock/tick、/hk/stock/tick）不提供数据，
    # 只能走日线接口（/us/stock/history、/hk/stock/history），取最新一根 K 线对齐格式。
    start_date = get_date_by_n(-15, _format='%Y%m%d')
    end_date = get_today()  # YYYYMMDD
    symbol = _strip_market_suffix(stock_code)
    if market == 'us':
        df = databull.get_us_stock_history(symbol, start_date=start_date, end_date=end_date)
    elif market == 'hk':
        df = databull.get_hk_stock_history(symbol, start_date=start_date, end_date=end_date)
    else:
        return False

    ohlc = _ohlc_last_from_daily(df)
    if ohlc is None:
        return False
    StockService.upsert_stock({
        'symbol': stock_code,
        'ohlc_last': ohlc
    })
    logger.debug(f"更新个股信息(日线), {stock_code}, {ohlc}")
    return True


def job_sync_data():
    # 基础信息同步覆盖全部市场；__sync_single_stock 已按标的真实 market 取概况
    stock_list = []
    for market in ('cn', 'hk', 'us'):
        stock_list.extend(StockService.get_monitoring_stock_pool(market=market, per_page=10000))
    total_cnt = len(stock_list)
    success_cnt = 0
    logger.info(f"开始多线程全量同步股票基础信息，标的总数：{total_cnt}，并发数：{MAX_WORKERS//2}")
    
    # 基础信息写入量小，用减半并发避免数据库写入压力过高
    with ThreadPoolExecutor(max_workers=MAX_WORKERS//2) as executor:
        future_map = {executor.submit(__sync_single_stock, stock): stock for stock in stock_list}
        for future in as_completed(future_map):
            try:
                future.result()
                success_cnt +=1
            except Exception as e:
                stock = future_map[future]
                logger.error(f"标的{stock['symbol']} 基础信息同步异常: {str(e)}")

    logger.info(f"全量股票基础信息同步完成，总标的{total_cnt}，成功{success_cnt}")

def __sync_single_stock(stock):
    """刷新**已在库**标的的基础信息与公司概况。

    与 ensure_stock_from_api 的区别：这里不判在不在库、无条件覆盖更新，
    也不碰 market / monitoring 字段（避免覆盖用户的监控开关）。
    """
    record = {
        'symbol': stock['symbol'],
        'name': stock['name'],
        'name_en': stock['name'],
    }
    record.update(StockService.company_profile_fields(stock['symbol'], stock.get('market', 'cn')))
    StockService.upsert_stock(record)
    logger.debug(f"更新个股信息, {stock['symbol']}, {stock['name']}")
    return True


def job_stock_daily_update():
    job_sync_data()
    job_fix_ohlc_last_all()
    job_update_stock_beta_all() # 可选：如果beta不需要每日跑可以注释掉


if __name__ == '__main__':
    job_stock_daily_update()