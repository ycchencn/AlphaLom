"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
from service.stock import StockService
from service.user_watchlist_service import UserWatchlistService
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis
from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_check_signal import job_check_signal
from job.job_update_factors import job_update_stock_factor
from utils.data_loader import databull


def job_stock_analysis(stock_code, send_notification=False):
    stock_local = StockService.get_stock_by_symbol(stock_code)
    stock = databull.get_stock_info(stock_code, market=stock_local.get('market'))
    assert stock is not None
    if not StockService.exists(stock_code):
        StockService.upsert_stock({
            'symbol': stock_code,
            'ts_code': stock.get('ts_code'),
            'name': stock.get('name'),
            'market': 'cn',
            'securities_type': 'stock',
            'monitoring': 1
        })

    # 计算走势指标
    job_update_stock_greedy_data(index_code=stock_code, override_all=True)

    # 计算因子
    job_update_stock_factor(stock_code=stock_code, save_last=False, time_period=-1200)

    # DCF模型分析
    job_stock_dcf_model_analysis(stock_code, send_notification=send_notification)

    # 技术分析
    job_check_signal(stock_code)


def manual_analysis():
    items = UserWatchlistService.get_all()
    # 将对象转换为字典列表
    watchlist = [item.to_dict() for item in items] if items else []
    for item in watchlist:
        # print(item['stock_code'])
        # stock_info = StockService.get_stock_by_symbol(symbol=item['stock_code'])
        job_stock_analysis(item['stock_code'])


if __name__ == '__main__':

    stock_codes = [

    ]

    for stock_code in stock_codes:
        job_stock_analysis(stock_code)
