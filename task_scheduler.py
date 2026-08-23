# scheduler/task_scheduler.py
"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from service.scheduled_task_service import ScheduledTaskService
from models import TriggerType
from utils.logger import logger
from datetime import datetime
import pytz


class TaskScheduler:
    def __init__(self, timezone='Asia/Shanghai'):
        self.timezone_obj = pytz.timezone(timezone)
        self.scheduler = BackgroundScheduler(timezone=self.timezone_obj)
        self.job_ids = set()

    def load_tasks_from_db(self):
        """
        @brief 从数据库加载所有启用的定时任务（cron + date）并添加到调度器
        """
        tasks = ScheduledTaskService.get_active_tasks()
        for task in tasks:
            self._add_job(task)

    def _add_job(self, task: dict):
        """
        @brief 根据 trigger_type 添加 cron 或 date 类型任务

        @param task: 任务字典（来自数据库）
        @type task: dict
        """
        job_id = task['task_name']
        if job_id in self.job_ids:
            logger.debug(f"Job {job_id} already scheduled, skipping.")
            return

        try:
            trigger = None
            trigger_type = task.get('trigger_type')

            if trigger_type == TriggerType.CRON:
                if not task.get('cron_expression'):
                    raise ValueError("cron_expression is required for cron task")
                trigger = CronTrigger.from_crontab(
                    task['cron_expression'],
                    timezone=self.timezone_obj
                )
            elif trigger_type == TriggerType.DATE:
                run_at = task.get('run_at')
                if not run_at:
                    raise ValueError("run_at is required for date task")
                # run_at 可能是字符串或 datetime，确保是 datetime
                if isinstance(run_at, str):
                    run_at = datetime.fromisoformat(run_at.replace('Z', '+00:00'))
                # 如果 run_at 是 naive datetime，本地化为调度器时区
                if run_at.tzinfo is None:
                    run_at = self.timezone_obj.localize(run_at)
                trigger = DateTrigger(run_date=run_at, timezone=self.timezone_obj)
            else:
                raise ValueError(f"Unsupported trigger_type: {trigger_type}")

            self.scheduler.add_job(
                func=self._wrapped_execute,
                trigger=trigger,
                args=[task],
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            self.job_ids.add(job_id)
            logger.info(f"Added {trigger_type} job: {job_id} | Trigger: {trigger}")
        except Exception as e:
            logger.error(f"Failed to add job {job_id}: {e}")

    def _wrapped_execute(self, task: dict):
        """
        @brief 执行任务后，若为一次性任务，则标记为 inactive（可选）
        """
        job_id = task['task_name']
        now = datetime.now(self.timezone_obj)
        next_run = None

        job = self.scheduler.get_job(job_id)
        if job:
            next_run = job.next_run_time

        try:
            logger.info(f"Executing task: {job_id} ({task['trigger_type']})")
            ScheduledTaskService.execute_task(
                task['func_module'],
                task['func_name'],
                task['args'],
                task['kwargs']
            )
            logger.info(f"Task {job_id} executed successfully.")
        except Exception as e:
            logger.error(f"Task {job_id} failed: {e}")
        finally:
            # 更新运行时间
            ScheduledTaskService.update_last_and_next_run(job_id, now, next_run)

            # 【可选】一次性任务执行后自动禁用（避免重复加载）
            if task['trigger_type'] == TriggerType.DATE:
                self._deactivate_one_time_task(job_id)

    def _deactivate_one_time_task(self, task_name: str):
        """
        @brief 将一次性任务标记为 inactive，防止重启后重复执行
        """
        try:
            task = db_session.query(ScheduledTask).filter_by(task_name=task_name).first()
            if task and task.trigger_type == TriggerType.DATE:
                task.is_active = False
                db_session.commit()
                logger.info(f"One-time task {task_name} marked as inactive after execution.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to deactivate one-time task {task_name}: {e}")

    def start(self):
        if not self.scheduler.running:
            self.load_tasks_from_db()
            self.scheduler.start()
            logger.info("Task scheduler started with cron & one-time tasks.")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Task scheduler shut down.")

    def add_listener(self):
        def job_listener(event):
            if event.exception:
                logger.error(f"Job {event.job_id} raised exception: {event.exception}")
            else:
                logger.debug(f"Job {event.job_id} succeeded.")
        self.scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # ===== 新增：手动添加一次性任务的便捷方法 =====
    def add_one_time_task(
        self,
        task_name: str,
        func_module: str,
        func_name: str,
        run_at: datetime,
        args: list = None,
        kwargs: dict = None
    ):
        """
        @brief 动态添加一个一次性任务（同时写入数据库并加入调度器）

        @param task_name: 唯一任务名
        @param func_module: 模块路径
        @param func_name: 函数名
        @param run_at: 执行时间（datetime）
        @param args: 位置参数
        @param kwargs: 关键字参数
        """
        task_data = {
            "task_name": task_name,
            "func_module": func_module,
            "func_name": func_name,
            "args": args or [],
            "kwargs": kwargs or {},
            "trigger_type": TriggerType.DATE,
            "run_at": run_at,
            "is_active": True
        }

        # 先存入数据库
        if ScheduledTaskService.add(task_data):
            # 再加载进调度器
            self._add_job(task_data)
            logger.info(f"One-time task {task_name} added for {run_at}.")
        else:
            logger.error(f"Failed to persist one-time task {task_name} to DB.")


if __name__ == '__main__':

    scheduler = TaskScheduler()
    scheduler.start()
    # 保持主线程运行
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
