"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from service import FactorValueService, StockService, FactorCalService
from utils.common import logger, get_date_by_n, get_today
from utils.financial_data import INDICATOR_NAME_MAP
from service import JobService


def convert_to_factor_records(stock_code: str, formatted_dict: dict):
    """
    将 format_financial_data 的输出转为因子记录列表
    每条记录：{stock_code, report_date, factor_name, value}
    """
    records = []
    for chinese_name, date_value_map in formatted_dict.items():
        english_name = INDICATOR_NAME_MAP.get(chinese_name)
        if english_name is None:
            print(f"⚠️ 未映射的指标名: {chinese_name}，跳过")
            continue
        for report_date, value in date_value_map.items():
            records.append({
                'stock_code': stock_code,
                'report_date': report_date,
                'factor_name': english_name,
                'value': value
            })
    return records


def format_financial_data(df):
    result = {}
    report_cols = [col for col in df.columns if col not in ['选项', '指标']]

    for _, row in df.iterrows():
        indicator = row['指标']
        if pd.isna(indicator):
            continue
        indicator = str(indicator).strip()
        time_series = {}
        for col in report_cols:
            val = row[col]
            if pd.notna(val) and str(val).strip() not in ('--', '-', '', 'None'):
                # 格式化日期：20250930 → 2025-09-30
                date_str = f"{col[:4]}-{col[4:6]}-{col[6:]}"
                # 尝试保留数值类型（避免字符串）
                try:
                    num_val = float(val)
                    time_series[date_str] = num_val
                except (ValueError, TypeError):
                    time_series[date_str] = str(val).strip()
        result[indicator] = time_series
    return result


def job_update_stock_factor_daily():
    # 判断交易日
    if FactorValueService.is_trading_day() is False:
        return

    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)

    # 循环对个股进行每日挖掘
    for stock in stocks:
        JobService.send_job({
            'job_func': 'job_update_stock_factor',
            'job_args': {
                'stock_code': stock['symbol'],
                'save_last': True,
                'time_period': -120,
            }
        })


def job_update_stock_factor_daily_all():
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    # 循环对个股进行每日挖掘
    for stock in stocks:
        job_update_stock_factor(stock_code=stock['symbol'], save_last=True, time_period=-360)


def job_update_stock_factor(stock_code, trade_date=None, save_last=False, time_period=-360):
    """
    计算个股的因子数据
    """

    if trade_date is None:
        trade_date = get_today(_format='%Y%m%d')

    logger.info(f"计算因子数据：{stock_code}")

    # 2、计算所有因子
    factors = FactorCalService.calculate_all_factors(stock_code, get_date_by_n(time_period, _format='%Y%m%d'), trade_date)

    if len(factors) == 0:
        return

    # 3、因子数据入库（长表）
    if save_last:
        FactorCalService.save_factor_records_to_db(stock_code, [factors[-1]])
    else:
        # 清空旧因子数据
        FactorValueService.delete_by_ticker(stock_code=stock_code)
        FactorCalService.save_factor_records_to_db(stock_code, factors)


if __name__ == '__main__':
    # job_update_financial_factors_by_index_constituents(index_code='000016')
    # df = get_financial_df(stock='600111')

    # job_update_stock_factor(stock_code='300750', save_last=False, time_period=-365)

    job_update_stock_factor_daily_all()
