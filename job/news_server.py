"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pytz

from apscheduler.schedulers.blocking import BlockingScheduler
from job import job_news_scrape_all

if __name__ == '__main__':

    # 创建调度器实例
    scheduler = BlockingScheduler()

    # 指定时区为北京时间
    beijing_tz = pytz.timezone('Asia/Shanghai')

    # 采集新闻 【每小时】
    scheduler.add_job(job_news_scrape_all, 'cron', minute=0, timezone=beijing_tz)

    try:
        # 开始执行计划任务
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        # 当用户按下Ctrl+C 或者发生系统退出异常时，捕获异常并结束程序
        pass
