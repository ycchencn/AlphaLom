"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from service import FactorValueService, StockService, FactorCalService
from service.etf_service import EtfService
from utils.common import get_date_by_n, get_today
from utils.logger import logger
from utils.financial_data import INDICATOR_NAME_MAP
from service.stock_financial_score import StockFinancialScoreService
from service.fundamental_service import compute_fundamental_scores
from service import JobService


# 因子计算所需的历史长度（自然日）。
# 52 周区间因子要 252 个交易日 ≈ 370 个自然日，取 400 留出长假冗余 —— 取数不足 252 根时
# rolling(min_periods=1) 不会报错，只会把「52 周高低」静默算成「最近 N 个交易日高低」
# （旧日更任务只取 120 个自然日 ≈ 82 根 K 线，52week_low 实际就是 82 日低点）。
FACTOR_LOOKBACK_DAYS = 400


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


def _send_factor_jobs(symbols, asset_type, save_last=True,
                      time_period=-FACTOR_LOOKBACK_DAYS):
    """
    把「逐标的算因子」投进任务队列（投递端只投递，真正的计算由 job_server 消费执行）。

    asset_type 必须显式传：ETF 与个股取行情的接口不同（get_etf_history / get_history），
    靠代码号段去猜会漏 —— 历史上 562xxx 不在 ETF 前缀白名单里，被当个股取数只拿到 2 根
    K 线，因子全被 dropna 掉。
    """
    for symbol in symbols:
        JobService.send_job({
            'job_func': 'job_update_stock_factor',
            'job_args': {
                'stock_code': symbol,
                'asset_type': asset_type,
                'save_last': save_last,
                'time_period': time_period,
            }
        })


def job_update_stock_factor_daily():
    """
    日更技术面因子：个股池 + ETF 监控清单。

    ⚠️ ETF 与个股用的是同一套因子算法（FactorCalService 按 asset_type 选行情接口），
    但这里原先只枚举了 stocks 表里 securities_type='stock' 的标的，ETF 监控清单
    （etf_watchlist 表，页面上的「ETF 洞察」列表）完全没有被覆盖 —— 于是 ETF 的
    52week_low / 52week_high 等因子从未入库，列表与详情页的 52 周区间一直是 0.00 / 空。
    """
    # 判断交易日
    if FactorValueService.is_trading_day() is False:
        return

    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    # ⚠️ ETF 取「全部用户自选的去重并集」：本任务没有用户上下文，因子是按标的算的公共数据
    etf_symbols = EtfService.list_all_symbols()

    # 循环对个股进行每日挖掘
    _send_factor_jobs([stock['symbol'] for stock in stocks], asset_type='stock')

    # ETF 监控清单：和个股同一套因子，只是行情接口不同
    _send_factor_jobs(etf_symbols, asset_type='etf')

    logger.info(f"因子日更任务已投递：个股 {len(stocks)} 只、ETF {len(etf_symbols)} 只")


def job_update_stock_factor_daily_all():
    """同步重算（不投队列）：个股池 + ETF 监控清单。用于手动执行 / 首次回填。"""
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)
    # 循环对个股进行每日挖掘
    for stock in stocks:
        job_update_stock_factor(stock_code=stock['symbol'], asset_type='stock',
                                save_last=True, time_period=-FACTOR_LOOKBACK_DAYS)

    for symbol in EtfService.list_all_symbols():
        job_update_stock_factor(stock_code=symbol, asset_type='etf',
                                save_last=True, time_period=-FACTOR_LOOKBACK_DAYS)


def job_update_etf_factor_all():
    """
    ETF 专用回填：把监控清单里的每只 ETF 的因子按最新交易日重新算一遍（同步执行）。

    新加入监控的 ETF 在下一个日更任务跑之前是没有因子的，可以先跑这个补上。
    """
    symbols = EtfService.list_all_symbols()
    logger.info(f"开始回填 ETF 因子，共 {len(symbols)} 只")
    for symbol in symbols:
        job_update_stock_factor(stock_code=symbol, asset_type='etf',
                                save_last=True, time_period=-FACTOR_LOOKBACK_DAYS)


def job_update_financial_score_all():
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000, market='cn')
    # 循环对个股进行每日挖掘
    for stock in stocks:
        res = compute_fundamental_scores(stock_code=stock['symbol'], start_date=get_date_by_n(-365), end_date=get_today())
        StockFinancialScoreService.upsert(res)
        print(res)

def job_update_stock_factor(stock_code, trade_date=None, save_last=False, time_period=-360,
                            asset_type=None):
    """
    计算单个标的（个股或 ETF）的因子数据并入库。

    :param asset_type: 'etf' / 'stock'；None 时由 FactorCalService 按代码号段推断。
        批量 / 队列任务一律显式传，不依赖号段猜测。
    :param save_last: 只落最新一个交易日（日更用）；False 时先清空该标的历史因子再整段重写。
    :param time_period: 取数窗口（自然日，负数表示过去）。**它只是下限**：不足
        FACTOR_LOOKBACK_DAYS 会自动放宽，保证 52 周因子有足够 K 线可用。
    """

    if trade_date is None:
        trade_date = get_today(_format='%Y%m%d')

    logger.info(f"计算因子数据：{stock_code}")

    # 取数窗口至少要覆盖 52 周因子的 252 个交易日
    lookback_days = max(abs(int(time_period)), FACTOR_LOOKBACK_DAYS)

    # 2、计算所有因子
    factors = FactorCalService.calculate_all_factors(
        stock_code,
        get_date_by_n(-lookback_days, _format='%Y%m%d'),
        trade_date,
        asset_type=asset_type,
    )

    if len(factors) == 0:
        logger.warning(f"{stock_code} 未计算出任何因子（行情为空或不足），跳过入库")
        return

    # 3、因子数据入库（长表）
    if save_last:
        FactorCalService.save_factor_records_to_db(stock_code, [factors[-1]])
    else:
        # 清空旧因子数据
        FactorValueService.delete_by_ticker(stock_code=stock_code)
        FactorCalService.save_factor_records_to_db(stock_code, factors)


if __name__ == '__main__':

    job_update_financial_score_all()
