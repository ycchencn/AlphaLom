"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from service.stock import StockService
from utils.data_loader import databull
from utils.common import logger


def job_fix_ohlc_last_all():
    markets = ['cn', 'us', 'hk']
    for market in markets:
        stocks = StockService.get_monitoring_stock_pool(market=market, per_page=10000)
        for stock in stocks:
            job_fix_ohlc_last(stock_code=stock['symbol'])


def job_fix_ohlc_last(stock_code):
    tick_last = databull.get_last_tick(symbol=stock_code)
    # {'time': 1786692600001, 'lastPrice': 6.93, 'open': 6.96, 'high': 6.98, 'low': 6.89, 'lastClose': 6.97, 'amount': 231931200, 'volume': 334879}
    # update_res = StockService.upsert_stock({
    #     'symbol': stock_code,
    #     'ohlc_last': {
    #         "low": 6.89, "high": 6.98, "open": 6.96, "close": 6.93, "chg_pct": -0.5739
    #     }
    # })
    tick_last['close'] = tick_last['lastPrice']
    tick_last['chg_pct'] = (tick_last['lastPrice'] - tick_last['lastClose']) / tick_last['lastClose'] * 100
    update_res = StockService.upsert_stock({
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


if __name__ == '__main__':
    # job_sync_data()

    job_fix_ohlc_last_all()