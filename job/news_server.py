"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pytz

from apscheduler.schedulers.blocking import BlockingScheduler
from job import job_news_scrape_all
from job.job_news_digest import job_news_digest_hourly
from service.news_digest_service import (
    REFRESH_HOUR_END,
    REFRESH_HOUR_START,
    REFRESH_MINUTE,
)

if __name__ == '__main__':

    # 创建调度器实例
    scheduler = BlockingScheduler()

    # 指定时区为北京时间
    beijing_tz = pytz.timezone('Asia/Shanghai')

    # 采集新闻 【每小时】
    scheduler.add_job(job_news_scrape_all, 'cron', minute=0, timezone=beijing_tz)

    # 新闻流 AI 速览（事件驱动页顶部 AI 推荐卡片）【每小时，活跃时段】
    # ⚠️ 三个参数全部取自 service.news_digest_service 的常量，与「前端显示下一轮几点刷新」
    #    用的是同一份口径 —— 曾经把 cron 和接口各写一遍，改了一处另一处就说不清了。
    # minute 取 REFRESH_MINUTE（30）而不是 0：采集任务在整点开始，把新新闻留给它。
    scheduler.add_job(
        job_news_digest_hourly, 'cron',
        hour=f'{REFRESH_HOUR_START}-{REFRESH_HOUR_END}',
        minute=REFRESH_MINUTE,
        timezone=beijing_tz,
    )

    try:
        # 开始执行计划任务
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        # 当用户按下Ctrl+C 或者发生系统退出异常时，捕获异常并结束程序
        pass
