"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import FactorValue
from models.database import db_session as session
from sqlalchemy import case, and_, func, Float
from utils.logger import logger
from datetime import date
from typing import Optional, Dict, Any
from service.factor_desc import ALL_FACTOR_FIELDS, technical_fields


class FactorSelectorService:

    @staticmethod
    def get_tech_factors_for_stock(ticker: str, asof_date) -> Dict[str, Optional[float]]:
        """
        获取指定股票在指定日期的最新全部因子数据。

        Args:
            ticker (str): 股票代码，如 '600519.SH'
            asof_date (date): 截止日期

        Returns:
            dict: {factor_name: value, ...}。如果股票或因子不存在，value为None。
        """

        # 2. 第二步：复用原有的“最新值”逻辑，但针对特定股票和所有因子
        # 使用窗口函数获取每个因子的最新值（截至 asof_date）
        try:
            latest_factor_values = (
                session.query(
                    FactorValue.factor_name,
                    FactorValue.value,
                    func.row_number().over(
                        partition_by=FactorValue.factor_name,  # 注意：这里只按因子名分区，因为我们只查一只股票
                        order_by=FactorValue.trade_date.desc()
                    ).label('rn')
                )
                .filter(
                    FactorValue.factor_name.in_(technical_fields),
                    FactorValue.ticker == ticker,  # 限定股票代码
                    FactorValue.trade_date <= asof_date,
                    FactorValue.value.isnot(None)
                )
                .subquery()
            )

            # 3. 第三步：提取 rn=1 的记录，并转换为字典
            result_query = (
                session.query(
                    latest_factor_values.c.factor_name,
                    latest_factor_values.c.value.cast(Float)
                )
                .filter(latest_factor_values.c.rn == 1)
            )

            results = result_query.all()

            # 4. 第四步：格式化结果
            # 结果格式: {factor_name: value}
            factor_dict = {row[0]: float(row[1]) if row[1] is not None else None for row in results}

            return factor_dict

        except Exception as e:
            logger.error(f"Error fetching all factors for {ticker} as of {asof_date}: {e}")
            return {}

    @staticmethod
    def get_all_factors_for_stock_asof(ticker: str, asof_date: date) -> Dict[str, Optional[float]]:
        """
        获取指定股票在指定日期的最新全部因子数据。

        Args:
            ticker (str): 股票代码，如 '600519.SH'
            asof_date (date): 截止日期

        Returns:
            dict: {factor_name: value, ...}。如果股票或因子不存在，value为None。
        """

        # 2. 第二步：复用原有的“最新值”逻辑，但针对特定股票和所有因子
        # 使用窗口函数获取每个因子的最新值（截至 asof_date）
        try:
            latest_factor_values = (
                session.query(
                    FactorValue.factor_name,
                    FactorValue.value,
                    func.row_number().over(
                        partition_by=FactorValue.factor_name,  # 注意：这里只按因子名分区，因为我们只查一只股票
                        order_by=FactorValue.trade_date.desc()
                    ).label('rn')
                )
                .filter(
                    FactorValue.factor_name.in_(ALL_FACTOR_FIELDS),
                    FactorValue.ticker == ticker,  # 限定股票代码
                    FactorValue.trade_date <= asof_date,
                    FactorValue.value.isnot(None)
                )
                .subquery()
            )

            # 3. 第三步：提取 rn=1 的记录，并转换为字典
            result_query = (
                session.query(
                    latest_factor_values.c.factor_name,
                    latest_factor_values.c.value.cast(Float)
                )
                .filter(latest_factor_values.c.rn == 1)
            )

            results = result_query.all()

            # 4. 第四步：格式化结果
            # 结果格式: {factor_name: value}
            factor_dict = {row[0]: float(row[1]) if row[1] is not None else None for row in results}

            return factor_dict

        except Exception as e:
            logger.error(f"Error fetching all factors for {ticker} as of {asof_date}: {e}")
            return {}

    @staticmethod
    def select_stocks_by_factors_asof(
            asof_date: date,
            conditions: Dict[str, Dict[str, Any]],
            limit: Optional[int] = None
    ):
        """
        高效地根据多个因子条件筛选股票（截至 asof_date 的最新值）。

        Args:
            asof_date: 截止日期
            conditions: 因子条件字典，如 {'roe': {'operator': '>=', 'value': 15}, ...}
            limit: 最多返回多少只股票（可选）

        Returns:
            dict: {"selected_tickers": [...], "details": {...}}
        """
        factor_names = list(conditions.keys())
        if not factor_names:
            return {"selected_tickers": [], "details": {}}

        # 第一步：为每个 ticker 获取每个因子的最新值（截至 asof_date）
        # 使用窗口函数 + 条件聚合
        latest_factor_values = (
            session.query(
                FactorValue.ticker,
                FactorValue.factor_name,
                FactorValue.value,
                func.row_number().over(
                    partition_by=[FactorValue.ticker, FactorValue.factor_name],
                    order_by=FactorValue.trade_date.desc()
                ).label('rn')
            )
            .filter(
                FactorValue.factor_name.in_(factor_names),
                FactorValue.trade_date <= asof_date,
                FactorValue.value.isnot(None)
            )
            .subquery()
        )

        # 第二步：只取 rn = 1 的记录（即每个 ticker 每个因子的最新值）
        valid_latest = session.query(
            latest_factor_values.c.ticker,
            latest_factor_values.c.factor_name,
            latest_factor_values.c.value.cast(Float).label('value')
        ).filter(latest_factor_values.c.rn == 1).subquery()

        # 第三步：按 ticker 分组，用条件聚合提取每个因子的值，并应用 WHERE/HAVING 过滤
        group_cols = [valid_latest.c.ticker]
        select_cols = [valid_latest.c.ticker]

        # 构建每个因子的条件表达式（用于 HAVING）
        having_conditions = []

        for fname, cond in conditions.items():
            op = cond['operator']
            threshold = float(cond['value'])

            # 条件聚合：提取该因子的值
            factor_expr = func.max(
                case((valid_latest.c.factor_name == fname, valid_latest.c.value), else_=None)
            ).label(f"factor_{fname}")

            select_cols.append(factor_expr)

            # 构建 HAVING 条件
            if op == '>=':
                having_cond = factor_expr >= threshold
            elif op == '<=':
                having_cond = factor_expr <= threshold
            elif op == '>':
                having_cond = factor_expr > threshold
            elif op == '<':
                having_cond = factor_expr < threshold
            elif op == '==':
                having_cond = func.abs(factor_expr - threshold) < 1e-8
            else:
                raise ValueError(f"Unsupported operator: {op}")

            having_conditions.append(having_cond)

        # 构建主查询
        query = session.query(*select_cols) \
            .group_by(valid_latest.c.ticker) \
            .having(and_(*having_conditions))

        # 应用 limit
        if limit is not None:
            query = query.limit(limit)

        # 执行查询
        results = query.all()

        if not results:
            return {"selected_tickers": [], "details": {}}

        # 整理结果
        selected_tickers = []
        details = {}

        for row in results:
            ticker = row[0]
            selected_tickers.append(ticker)
            ticker_detail = {}
            for i, fname in enumerate(factor_names, start=1):
                val = getattr(row, f"factor_{fname}", None)
                ticker_detail[fname] = float(val) if val is not None else None
            details[ticker] = ticker_detail

        return {
            "selected_tickers": selected_tickers,
            "details": details
        }


# 使用示例
if __name__ == "__main__":

    asof_date = date(2026, 5, 1)

    # print(FactorValueService.get_latest_trading_date())

    conditions = {
        # 盈利能力（Quality）
        'roe': {'operator': '>=', 'value': 15},  # 净资产收益率 ≥ 15%
        'gross_margin': {'operator': '>=', 'value': 30},  # 毛利率 ≥ 30%

        # 成长性（Growth）
        'revenue_growth_yoy': {'operator': '>=', 'value': 10},  # 营业总收入同比增长 ≥ 10%
        'net_profit_parent_growth_yoy': {'operator': '>=', 'value': 15},  # 归母净利润同比增长 ≥ 15%

        # 财务稳健性（Safety）
        'debt_to_asset_ratio': {'operator': '<=', 'value': 60},  # 资产负债率 ≤ 60%
        'current_ratio': {'operator': '>=', 'value': 1.2},  # 流动比率 ≥ 1.2
        'ocf_to_net_profit_parent': {'operator': '>=', 'value': 0.8},  # 经营现金流/归母净利润 ≥ 0.8（盈利质量高）

        # 规模与持续性（可选）
        'operating_revenue': {'operator': '>=', 'value': 1e9},  # 营业总收入 ≥ 10亿元（排除微小公司）
    }

    result = FactorSelectorService.select_stocks_by_factors_asof(asof_date, conditions, limit=5)

    for stock in result['selected_tickers']:
        print(stock)
        print(result['details'][stock])
        print()
