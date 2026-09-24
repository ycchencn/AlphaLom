"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import date
from typing import List, Dict, Any
from utils.logger import logger
from models import PortfolioDailySummary, DailyPnLRecord
from models.database import db_session
from utils.data_loader import databull


class DailyStrategySimulator:

    def __init__(self, initial_cash: float = 1000000.0, portfolio_id=None, strategy_setting=None):

        self.cash = initial_cash
        self.holdings = {}  # {code: {'size': int, 'cost': float}}
        self.trade_log = []
        self.daily_records = []
        self.db_session = db_session
        self.portfolio_id = portfolio_id
        self.cumulative_realized_pnl = 0
        self.strategy_setting = strategy_setting

    def load_cumulative_realized_pnl(self):
        """从数据库加载最新的累计已实现盈亏"""
        if not self.portfolio_id:
            return
        latest = self.db_session.query(PortfolioDailySummary) \
            .filter(PortfolioDailySummary.portfolio_id == self.portfolio_id) \
            .order_by(PortfolioDailySummary.date.desc()) \
            .first()
        if latest:
            self.cumulative_realized_pnl = latest.cumulative_realized_pnl or 0.0
            logger.info(f"加载累计已实现盈亏: {self.cumulative_realized_pnl:.2f}")
        else:
            self.cumulative_realized_pnl = 0.0

    def load_holdings(self, holding_assets: List[Dict[str, Any]]):
        """加载当前持仓（来自数据库）"""
        self.holdings = {}
        for asset in holding_assets:
            code = asset['stock_code']
            size = asset['position_size']
            cost = asset['cost_price']
            if size > 0:
                self.holdings[code] = {'size': size, 'cost': cost, 'market_price': asset['position_price']}
                logger.info(f"持仓加载: {code} {asset['name']} - {size} 股 @ {cost:.2f}")

    def execute_trades(self, position_plan: Dict | None, market_data: Dict[str, Dict]):
        """执行调仓计划（模拟交易）"""
        if not position_plan or position_plan.get('date') is None:
            logger.info("无调仓计划，跳过交易")
            return

        plan_date = position_plan['date']
        logger.info(f"执行调仓计划（生成于 {plan_date}）")

        for action in position_plan['actions']:

            code = action.get('stock_code')
            qty = action.get('quantity')
            act_type = action.get('action')
            name = action.get('stock_name', '未知')

            # 校验 stock_code：必须存在且为字符串，且非空
            if not code or not isinstance(code, str) or not code.strip():
                continue
            code = code.strip()

            # 校验 quantity：必须是整数或可转为整数的数值，且大于 0
            if qty is None:
                continue
            try:
                qty = int(qty)
                if qty <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            if code not in market_data or market_data[code]['close'] <= 0:
                logger.warning(f"⚠️ 行情缺失，跳过 {code} ({name})")
                continue

            # 使用开盘价买入
            price = market_data[code]['open']

            if act_type == 'buy' and qty > 0:
                cost = qty * price
                if self.cash >= cost:
                    self.cash -= cost

                    if code in self.holdings:
                        # 加权平均成本法（Weighted Average Cost） 计算持仓成本
                        old_size = self.holdings[code]['size']
                        old_cost_per_share = self.holdings[code]['cost']
                        old_total_cost = old_size * old_cost_per_share
                        new_total_cost = old_total_cost + cost
                        new_size = old_size + qty
                        new_avg_cost = new_total_cost / new_size
                        self.holdings[code]['size'] = new_size
                        self.holdings[code]['cost'] = round(new_avg_cost, 4)  # 保留4位小数防浮点误差
                    else:
                        self.holdings[code] = {'size': qty, 'cost': price}

                    self.trade_log.append({
                        'date': date.today(),
                        'action': 'BUY',
                        'code': code,
                        'name': name,
                        'qty': qty,
                        'price': price,
                        'amount': cost,
                        'realized_pnl': 0,
                        'portfolio_id': self.portfolio_id
                    })
                    logger.info(f"🟢 BUY {qty:6d} @ {code} ({name}) @{price:.2f}")
                else:
                    logger.error(f"❌ 现金不足，无法买入 {code}")

            elif act_type == 'sell' and qty > 0:

                # 使用收盘价卖出
                price = market_data[code]['close']

                if code in self.holdings and self.holdings[code]['size'] >= qty:

                    holding = self.holdings[code]
                    original_cost = holding['cost']
                    proceeds = qty * price
                    realized_pnl = qty * (price - original_cost)  # 👈 新增

                    holding['size'] -= qty
                    self.cash += proceeds

                    self.trade_log.append({
                        'date': date.today(),
                        'action': 'SELL',
                        'code': code,
                        'name': name,
                        'qty': qty,
                        'price': price,
                        'amount': proceeds,
                        'realized_pnl': realized_pnl,  # 👈 记录,
                        'portfolio_id': self.portfolio_id
                    })

                    # 清仓动作
                    if holding['size'] == 0:
                        logger.info(f"🔴 SELL {qty:6d} @ {code} ({name}) @{price:.2f} | 执行了清仓动作: {realized_pnl:+.2f}")
                    else:
                        logger.info(f"🔴 SELL {qty:6d} @ {code} ({name}) @{price:.2f} | 实现盈亏: {realized_pnl:+.2f}")


                else:
                    logger.warning(f"🟡 无足够持仓，跳过卖出 {code}")

            elif act_type == 'hold':
                pass  # 无需操作

    def calculate_daily_pnl(self, market_data: Dict[str, Dict]):
        """计算当日持仓浮动盈亏并记录"""
        total_value = self.cash
        total_cost = 0.0
        total_unrealized_pnl = 0.0
        records = []

        logger.info("【最新浮动盈亏明细】")
        logger.info(
            f"{'代码':<10} {'名称':<12} {'持仓':<8} {'成本价':<8} {'现价':<8} {'市值':<12} {'浮盈':<10} {'盈亏%'}")
        logger.info("-" * 80)

        for code, holding in self.holdings.items():
            size = holding['size']
            cost_price = holding['cost']
            if code not in market_data or market_data[code]['close'] <= 0:
                # 如果获取不到行情，暂时使用旧数据
                current_price = holding['market_price']
            else:
                current_price = market_data[code]['close']

            market_value = size * current_price
            cost_value = size * cost_price
            unrealized_pnl = market_value - cost_value
            pnl_pct = (unrealized_pnl / cost_value * 100) if cost_value != 0 else 0.0

            # 累计
            total_value += market_value
            total_cost += cost_value
            total_unrealized_pnl += unrealized_pnl

            name = self._get_stock_name(code)  # 可选：从外部传入名称映射

            # 记录
            records.append({
                'date': date.today(),
                'code': code,
                'name': name,
                'size': size,
                'cost_price': round(cost_price, 2),
                'current_price': round(current_price, 2),
                'market_value': round(market_value, 2),
                'unrealized_pnl': round(unrealized_pnl, 2),
                'pnl_pct': round(pnl_pct, 2)
            })

            # 打印明细（对齐美观）
            logger.info(
                f"{code:<10} {name:<12} {size:<8} {cost_price:<8.2f} "
                f"{current_price:<8.2f} {market_value:<12,.2f} "
                f"{unrealized_pnl:+10.2f} {pnl_pct:+7.2f}%"
            )

        # 总浮动盈亏
        total_pnl_pct = (total_unrealized_pnl / total_cost * 100) if total_cost != 0 else 0.0

        logger.info("-" * 80)
        logger.info(f"📈 组合总浮动盈亏: {total_unrealized_pnl:+,.2f} 元 ({total_pnl_pct:+.2f}%)")
        logger.info(f"💰 总资产: {total_value:,.2f} | 现金: {self.cash:,.2f} | 持仓市值: {total_value - self.cash:,.2f}")
        logger.info(f"📊 仓位比例: {(total_value - self.cash) / total_value * 100:.1f}%")

        self.daily_records.extend(records)

        return {
            'total_value': total_value,
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_pnl_pct': total_pnl_pct,
            'records': records
        }

    def _get_stock_name(self, code: str) -> str:
        """简易股票名称映射（实际可从 holdings 或外部字典获取）"""
        stock_api = databull.get_stock_info(code, market='cn')
        name = stock_api.get('name') if isinstance(stock_api, dict) else ''
        return name

    def save_daily_pnl_to_db(self, trading_date: str, total_value: float, daily_pnl_change:float, overwrite: bool = False):
        """
        保存当日浮动盈亏到 MySQL（支持覆盖）

        :param trading_date: 交易日期
        :param total_value: 组合总资产
        :param daily_pnl_change: 组合持仓变动
        :param overwrite: 是否先删除当天已存在的记录（默认 False）
        """
        if self.db_session is None:
            logger.error("❌ 数据库会话未注入，跳过保存")
            return

        try:
            if overwrite:
                # 删除当天该组合的个股记录
                self.db_session.query(DailyPnLRecord).filter(
                    DailyPnLRecord.date == trading_date,
                    DailyPnLRecord.portfolio_id == self.portfolio_id
                ).delete(synchronize_session=False)

                # 删除当天该组合的汇总记录
                self.db_session.query(PortfolioDailySummary).filter(
                    PortfolioDailySummary.date == trading_date,
                    PortfolioDailySummary.portfolio_id == self.portfolio_id
                ).delete(synchronize_session=False)

                logger.debug(f"🗑️ 已删除 {trading_date} 组合 {self.portfolio_id} 的旧盈亏记录")

            # 插入新记录（直接 add，不 merge）
            for rec in self.daily_records:
                if rec['market_value'] <= 0:
                    continue
                db_record = DailyPnLRecord(
                    date=trading_date,
                    portfolio_id=self.portfolio_id,
                    stock_code=rec['code'],
                    stock_name=self._get_stock_name(rec['code']),
                    position_size=rec['size'],
                    cost_price=rec['cost_price'],
                    close_price=rec['current_price'],
                    market_value=rec['market_value'],
                    unrealized_pnl=rec['unrealized_pnl'],
                    pnl_pct=rec['pnl_pct'],
                    total_assets=total_value,
                    cash_balance=self.cash
                )
                self.db_session.add(db_record)

            # 插入组合汇总
            total_unrealized_pnl = sum(r['unrealized_pnl'] for r in self.daily_records)
            position_value = total_value - self.cash
            position_ratio = position_value / total_value if total_value > 0 else 0

            # 写入账户每日统计数据
            summary = PortfolioDailySummary(
                date=trading_date,
                portfolio_id=self.portfolio_id,
                total_assets=total_value,
                total_unrealized_pnl=total_unrealized_pnl,
                total_pnl_pct=(total_unrealized_pnl / (position_value) * 100) if position_value > 0 else 0,
                position_ratio=position_ratio,
                cash_balance=self.cash,
                daily_pnl_change=daily_pnl_change,
                cumulative_realized_pnl=self.cumulative_realized_pnl
            )
            self.db_session.add(summary)
            self.db_session.commit()

            logger.info(f"✅ 已保存 {len(self.daily_records)} 条个股 + 1 条组合记录（overwrite={overwrite}）")

            return True

        except Exception as e:
            logger.error(f"❌ 保存盈亏记录失败: {e}")
            self.db_session.rollback()
            return False
