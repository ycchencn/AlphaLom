"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import and_, desc, func
from models import AppLog
from models.database import db_session
from utils.logger import logger


class AppLogService:

    @staticmethod
    def get_by_id(log_id: int) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取单条日志
        """
        try:
            log = db_session.query(AppLog).filter(AppLog.id == log_id).first()
            return log.to_dict() if log else None
        except Exception as e:
            logger.error(f"Error fetching log by id {log_id}: {e}")
            return None

    @staticmethod
    def query_logs(
        level: Optional[str] = None,
        module: Optional[str] = None,
        keyword: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """
        分页查询日志列表
        
        :param level: 日志级别筛选
        :param module: 模块名筛选
        :param keyword: 关键词搜索（搜索 message）
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param page: 页码（从 1 开始）
        :param page_size: 每页数量
        :return: 包含 logs、total、page、page_size 的字典
        """
        try:
            query = db_session.query(AppLog)
            conditions = []

            if level:
                conditions.append(AppLog.level == level)

            if module:
                conditions.append(AppLog.module == module)

            if keyword:
                # 搜索 message 字段
                conditions.append(AppLog.message.like(f"%{keyword}%"))

            if start_time:
                conditions.append(AppLog.timestamp >= start_time)

            if end_time:
                conditions.append(AppLog.timestamp <= end_time)

            if conditions:
                query = query.filter(and_(*conditions))

            # 统计总数
            total = query.count()

            # 分页查询
            offset = (page - 1) * page_size
            logs = query.order_by(desc(AppLog.timestamp)).offset(offset).limit(page_size).all()

            return {
                'logs': [log.to_dict() for log in logs],
                'total': total,
                'page': page,
                'page_size': page_size
            }
        except Exception as e:
            logger.error(f"Error querying logs: {e}")
            return {
                'logs': [],
                'total': 0,
                'page': page,
                'page_size': page_size
            }

    @staticmethod
    def get_levels() -> List[str]:
        """
        获取所有日志级别
        """
        try:
            levels = db_session.query(AppLog.level).distinct().all()
            return [level[0] for level in levels if level[0]]
        except Exception as e:
            logger.error(f"Error fetching levels: {e}")
            return []

    @staticmethod
    def get_modules() -> List[str]:
        """
        获取所有模块名
        """
        try:
            modules = db_session.query(AppLog.module).distinct().all()
            return [module[0] for module in modules if module[0]]
        except Exception as e:
            logger.error(f"Error fetching modules: {e}")
            return []

    @staticmethod
    def get_statistics() -> Dict[str, Any]:
        """
        获取日志统计信息
        """
        try:
            total = db_session.query(AppLog).count()
            
            # 按级别统计
            level_rows = db_session.query(
                AppLog.level, func.count(AppLog.id)
            ).group_by(AppLog.level).all()
            level_counts = {level: count for level, count in level_rows if level}
            
            # 最新日志时间
            latest_log = db_session.query(AppLog).order_by(desc(AppLog.timestamp)).first()
            latest_time = latest_log.timestamp if latest_log else None
            
            return {
                'total': total,
                'level_counts': level_counts,
                'latest_time': latest_time.isoformat() if latest_time else None
            }
        except Exception as e:
            logger.error(f"Error fetching statistics: {e}")
            return {
                'total': 0,
                'level_counts': {},
                'latest_time': None
            }
