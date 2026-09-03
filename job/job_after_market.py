
"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from backtest.strategy.run_portfolio_daily import run_daily_strategy_all
from backtest.strategy.ai_position_plan_daily import job_position_plan_daily_all

if __name__ == '__main__':

    run_daily_strategy_all()

    job_position_plan_daily_all(trade_day_override=True)