"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import FactorValue
from models.database import db_session as session
from sqlalchemy import case, and_, func, Float
from utils.common import ETF_PREFIXES
from utils.logger import logger
from datetime import date
from typing import Optional, Dict, Any
from service.factor_desc import ALL_FACTOR_FIELDS, technical_fields

# 选股时回溯「最近多少个有数据的交易日」。
# 日更按监控池分批落库，单日可能只覆盖极少标的（实测 2026-09-28 仅 7 只），
# 取 1 天会漏掉绝大多数标的；取 5 天可把覆盖从 7 只提到 ~171 只，且查询仍是
# 主键等值扫描（0.04s 级）。数值越大覆盖越全、但会引入更旧的值。
LOOKBACK_DATES = 5


def exclude_etf_condition():
    """构造「排除 ETF」的 SQL 条件（作用于 FactorValue.ticker 列）。

    ⚠️ 为什么用号段前缀而不是 `stocks.securities_type`：
    因子落库走 `factor_cal_service`，ETF 与个股共用 `factor_values` 这张 EAV 表，
    而 ETF 在 `stocks` 表里**根本没有对应行**（实测 159915 / 159258 / 512980
    三个 ETF 都有因子数据但都不在 stocks 表中）。所以 join `stocks` 过滤反而会
    因内连接把这些 ETF 连带漏掉、同时把「有因子但没登记 stocks 的个股」一起误杀。
    号段前缀是全项目唯一的 ETF 判据（`utils/common.py:is_etf` 同源），这里与其保持
    一致，不要另立一套。

    ⚠️ 必须下推到 SQL 而不是查询后过滤：`select_stocks_by_factors_asof` 先 `.limit()`
    再返回，若在路由层拿到结果后剔除 ETF，用户要 50 条只会回来 47 条 —— 等于把
    「剔除 ETF」变成了「限量缩水」。

    注意 `is_etf` 要求 6 位纯数字，前缀长度不一会漏判（如 `1` 开头不匹配 `15`），
    所以这里保持 `startswith` 的语义，改用 `NOT LIKE '前缀%'`（等价且走不了索引，
    但这只作用在已经按 trade_date IN 收敛后的小结果集上，实测无额外开销）。
    """
    return and_(*[
        ~FactorValue.ticker.like(f'{p}%')
        for p in ETF_PREFIXES
    ])


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

        ⚠️ 性能要点（2026-09-29 重写，实测 57s → 1.3s）：

        `factor_values` 是 2100 万行的 EAV 长表，主键是
        (trade_date, ticker, factor_name) —— 注意 **trade_date 是第一列**。
        原来的实现用 `ROW_NUMBER() OVER (PARTITION BY ticker, factor_name ORDER BY
        trade_date DESC)` 配合 `trade_date <= asof_date` 取「每个标的最新值」，
        两个问题叠在一起：

          1. `PARTITION BY (ticker, factor_name)` 与主键前缀
             `(trade_date, ...)` 不匹配，MySQL 只能全表扫 1165 万行再排序；
          2. `trade_date <= asof` 是范围条件，即使走索引也要扫大量历史分区。

        改成「先把 asof 之前的最新交易日**求出来**，再用等值条件命中主键」：
        日更任务按「监控池批次」分批计算并落库，所以**同一天里可能只有一小部分标的
        有数据**（实测 2026-09-28 只有 7 只标的写全了技术因子，而 09-21 有 108 只）。
        因此「取全表最大 trade_date」会挑到一个几乎空的日子，选股结果自然接近 0 命中。

        正确做法：取每个因子在 asof 之前的 **最近 K 个有数据的交易日**，
        再对这些日期做 `trade_date IN (...)` 等值扫描（命中主键首列，0.04s 级）。
        一个标的只要在上述任一天有该因子的值就参与筛选，等价于「用最近一次落库的值」，
        既容忍分批落库，又把扫描量限制在几十万行内。
        """
        factor_names = list(conditions.keys())
        if not factor_names:
            return {"selected_tickers": [], "details": {}}

        # 第一步：为每个因子取出它在 asof_date 之前「最近 K 个有数据的交易日」。
        # 不用全表 MAX —— 见 docstring，MAX 会落到只有极少标的的分批落库日。
        latest_dates = set()
        for fname in factor_names:
            rows = (
                session.query(FactorValue.trade_date)
                .filter(FactorValue.factor_name == fname,
                        FactorValue.trade_date <= asof_date)
                .group_by(FactorValue.trade_date)
                .order_by(FactorValue.trade_date.desc())
                .limit(LOOKBACK_DATES)
                .all()
            )
            latest_dates.update(r[0] for r in rows if r[0] is not None)

        if not latest_dates:
            return {"selected_tickers": [], "details": {}}

        # 第二步：只扫这些最近交易日，按 ticker 分组做条件聚合。
        # `trade_date IN (...)` 命中主键首列 → 扫描量从 1165 万行降到几十万行。
        # ⚠️ ETF 排除放在这一层（而不是查询后过滤）——主查询下面才 `.limit()`，
        # 事后剔除会让「要 50 条」只回来 47 条。选股器是选个股的入口，
        # ETF 有自己独立的页面（ETF 洞察 / 轮动），不该混进这里。
        valid_latest = (
            session.query(
                FactorValue.ticker.label('ticker'),
                FactorValue.factor_name.label('factor_name'),
                FactorValue.value.cast(Float).label('value'),
            )
            .filter(
                FactorValue.trade_date.in_(sorted(latest_dates)),
                FactorValue.factor_name.in_(factor_names),
                FactorValue.value.isnot(None),
                exclude_etf_condition(),
            )
            .subquery()
        )

        # 第三步：按 ticker 分组，用条件聚合提取每个因子的值，并应用 HAVING 过滤
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
