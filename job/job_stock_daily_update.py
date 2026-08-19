"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from service import FactorValueService
from utils.common import get_today
from utils.beta_calculate import calculate_beta
from service.stock import StockService
from utils.data_loader import databull
from utils.common import logger

def job_update_stock_beta_all():

    market_index = "000001"
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    start_date = "20260101"
    end_date = get_today()

    # 循环对个股进行每日挖掘
    for stock in stocks:
        stock_code = stock.get('symbol')
        if stock.get('market') != 'cn':
            continue
        beta = calculate_beta(stock_code, market_index, start_date=start_date, end_date=end_date)
        logger.info(f"The Beta of #({stock_code}) relative to {market_index} is: {beta:.3f}")
        FactorValueService.create(
            trade_date=get_today(_format='%Y-%m-%d'),
            ticker=stock_code,
            factor_name='beta',
            value=beta
        )

def job_fix_ohlc_last_all():
    markets = ['cn', 'us', 'hk']
    for market in markets:
        stocks = StockService.get_monitoring_stock_pool(market=market, per_page=10000)
        for stock in stocks:
            job_fix_ohlc_last(stock_code=stock['symbol'])


def job_fix_ohlc_last(stock_code):
    tick_last = databull.get_last_tick(symbol=stock_code)
    if 'lastPrice' not in tick_last:
        return
    tick_last['close'] = tick_last['lastPrice']
    tick_last['chg_pct'] = (tick_last['lastPrice'] - tick_last['lastClose']) / tick_last['lastClose'] * 100
    StockService.upsert_stock({
        'symbol': stock_code,
        'ohlc_last': tick_last
    })
    logger.info(f"更新个股信息, {stock_code}, {tick_last}")


def job_sync_data():

    stock_list = databull.get_stock_list()

    for stock in stock_list['data']:
        logger.info(f"更新个股信息, {stock['symbol']}, {stock['name']}")
        StockService.upsert_stock({
            'symbol': stock['symbol'],
            'name': stock['name'],
        })


def job_stock_daily_update():
    # job_sync_data()
    job_fix_ohlc_last_all()


if __name__ == '__main__':

    job_stock_daily_update()
