"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import StockFearGreed  # 请确保你的模型文件中已定义该类
from models.database import db_session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from utils.logger import logger
from datetime import date
from typing import List, Optional, Dict, Any


class StockFearGreedService:

    @staticmethod
    def batch_create(records: List[Dict[str, Any]]) -> bool:
        """
        批量插入恐惧贪婪指数记录（高性能版本）。
        :param records: 列表，每个元素为 dict，包含字段：
                        trade_date (date), index_code (str), close (float),
                        fear_greed (float), vol_score (float), mom_score (float)
        :return: True 成功，False 失败
        """
        if not records:
            logger.warning("batch_create called with empty records")
            return False

        try:
            # 使用 bulk_insert_mappings，避免逐个创建 ORM 对象
            db_session.bulk_insert_mappings(StockFearGreed, records)
            db_session.commit()
            logger.info(f"Successfully bulk-inserted {len(records)} fear/greed records.")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error during bulk_insert: {e}")
            db_session.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error in batch_create: {e}")
            db_session.rollback()
            return False

    @staticmethod
    def get_by_index_all(index_code: str, limit=60) -> List[Dict[str, Any]]:
        """
        根据指数代码和交易日期查询单条记录。
        :param index_code: 指数代码，如 '000905'
        :return: 字典形式的记录，或 None
        """
        try:
            records = db_session.query(StockFearGreed).filter(
                and_(
                    StockFearGreed.index_code == index_code,
                )
            ).order_by(StockFearGreed.trade_date.desc()).limit(limit).all()

            return [r.to_dict() for r in records] if records else []
        except Exception as e:
            logger.error(f"Error in get_by_index_and_range: {e}")
            return []

    @staticmethod
    def get_by_index_and_date(index_code: str, trade_date: date) -> Optional[Dict[str, Any]]:
        """
        根据指数代码和交易日期查询单条记录。
        :param index_code: 指数代码，如 '000905'
        :param trade_date: 交易日期
        :return: 字典形式的记录，或 None
        """
        try:
            record = db_session.query(StockFearGreed).filter_by(
                index_code=index_code,
                trade_date=trade_date
            ).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Error in get_by_index_and_date: {e}")
            return None

    @staticmethod
    def get_by_index_and_range(
        index_code: str,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """
        根据指数代码和时间范围查询多条记录。
        :param index_code: 指数代码
        :param start_date: 起始日期（含）
        :param end_date: 结束日期（含）
        :return: 记录列表（字典形式），按 trade_date 升序
        """
        try:
            records = db_session.query(StockFearGreed).filter(
                and_(
                    StockFearGreed.index_code == index_code,
                    StockFearGreed.trade_date >= start_date,
                    StockFearGreed.trade_date <= end_date
                )
            ).order_by(StockFearGreed.trade_date.asc()).all()

            return [r.to_dict() for r in records] if records else []
        except Exception as e:
            logger.error(f"Error in get_by_index_and_range: {e}")
            return []

    @staticmethod
    def get_latest_by_index(index_code: str) -> Optional[Dict[str, Any]]:
        """
        获取指定指数最新的恐惧贪婪记录。
        """
        try:
            record = db_session.query(StockFearGreed).filter_by(
                index_code=index_code
            ).order_by(StockFearGreed.trade_date.desc()).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Error in get_latest_by_index: {e}")
            return None

    @staticmethod
    def delete_by_index_and_date(index_code: str, trade_date: date) -> bool:
        """
        删除指定指数在指定日期的记录。
        """
        try:
            record = db_session.query(StockFearGreed).filter_by(
                index_code=index_code,
                trade_date=trade_date
            ).first()
            if record:
                db_session.delete(record)
                db_session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"DB error in delete: {e}")
            db_session.rollback()
            return False

    @staticmethod
    def delete_by_index(index_code: str) -> bool:
        """
        删除指定指数在指定日期的记录。
        """
        try:
            deleted_count = db_session.query(StockFearGreed).filter(
                StockFearGreed.index_code == index_code,
            ).delete(synchronize_session=False)
            db_session.commit()
            logger.info(f"Deleted {deleted_count} records for symbol: {index_code}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to delete data for symbol {index_code}: {e}")
            return False
