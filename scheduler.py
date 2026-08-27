"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pytz

from utils.logger import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from job import job_update_stock_factor_daily
from backtest.strategy.ai_position_plan_daily import job_position_plan_daily_all
from backtest.strategy.run_portfolio_daily import run_daily_strategy_all
from job.job_update_factors import job_update_financial_score_all
from job.job_update_stock_greedy_data import job_update_stock_greedy_data_daily
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis_daily
from job.job_stock_daily_update import job_stock_daily_update, job_update_stock_beta_all
from job.job_check_signal import job_check_signal_daily

if __name__ == '__main__':

    # 创建调度器实例
    scheduler = BlockingScheduler()

    # 指定时区为北京时间
    beijing_tz = pytz.timezone('Asia/Shanghai')

    # 量化回测任务执行
    scheduler.add_job(run_daily_strategy_all, 'cron', hour=16, minute=15, timezone=beijing_tz)

    # 量化回测任务执行，运算调仓计划
    scheduler.add_job(job_position_plan_daily_all, 'cron', hour=16, minute=30, timezone=beijing_tz)

    # 周日 20:30 执行运算调仓计划
    scheduler.add_job(job_position_plan_daily_all, 'cron', day_of_week='sun', hour=20, minute=30, timezone=beijing_tz, kwargs={'trade_day_override': True})

    # 每天 刷新个股信息
    scheduler.add_job(job_stock_daily_update, 'cron', hour=20, minute=10, timezone=beijing_tz)

    # 个股因子计算任务
    scheduler.add_job(job_update_stock_factor_daily, 'cron', hour=20, minute=10, timezone=beijing_tz)

    # 个股走势技术分析
    scheduler.add_job(job_check_signal_daily, 'cron', hour=20, minute=10, timezone=beijing_tz)

    # 量化回测任务执行，运算个股beta数据
    scheduler.add_job(job_update_stock_beta_all, 'cron', hour=20, minute=15, timezone=beijing_tz)

    # 更新个股恐贪数据
    scheduler.add_job(job_update_stock_greedy_data_daily, 'cron', hour=20, minute=55, timezone=beijing_tz)

    # 每周五晚上更新DCF数据
    scheduler.add_job(job_stock_dcf_model_analysis_daily, 'cron', day_of_week='fri', hour=20, minute=30, timezone=beijing_tz)

    # 每周五晚上更新基础评分
    scheduler.add_job(job_update_financial_score_all, 'cron', day_of_week='fri', hour=20, minute=30, timezone=beijing_tz)
    try:
        # 开始执行计划任务
        logger.info(f"running scheduler service")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        # 当用户按下Ctrl+C 或者发生系统退出异常时，捕获异常并结束程序
        pass
