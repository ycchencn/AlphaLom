"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from service.stock import StockService
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis
from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_check_signal import job_check_signal
from job.job_update_factors import job_update_stock_factor
from utils.data_loader import databull


def job_stock_analysis(stock_code, send_notification=False):

    if not StockService.exists(stock_code):
        # 个股不在数据库，查询api获取
        stock_api = databull.get_stock_info(stock_code, market='cn')
        # 自动添加
        StockService.upsert_stock({
            'symbol': stock_code,
            'ts_code': stock_api.get('ts_code'),
            'name': stock_api.get('name'),
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


if __name__ == '__main__':

    stock_codes = [
        '300972'
    ]

    for stock_code in stock_codes:
        job_stock_analysis(stock_code)
