"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from service import StockService
from service.stock_fear_greed_service import StockFearGreedService
from job.market_fear_greed import build_fear_greed_index
from utils.common import get_today, is_etf
from datetime import datetime
from utils.data_loader import databull
from utils.logger import logger

def job_update_stock_greedy_data_daily(override_all=False):
    stocks = StockService.get_monitoring_stock_pool(per_page=500)
    for stock in stocks:
        job_update_stock_greedy_data(index_code=stock['symbol'], override_all=override_all)

def job_update_stock_greedy_data(index_code, override_all=False):

    try:
        if is_etf(index_code):
            market_data = databull.get_etf_history(symbol=index_code, start_date="20250101", end_date=get_today())
        else:
            market_data = databull.get_stock_history(symbol=index_code, start_date="20250101", end_date=get_today())
        # 构建指数
        result = build_fear_greed_index(market_data)
    except Exception as e:
        logger.info(f"{index_code}, 个股行情数据获取失败: {e}")
        return None

    if market_data is None:
        logger.warning(f"{index_code}, 个股行情数据为空，跳过处理")
        return None

    # === 新增：准备批量写入数据 ===
    records_to_insert = []

    if override_all:

        # 清空旧数据
        StockFearGreedService.delete_by_index(index_code=index_code)

        for trade_date, row in result.iterrows():
            # 跳过任何关键字段为 NaN 的行
            if (
                pd.isna(row["fear_greed"]) or
                pd.isna(row["vol_score"]) or
                pd.isna(row["mom_score"]) or
                pd.isna(row["close"])
            ):
                continue  # 跳过无效行
            # 确保 trade_date 是 date 类型（不是 Timestamp）
            if hasattr(trade_date, 'date'):
                trade_date = trade_date.date()
            elif isinstance(trade_date, str):
                trade_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
            records_to_insert.append({
                "trade_date": trade_date,
                "index_code": index_code,  # 或从原始数据中获取 symbol
                "close": float(row["close"]),
                "fear_greed": float(row["fear_greed"]),
                "vol_score": float(row["vol_score"]),
                "mom_score": float(row["mom_score"])
            })
    else:
        row = result.iloc[-1]
        records_to_insert.append({
            "trade_date": result.index[-1],
            "index_code": index_code,  # 或从原始数据中获取 symbol
            "close": float(row["close"]),
            "fear_greed": float(row["fear_greed"]),
            "vol_score": float(row["vol_score"]),
            "mom_score": float(row["mom_score"])
        })

    # === 执行批量插入 ===
    success = StockFearGreedService.batch_create(records_to_insert)
    if success:
        logger.debug("✅ 贪婪与恐惧数据已成功写入数据库！")
    else:
        logger.debug("❌ 贪婪与恐惧数据写入失败，请检查日志。")

    return None

if __name__ == '__main__':

    # job_update_stock_greedy_data_daily(override_all=True)

    # 是否覆盖旧数据
    override_all = True
    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)

    # 循环对个股进行每日挖掘
    for stock in stocks:
        stock_code = stock.get('symbol')
        job_update_stock_greedy_data(index_code=stock.get('symbol'), override_all=override_all)
