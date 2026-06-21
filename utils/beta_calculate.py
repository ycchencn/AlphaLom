"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import numpy as np
import pandas as pd
from service import StockService
from utils.data_loader import databull
from utils.common import logger

# Beta 计算函数
def calculate_beta(stock_code, index_code='000001', start_date="20200101", end_date="20240405"):
    """
    计算ETF相对于指数的Beta值：Beta = Cov(ETF, Index) / Var(Index)
    若数据不足、为空、方差为0等异常情况，统一返回 0.0。
    """
    try:

        stock = StockService.get_stock_by_symbol(symbol=stock_code)
        assert stock is not None

        # 获取指数价格
        # index_df = IndexDailyDataService.get_history(index_code, start_date, end_date)
        index_df = databull.get_index_history(index_code, start_date, end_date)
        if index_df is None or index_df.empty:
            logger.warning(f"Index {index_code} has no data between {start_date} and {end_date}")
            return 0.0
        index_close = index_df['close']

        # 获取ETF价格
        stock_df = databull.get_history(stock_code, start_date, end_date, 'd', stock.get('market'))
        stock_close = stock_df.loc[start_date:end_date]["close"]

        if stock_close is None or stock_close.empty:
            logger.warning(f"ETF {stock_code} has no price data between {start_date} and {end_date}")
            return 0.0

        # 对齐收益率（内部已处理索引统一）
        aligned = _align_returns(stock_close, index_close)

        if len(aligned) < 2:
            logger.warning(
                f"Insufficient overlapping data to compute beta for {stock_code} vs {index_code}. "
                f"Aligned return samples: {len(aligned)}"
            )
            return 0.0

        X = aligned['Index_Returns'].values  # 基准指数收益率
        Y = aligned['ETF_Returns'].values    # ETF收益率

        # 检查是否全为常数（方差为0）
        if np.var(X) == 0:
            logger.warning(f"Variance of index returns is zero for {index_code}. Cannot compute beta.")
            return 0.0

        # 计算 Beta（使用样本协方差和方差，ddof=1 更合理）
        cov = np.cov(X, Y, ddof=1)[0, 1]
        var = np.var(X, ddof=1)
        if var == 0:
            return 0.0

        beta = cov / var

        return round(float(beta), 5)

    except Exception as e:
        logger.error(f"Unexpected error calculating beta for {stock_code} vs {index_code}: {e}", exc_info=True)
        return 0.0


# 对齐两个资产的日收益率
def _align_returns(etf_close: pd.Series, index_close: pd.Series):
    """
    计算ETF和指数的日对数收益率，并对齐到有交集的日期序列表
    """

    # 保证输入是Series
    if not isinstance(etf_close, pd.Series) or not isinstance(index_close, pd.Series):
        raise TypeError("ETF 和 指数的 close 列必须为 pandas.Series 类型！")

    # 计算日对数收益率
    etf_returns = np.log(etf_close / etf_close.shift(1)).dropna()
    index_returns = np.log(index_close / index_close.shift(1)).dropna()

    # 对齐数据，保留共同日期
    aligned_returns = pd.DataFrame({
        'ETF_Returns': etf_returns,
        'Index_Returns': index_returns
    }).dropna()

    return aligned_returns


# 😄 主程序运行
if __name__ == "__main__":

    pass
