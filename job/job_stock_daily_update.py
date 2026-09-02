"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from service import FactorValueService
from utils.common import get_today
from utils.beta_calculate import calculate_beta
from service.stock import StockService
from utils.data_loader import databull
from utils.logger import logger

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
    all_stocks = []
    for market in markets:
        stocks = StockService.get_monitoring_stock_pool(market=market, per_page=10000)
        all_stocks.extend([s['symbol'] for s in stocks])
    
    total_cnt = len(all_stocks)
    success_cnt = 0
    fail_cnt = 0
    logger.info(f"开始多线程更新全市场最新行情快照，标的总数：{total_cnt}，并发数：{MAX_WORKERS}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(job_fix_ohlc_last, symbol): symbol for symbol in all_stocks}
        for future in as_completed(future_map):
            try:
                future.result()
                success_cnt +=1
            except Exception as e:
                fail_cnt +=1
                stock_code = future_map[future]
                logger.error(f"标的{stock_code} 更新最新行情异常: {str(e)}")
    
    logger.info(f"全市场最新行情更新任务完成，总标的{total_cnt}，成功{success_cnt}，失败{fail_cnt}")


def job_fix_ohlc_last(stock_code):
    tick_last = databull.get_last_tick(symbol=stock_code)
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


def job_sync_data():
    stock_list = databull.get_stock_list()['data']
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
    StockService.upsert_stock({
        'symbol': stock['symbol'],
        'name': stock['name'],
    })
    logger.debug(f"更新个股信息, {stock['symbol']}, {stock['name']}")
    return True


def job_stock_daily_update():
    job_sync_data()
    job_fix_ohlc_last_all()
    job_update_stock_beta_all() # 可选：如果beta不需要每日跑可以注释掉


if __name__ == '__main__':
    job_stock_daily_update()