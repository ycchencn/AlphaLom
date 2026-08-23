"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_, desc
from models import SystemLog
from models.database import db_session
from utils.logger import logger


class LogType:
    """日志类型常量"""
    SYSTEM = 1  # 系统日志
    USER_ACTION = 2  # 用户操作日志


class LogLevel:
    """日志级别常量"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARN = logging.WARN
    ERROR = logging.ERROR
    FATAL = logging.FATAL


class LogStatus:
    """日志状态常量"""
    FAILED = 0
    SUCCESS = 1


class LogService:

    @staticmethod
    def add(log_data: Dict[str, Any]) -> bool:
        """
        添加一条日志记录
        :param log_data: dict, 包含日志相关字段
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            # 设置默认值
            if 'operation_time' not in log_data:
                log_data['operation_time'] = datetime.utcnow()
            if 'created_at' not in log_data:
                log_data['created_at'] = datetime.utcnow()
            if 'status' not in log_data:
                log_data['status'] = LogStatus.SUCCESS

            log = SystemLog(**log_data)
            db_session.add(log)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Log insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred while adding log: {e}")
        return False

    @staticmethod
    def batch_add(log_list: List[Dict[str, Any]]) -> bool:
        """
        批量添加日志记录
        :param log_list: list, 每项为包含日志数据的 dict
        :return: bool, 成功返回 True，失败返回 False
        """
        if not log_list:
            return True

        try:
            # 设置默认时间
            now = datetime.utcnow()
            for log_data in log_list:
                if 'operation_time' not in log_data:
                    log_data['operation_time'] = now
                if 'created_at' not in log_data:
                    log_data['created_at'] = now
                if 'status' not in log_data:
                    log_data['status'] = LogStatus.SUCCESS

            db_session.bulk_insert_mappings(SystemLog, log_list)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch log insertion failed due to integrity error: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error during batch log insertion: {e}")
            return False

    @staticmethod
    def get_by_id(log_id: int) -> Optional[SystemLog]:
        """
        根据 ID 获取日志记录
        :param log_id: int, 日志 ID
        :return: SystemLog or None
        """
        try:
            return db_session.query(SystemLog).filter(SystemLog.id == log_id).first()
        except Exception as e:
            logger.error(f"Error fetching log by id '{log_id}': {e}")
            return None

    @staticmethod
    def get_by_request_id(request_id: str) -> List[SystemLog]:
        """
        根据 request_id 获取相关日志（用于链路追踪）
        :param request_id: str, 请求追踪 ID
        :return: list of SystemLog
        """
        try:
            return db_session.query(SystemLog).filter(
                SystemLog.request_id == request_id
            ).order_by(SystemLog.operation_time.asc()).all()
        except Exception as e:
            logger.error(f"Error fetching logs by request_id '{request_id}': {e}")
            return []

    @staticmethod
    def get_by_user_id(user_id: int, limit: int = 100) -> List[SystemLog]:
        """
        获取指定用户的操作日志
        :param user_id: int, 用户 ID
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            return db_session.query(SystemLog).filter(
                and_(
                    SystemLog.user_id == user_id,
                    SystemLog.log_type == LogType.USER_ACTION
                )
            ).order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error fetching logs for user_id '{user_id}': {e}")
            return []

    @staticmethod
    def get_by_module(module: str, limit: int = 100) -> List[SystemLog]:
        """
        获取指定模块的日志
        :param module: str, 模块名称
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            return db_session.query(SystemLog).filter(
                SystemLog.module == module
            ).order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error fetching logs for module '{module}': {e}")
            return []

    @staticmethod
    def get_by_time_range(
        start_time: datetime,
        end_time: datetime,
        log_type: Optional[int] = None,
        log_level: Optional[int] = None,
        limit: int = 1000
    ) -> List[SystemLog]:
        """
        按时间范围查询日志
        :param start_time: datetime, 开始时间
        :param end_time: datetime, 结束时间
        :param log_type: int, 日志类型（可选）
        :param log_level: int, 日志级别（可选）
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            query = db_session.query(SystemLog).filter(
                and_(
                    SystemLog.operation_time >= start_time,
                    SystemLog.operation_time <= end_time
                )
            )

            if log_type is not None:
                query = query.filter(SystemLog.log_type == log_type)

            if log_level is not None:
                query = query.filter(SystemLog.log_level == log_level)

            return query.order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error fetching logs by time range: {e}")
            return []

    @staticmethod
    def get_error_logs(
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[SystemLog]:
        """
        获取错误日志（ERROR 和 FATAL 级别）
        :param start_time: datetime, 开始时间（默认 24 小时前）
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            if start_time is None:
                start_time = datetime.utcnow() - timedelta(hours=24)

            return db_session.query(SystemLog).filter(
                and_(
                    SystemLog.log_level.in_([LogLevel.ERROR, LogLevel.FATAL]),
                    SystemLog.operation_time >= start_time
                )
            ).order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error fetching error logs: {e}")
            return []

    @staticmethod
    def get_failed_operations(
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[SystemLog]:
        """
        获取失败的操作日志（status = 0）
        :param start_time: datetime, 开始时间（默认 24 小时前）
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            if start_time is None:
                start_time = datetime.utcnow() - timedelta(hours=24)

            return db_session.query(SystemLog).filter(
                and_(
                    SystemLog.status == LogStatus.FAILED,
                    SystemLog.operation_time >= start_time
                )
            ).order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error fetching failed operation logs: {e}")
            return []

    @staticmethod
    def search_logs(
        keyword: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[SystemLog]:
        """
        搜索日志（支持 content、error_message、module 等字段模糊匹配）
        :param keyword: str, 搜索关键词
        :param start_time: datetime, 开始时间（可选）
        :param end_time: datetime, 结束时间（可选）
        :param limit: int, 返回数量限制
        :return: list of SystemLog
        """
        try:
            query = db_session.query(SystemLog).filter(
                or_(
                    SystemLog.content.like(f"%{keyword}%"),
                    SystemLog.error_message.like(f"%{keyword}%"),
                    SystemLog.module.like(f"%{keyword}%"),
                    SystemLog.action.like(f"%{keyword}%")
                )
            )

            if start_time is not None:
                query = query.filter(SystemLog.operation_time >= start_time)

            if end_time is not None:
                query = query.filter(SystemLog.operation_time <= end_time)

            return query.order_by(desc(SystemLog.operation_time)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error searching logs with keyword '{keyword}': {e}")
            return []

    @staticmethod
    def get_statistics(
        start_time: datetime,
        end_time: datetime,
        group_by: str = 'module'
    ) -> List[Dict[str, Any]]:
        """
        获取日志统计信息
        :param start_time: datetime, 开始时间
        :param end_time: datetime, 结束时间
        :param group_by: str, 分组字段 ('module', 'log_level', 'status')
        :return: list of dict, 统计结果
        """
        try:
            from sqlalchemy import func

            if group_by == 'module':
                group_field = SystemLog.module
            elif group_by == 'log_level':
                group_field = SystemLog.log_level
            elif group_by == 'status':
                group_field = SystemLog.status
            else:
                logger.warning(f"Unsupported group_by field: {group_by}")
                return []

            results = db_session.query(
                group_field,
                func.count(SystemLog.id).label('count')
            ).filter(
                and_(
                    SystemLog.operation_time >= start_time,
                    SystemLog.operation_time <= end_time
                )
            ).group_by(group_field).all()

            return [{'group': str(r[0]), 'count': r[1]} for r in results]
        except Exception as e:
            logger.error(f"Error fetching log statistics: {e}")
            return []

    @staticmethod
    def cleanup_old_logs(
        days_to_keep: int = 90,
        batch_size: int = 10000
    ) -> int:
        """
        清理旧日志（用于定期维护）
        :param days_to_keep: int, 保留天数
        :param batch_size: int, 每批删除数量
        :return: int, 删除的日志数量
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)

            # 先查询需要删除的数量
            count_query = db_session.query(SystemLog).filter(
                SystemLog.operation_time < cutoff_time
            )
            total_count = count_query.count()

            if total_count == 0:
                logger.info(f"No logs older than {days_to_keep} days to clean up.")
                return 0

            # 分批删除，避免锁表
            deleted_count = 0
            while True:
                ids_to_delete = [
                    log.id for log in count_query.limit(batch_size).all()
                ]

                if not ids_to_delete:
                    break

                db_session.query(SystemLog).filter(
                    SystemLog.id.in_(ids_to_delete)
                ).delete(synchronize_session=False)
                db_session.commit()

                deleted_count += len(ids_to_delete)
                logger.info(f"Deleted {deleted_count}/{total_count} old logs.")

            logger.info(f"Log cleanup completed. Total deleted: {deleted_count}")
            return deleted_count
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Log cleanup failed due to integrity error: {e}")
            return 0
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during log cleanup: {e}")
            return 0

    @staticmethod
    def info(
        module: str,
        content: str,
        request_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ) -> bool:
        """
        便捷方法：创建系统日志
        :param module: str, 模块名称
        :param content: str, 日志内容
        :param request_id: str, 请求 ID（可选）
        :param error_code: str, 错误码（可选）
        :param error_message: str, 错误信息（可选）
        :param extra_data: dict, 扩展数据（可选）
        :return: bool, 成功返回 True
        """
        log_data = {
            'log_type': LogType.SYSTEM,
            'log_level': LogLevel.INFO,
            'module': module,
            'content': content,
            'request_id': request_id,
            'error_code': error_code,
            'error_message': error_message,
            'extra_data': extra_data,
            'status': LogStatus.FAILED if error_message else LogStatus.SUCCESS,
        }
        logger.info(content)
        return LogService.add(log_data)

    @staticmethod
    def system_log(
        module: str,
        level: int,
        content: str,
        request_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ) -> bool:
        """
        便捷方法：创建系统日志
        :param module: str, 模块名称
        :param level: int, 日志级别
        :param content: str, 日志内容
        :param request_id: str, 请求 ID（可选）
        :param error_code: str, 错误码（可选）
        :param error_message: str, 错误信息（可选）
        :param extra_data: dict, 扩展数据（可选）
        :return: bool, 成功返回 True
        """
        log_data = {
            'log_type': LogType.SYSTEM,
            'log_level': level,
            'module': module,
            'content': content,
            'request_id': request_id,
            'error_code': error_code,
            'error_message': error_message,
            'extra_data': extra_data,
            'status': LogStatus.FAILED if error_message else LogStatus.SUCCESS,
        }
        logger.info(content)
        return LogService.add(log_data)

    @staticmethod
    def user_log(
        user_id: int,
        username: str,
        module: str,
        action: str,
        ip_address: str,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        content: Optional[str] = None,
        extra_data: Optional[Dict] = None,
        status: int = LogStatus.SUCCESS,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        便捷方法：创建用户操作日志
        :param user_id: int, 用户 ID
        :param username: str, 用户名
        :param module: str, 模块名称
        :param action: str, 操作动作
        :param ip_address: str, IP 地址
        :param user_agent: str, 用户代理（可选）
        :param request_id: str, 请求 ID（可选）
        :param content: str, 日志内容（可选）
        :param extra_data: dict, 扩展数据（可选）
        :param status: int, 状态
        :param error_message: str, 错误信息（可选）
        :return: bool, 成功返回 True
        """
        log_data = {
            'log_type': LogType.USER_ACTION,
            'log_level': LogLevel.INFO,
            'module': module,
            'action': action,
            'user_id': user_id,
            'username': username,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'request_id': request_id,
            'content': content,
            'extra_data': extra_data,
            'status': status,
            'error_message': error_message,
        }
        return LogService.add(log_data)
