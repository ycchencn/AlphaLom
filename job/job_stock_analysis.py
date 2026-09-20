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
from job.job_stock_daily_update import job_fix_ohlc_last


def job_stock_analysis(stock_code, send_notification=False):

    # 不在数据库则自动添加（从 API 补全名称 + 公司概况）
    StockService.ensure_stock_from_api(stock_code)

    # 计算走势指标
    job_update_stock_greedy_data(index_code=stock_code, override_all=True)

    # 计算因子
    job_update_stock_factor(stock_code=stock_code, save_last=False, time_period=-1200)

    # DCF模型分析
    job_stock_dcf_model_analysis(stock_code, send_notification=send_notification)

    # 技术分析
    job_check_signal(stock_code)

    # 最新报价
    job_fix_ohlc_last(stock_code)


if __name__ == '__main__':

    stock_codes = [
        '600362'
    ]

    for stock_code in stock_codes:
        job_stock_analysis(stock_code)
