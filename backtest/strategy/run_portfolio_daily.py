"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from datetime import date
from backtest.strategy.strategy_runner import DailyStrategySimulator
from models.database import db_session
from models import PortfolioDailySummary
from service import (
    InvestmentPortfolioService,
    PortfolioAssetsService,
    FactorValueService,
    PortfolioTransactionService,
    PortfolioDailySummaryService
)
from utils.common import logger, get_today, is_etf
from utils.data_loader import databull
from backtest.quant_stat_report import generate_html_report_string


class StrategyRunner:

    def __init__(self, portfolio, trading_date_str: str = None, overwrite: bool = False):

        self.portfolio_id = portfolio.get('portfolio_id')
        self.overwrite = overwrite
        self.trading_date_str = trading_date_str or date.today().strftime('%Y%m%d')
        self.today = date.today()

        # Load portfolio info and holdings
        self.investment_info = portfolio
        assert self.investment_info is not None

        self.holding_assets = PortfolioAssetsService.get_all_by_portfolio_id(self.portfolio_id)

        # 获取调仓计划表
        self.position_plan = self.investment_info.get('position_plan')

        # 获取可用现金
        self.current_cash = self.investment_info.get('current_cash')

    def _get_previous_total_value(self) -> float:
        """从 PortfolioDailySummary 表中获取最近一个早于当前交易日的总资产"""

        try:
            # 将当前交易日转为字符串格式 'YYYYMMDD' → 用于比较
            current_date_str = self.trading_date_str  # e.g., '20260121'

            # 查询：同 portfolio_id，且 date < 当前日期，按 date 降序取第一条
            prev_summary = db_session.query(PortfolioDailySummary) \
                .filter(
                PortfolioDailySummary.portfolio_id == self.portfolio_id,
                PortfolioDailySummary.date < current_date_str
            ) \
                .order_by(PortfolioDailySummary.date.desc()) \
                .first()

            if prev_summary:
                logger.debug(f"🔍 找到上一交易日 {prev_summary.date} 的总资产: {prev_summary.total_assets}")
                return float(prev_summary.total_assets)
            else:
                # 没有历史记录：视为初始日
                logger.info("🆕 无历史盈亏记录，按初始持仓+现金计算昨日资产（实际为今日初始值）")
                initial_value = self.current_cash + sum(
                    asset['position_size'] * asset['position_price']
                    for asset in self.holding_assets
                )
                return float(initial_value)

        except Exception as e:
            logger.error(f"❌ 查询上一日总资产失败: {e}")
            # 容错：回退到初始估值
            return self.current_cash + sum(
                asset['position_size'] * asset['position_price']
                for asset in self.holding_assets
            )

    def run(self):

        logger.info(
            f"🚀 启动 {self.today} 策略模拟运行..., 策略编号：{self.portfolio_id}，策略名称：{self.investment_info.get('name')}")

        # 1. 加载行情数据
        market_data = self._load_market_data()

        # 2. 初始化模拟器
        simulator = DailyStrategySimulator(
            initial_cash=self.current_cash,
            portfolio_id=self.portfolio_id
        )
        simulator.load_holdings(self.holding_assets)

        # 3. 执行调仓
        simulator.execute_trades(self.position_plan, market_data)
        self.current_cash = simulator.cash

        # 获取昨日总资产（用于计算日度盈亏变化）
        yesterday_total_value = self._get_previous_total_value()

        # 4. 计算盈亏
        pnl_result = simulator.calculate_daily_pnl(market_data)

        # 计算今日盈亏（含持仓市值）
        today_total_value = pnl_result['total_value']

        # 计算每日盈亏变化
        daily_pnl_change = today_total_value - yesterday_total_value

        logger.info(f"📊 今日盈亏变化: {daily_pnl_change:+,.2f} 元")

        # 5. 保存统计结果
        result = simulator.save_daily_pnl_to_db(self.trading_date_str, pnl_result['total_value'],
                                                daily_pnl_change=daily_pnl_change, overwrite=self.overwrite)

        # 6. 保存交易记录
        for transaction_data in simulator.trade_log:
            # transaction_data = {
            #     'date': '2026-01-22',
            #     'action': 'BUY',
            #     'code': '603019',
            #     'name': '中科曙光',
            #     'qty': 600,
            #     'price': 91.28,
            #     'amount': 54768.0,
            #     'realized_pnl': 0.0,
            #     'portfolio_id': 8
            # }
            PortfolioTransactionService.add(transaction_data)

        # 6. 刷新持仓信息（仅当未覆盖时）
        if result and not self.overwrite:
            # 刷新持仓信息到assets
            # 置空调仓计划
            self._update_position_info(pnl_result)
            InvestmentPortfolioService.update_by_portfolio_id(self.portfolio_id, {
                'current_cash': self.current_cash,
                'position_plan': {},  # 置空调仓计划
            })

            # 清空0持仓的数据
            PortfolioAssetsService.delete_zero_by_portfolio_id(self.portfolio_id)

        logger.info("✅ 今日策略模拟完成！")

    def _load_market_data(self):
        """构建股票池并加载行情"""
        holding_codes = [h['stock_code'] for h in self.holding_assets]
        plan_codes = []
        if self.position_plan and isinstance(self.position_plan, dict) and 'actions' in self.position_plan:
            plan_codes = [
                act['stock_code'] for act in self.position_plan['actions']
                if 'stock_code' in act
            ]
        all_codes = list(set(holding_codes + plan_codes))
        return self._fetch_market_data(all_codes, self.trading_date_str)

    @staticmethod
    def _fetch_market_data(stock_codes, trading_date):
        """从行情服务加载指定日期的股票收盘价等数据"""
        market_data = {}

        for code in stock_codes:
            try:

                # 从数据库获取行情数据
                if is_etf(code):
                    last_tick = databull.get_last_tick(code, 'etf', 'cn')
                else:
                    last_tick = databull.get_last_tick(code, 'stock', 'cn')

                if last_tick is None or 'open' not in last_tick:
                    logger.warning(f"⚠️ 行情缺失: {code} 在 {trading_date} 无数据")
                    market_data[code] = {'close': 0}
                    continue

                market_data[code] = {
                    'close': last_tick['lastPrice'],
                    'prev_close': last_tick['lastClose'],
                    'open': last_tick['open'],
                    'high': last_tick['high'],
                    'low': last_tick['low'],
                }

                logger.info(f"✅ 加载行情: {code} | {trading_date} | 收盘: {last_tick['lastPrice']:.2f}")

            except Exception as e:
                logger.error(f"❌ 加载 {code} 行情失败: {e}")
                market_data[code] = {'close': 0.0}

        return market_data

    def _get_reason_from_plan(self, stock_code):
        """获取调仓原因"""
        if not self.position_plan or 'actions' not in self.position_plan:
            return ''
        for action in self.position_plan['actions']:
            if stock_code == action.get('stock_code'):
                return action.get('reason', '')
        return ''

    def _update_position_info(self, pnl_result):
        """刷新持仓信息到数据库"""
        for position in pnl_result['records']:

            asset = PortfolioAssetsService.get_by_symbol(position['code'], self.portfolio_id)

            update_data = {
                'position_price': position['current_price'],
                'cost_price': position['cost_price'],
                'position_size': position['size'],
                'last_update': get_today(_format='%Y-%m-%d %H:%M:%S'),
                'remark': self._get_reason_from_plan(position['code'])
            }

            if asset is None:
                update_data.update({
                    'portfolio_id': self.portfolio_id,
                    'asset_name': position['name'],
                    'stock_code': position['code'],
                    'remark': self._get_reason_from_plan(position['code'])
                })
                PortfolioAssetsService.add(update_data)
            else:
                update_data['remark'] = ''  # 或保留原 remark？按需调整
                PortfolioAssetsService.update_by_stock_code(
                    self.portfolio_id, position['code'], update_data
                )


def run_daily_strategy_all(overwrite=False):
    # 判断交易日
    if FactorValueService.is_trading_day() is False:
        return

    portfolios = InvestmentPortfolioService.get_all()

    # 获取交易日
    trading_day = FactorValueService.get_latest_trading_date().strftime('%Y%m%d')

    for portfolio in portfolios:
        # 剔除禁用的
        if portfolio.get('enable') == 0:
            continue
        run_daily_strategy(portfolio=portfolio, trading_day=trading_day, overwrite=overwrite)


def run_daily_strategy(portfolio, trading_day, overwrite):
    """
    运行每日策略
    """

    runner = StrategyRunner(
        portfolio=portfolio,
        trading_date_str=trading_day,
        overwrite=overwrite
    )

    runner.run()


def generate_quantstat_report():
    portfolios = InvestmentPortfolioService.get_all()

    for portfolio in portfolios:

        # 剔除禁用的
        if portfolio.get('enable') == 0:
            continue

        summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio['portfolio_id'])

        # 2. 转换为 DataFrame，只取日期和总资产
        df = pd.DataFrame(summary_list)
        df['date'] = pd.to_datetime(df['date'])  # 确保是 datetime 格式
        df = df.set_index('date').sort_index()  # 设为索引并按时间排序
        equity = df['total_assets']  # 净资产序列

        # 你的归一化净值序列 equity
        html_content = generate_html_report_string(equity, title="量化策略绩效报告")

        InvestmentPortfolioService.update_by_portfolio_id(portfolio['portfolio_id'], {
            'quantstat': html_content
        })


if __name__ == "__main__":

    # generate_quantstat_report()

    run_daily_strategy_all()

    # portfolio_id = 15
    # portfolio = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    # trading_day = FactorValueService.get_latest_trading_date().strftime('%Y%m%d')
    # run_daily_strategy(
    #     portfolio=portfolio,
    #     trading_day=trading_day,
    #     overwrite=False
    # )
