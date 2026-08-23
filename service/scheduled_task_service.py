# services/scheduled_task_service.py
"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.exc import IntegrityError
from models import ScheduledTask
from models.database import db_session
from utils.logger import logger
import importlib


class ScheduledTaskService:

    @staticmethod
    def add(task_data: Dict[str, Any]) -> bool:
        """
        @brief 添加一条定时任务配置到数据库

        @param task_data: 任务配置字典，需包含 task_name, func_module, func_name, cron_expression 等
        @type task_data: dict

        @return: 是否成功添加
        @rtype: bool

        @throws: IntegrityError 如果 task_name 重复
        @throws: Exception 其他数据库错误
        """
        try:
            task = ScheduledTask(**task_data)
            db_session.add(task)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Failed to add scheduled task (duplicate task_name?): {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error adding scheduled task: {e}")
        return False

    @staticmethod
    def get_active_tasks() -> List[Dict[str, Any]]:
        """
        @brief 获取所有启用的定时任务（包括 cron 和一次性任务）
        @return: 启用的任务列表
        @rtype: list of dict
        """
        try:
            tasks = db_session.query(ScheduledTask).filter_by(is_active=True).all()
            return [t.to_dict() for t in tasks]
        except Exception as e:
            logger.error(f"Failed to fetch active scheduled tasks: {e}")
        return []

    @staticmethod
    def update_last_and_next_run(task_name: str, last_run_at: Any, next_run_at: Any) -> bool:
        """
        @brief 更新任务的上次运行时间和下次运行时间

        @param task_name: 任务名称
        @type task_name: str
        @param last_run_at: 上次运行时间（datetime）
        @type last_run_at: datetime
        @param next_run_at: 下次运行时间（datetime）
        @type next_run_at: datetime

        @return: 是否更新成功
        @rtype: bool
        """
        try:
            task = db_session.query(ScheduledTask).filter_by(task_name=task_name).first()
            if not task:
                logger.warning(f"Scheduled task not found: {task_name}")
                return False
            task.last_run_at = last_run_at
            task.next_run_at = next_run_at
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to update run times for task {task_name}: {e}")
        return False

    @staticmethod
    def execute_task(func_module: str, func_name: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        """
        @brief 动态导入并执行指定函数

        @param func_module: 模块路径，如 'services.etf_service'
        @type func_module: str
        @param func_name: 函数名
        @type func_name: str
        @param args: 位置参数列表
        @type args: list
        @param kwargs: 关键字参数字典
        @type kwargs: dict

        @return: 函数执行结果（若无返回则为 None）
        @rtype: Any

        @throws: ImportError 模块或函数不存在
        @throws: Exception 函数执行异常
        """
        try:
            module = importlib.import_module(func_module)
            func = getattr(module, func_name)
            if not callable(func):
                raise AttributeError(f"{func_name} is not callable in {func_module}")
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"Error executing task {func_module}.{func_name}: {e}")
            raise