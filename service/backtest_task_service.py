"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models.database import db_session  # 假设这是你的数据库会话
from models import BacktestTask  # 从你的模型文件导入BacktestTask
from utils.logger import logger  # 从你的日志工具中导入logger
from datetime import datetime, timedelta
from sqlalchemy import asc, and_, desc

class BacktestTaskService:

    @staticmethod
    def add_task(task_data):
        try:
            task = BacktestTask(**task_data)
            db_session.add(task)
            db_session.commit()
            return task.to_dict()
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Adding backtest task failed: {e}")
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
            return None

    @staticmethod
    def get_all_tasks():
        try:
            tasks = db_session.query(BacktestTask).all()
            return [task.to_dict() for task in tasks]
        except Exception as e:
            logger.error(f"An error occurred while fetching all tasks: {e}")
            return []

    @staticmethod
    def get_signal_match_counts(last_signal_trade_type='buy'):
        from sqlalchemy import func
        try:
            result = (
                db_session.query(
                    func.count().label('c'),
                    BacktestTask.last_signal_date
                )
                .filter(and_(
                    BacktestTask.trade_signal_match == 1,
                    BacktestTask.calmar_ratio >= 2,
                    BacktestTask.last_signal_trade_type == last_signal_trade_type
                ))
                .group_by(BacktestTask.last_signal_date)
                .order_by(BacktestTask.last_signal_date.asc())
                .limit(30)
            )
            return [{'_count': row.c, 'last_signal_date': row.last_signal_date.strftime('%Y-%m-%d')} for row in result]
        except Exception as e:
            logger.error(f"An error occurred while getting signal match counts: {e}")
            return []

    @staticmethod
    def get_signals(market, day_delta=7):
        seven_days_ago = datetime.now() - timedelta(days=day_delta)
        try:
            tasks = BacktestTask.query.filter(
                and_(BacktestTask.finished == 1,
                     BacktestTask.last_signal_date.isnot(None),
                     BacktestTask.last_signal_date >= seven_days_ago,
                     BacktestTask.securities_type == market,
                     BacktestTask.calmar_ratio >= 2,
                     )).order_by(desc(BacktestTask.last_signal_date), desc(BacktestTask.calmar_ratio)).limit(500)
            return [task.to_dict() for task in tasks]
        except Exception as e:
            logger.error(f"An error occurred while getting signal match counts: {e}")
            return []
