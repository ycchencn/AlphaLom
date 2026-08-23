"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models import DailyPnLRecord
from models.database import db_session
from utils.logger import logger
from typing import Dict, Any, List, Optional


class DailyPnLRecordService:

    @staticmethod
    def add(record_data: Dict[str, Any]) -> bool:
        """
        @brief 添加一条 DailyPnLRecord 记录

        @param record_data: 包含单条盈亏记录的字典
        @type record_data: dict

        @return: 是否成功添加
        @rtype: bool

        @throws: IntegrityError 如果违反唯一性约束（如重复 date + portfolio_id + stock_code）
        @throws: Exception 其他数据库错误

        @example:
            data = {
                'date': '2025-12-31',
                'portfolio_id': 'port_001',
                'stock_code': 'AAPL',
                'stock_name': 'Apple Inc.',
                'position_size': 100,
                'cost_price': 150.0000,
                'close_price': 160.0000,
                'market_value': 16000.00,
                'unrealized_pnl': 1000.00,
                'pnl_pct': 6.6667,
                'total_assets': 1000000.00,
                'cash_balance': 150000.00
            }
            success = DailyPnLRecordService.add(data)
            print(success)
        """
        try:
            record = DailyPnLRecord(**record_data)
            db_session.add(record)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed due to integrity constraint: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during insertion: {e}")
        return False

    @staticmethod
    def batch_add(records_data: List[Dict[str, Any]]) -> bool:
        """
        @brief 批量添加多条 DailyPnLRecord 记录

        @param records_data: 多条记录的列表
        @type records_data: list of dict

        @return: 是否全部成功添加
        @rtype: bool

        @throws: IntegrityError 若任一记录违反唯一约束
        @throws: Exception 其他错误

        @example:
            records = [ {...}, {...} ]
            success = DailyPnLRecordService.batch_add(records)
        """
        try:
            for data in records_data:
                record = DailyPnLRecord(**data)
                db_session.add(record)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch insertion failed due to integrity constraint: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during batch insertion: {e}")
        return False

    @staticmethod
    def get_by_date_portfolio_stock(date: str, portfolio_id: str, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        @brief 根据日期、组合ID、股票代码获取单条记录

        @param date: 交易日期（'YYYY-MM-DD'）
        @param portfolio_id: 组合ID
        @param stock_code: 股票代码
        @return: 记录字典或 None
        """
        try:
            record = db_session.query(DailyPnLRecord).filter_by(
                date=date,
                portfolio_id=portfolio_id,
                stock_code=stock_code
            ).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Failed to fetch record by date={date}, portfolio={portfolio_id}, stock={stock_code}: {e}")
        return None

    @staticmethod
    def get_all_by_portfolio_and_date(portfolio_id: str, date: str) -> List[Dict[str, Any]]:
        """
        @brief 获取某组合在某一天的所有持仓盈亏记录

        @param portfolio_id: 组合ID
        @param date: 交易日期
        @return: 记录列表（可能为空）
        """
        try:
            records = db_session.query(DailyPnLRecord).filter_by(
                portfolio_id=portfolio_id,
                date=date
            ).all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to fetch records for portfolio={portfolio_id} on date={date}: {e}")
        return []

    @staticmethod
    def get_all_by_portfolio_id(portfolio_id) -> List[Dict[str, Any]]:
        """
        @brief 获取某组合所有历史 DailyPnLRecord（按日期降序）

        @param portfolio_id: 组合ID
        @return: 所有记录列表（按 date desc 排序）
        """
        try:
            records = db_session.query(DailyPnLRecord)\
                .filter_by(portfolio_id=portfolio_id)\
                .order_by(DailyPnLRecord.date.desc())\
                .all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to fetch all records for portfolio_id={portfolio_id}: {e}")
        return []

    @staticmethod
    def get_last_by_portfolio_id(portfolio_id: str) -> List[Dict[str, Any]]:
        """
        @brief 获取某组合最新交易日的所有持仓盈亏记录（即“最新快照”）

        @param portfolio_id: 组合ID
        @return: 最新日期下的所有记录列表；若无数据则返回空列表

        @note: 先查最大日期，再查该日期下所有股票
        """
        try:
            # Step 1: 获取该组合的最新日期
            latest_date = db_session.query(DailyPnLRecord.date)\
                .filter_by(portfolio_id=portfolio_id)\
                .order_by(DailyPnLRecord.date.desc())\
                .first()

            if not latest_date:
                return []

            # Step 2: 查询该日期下所有记录
            records = db_session.query(DailyPnLRecord)\
                .filter_by(portfolio_id=portfolio_id, date=latest_date[0])\
                .all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to fetch latest PnL snapshot for portfolio_id={portfolio_id}: {e}")
        return []

    @staticmethod
    def update_by_date_portfolio_stock(
        date: str,
        portfolio_id: str,
        stock_code: str,
        update_data: Dict[str, Any]
    ) -> bool:
        """
        @brief 根据 date + portfolio_id + stock_code 更新记录

        @param date: 交易日期
        @param portfolio_id: 组合ID
        @param stock_code: 股票代码
        @param update_data: 要更新的字段字典
        @return: 是否成功更新
        """
        try:
            record = db_session.query(DailyPnLRecord).filter_by(
                date=date,
                portfolio_id=portfolio_id,
                stock_code=stock_code
            ).first()

            if not record:
                logger.warning(f"Record not found for update: {date}, {portfolio_id}, {stock_code}")
                return False

            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
                else:
                    logger.warning(f"Ignoring unknown field in update: {key}")
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed due to integrity constraint: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during update: {e}")
        return False

    @staticmethod
    def delete_by_date_portfolio_stock(date: str, portfolio_id: str, stock_code: str) -> bool:
        """
        @brief 删除指定记录

        @param date: 交易日期
        @param portfolio_id: 组合ID
        @param stock_code: 股票代码
        @return: 是否成功删除
        """
        try:
            record = db_session.query(DailyPnLRecord).filter_by(
                date=date,
                portfolio_id=portfolio_id,
                stock_code=stock_code
            ).first()
            if not record:
                logger.warning(f"Record not found for deletion: {date}, {portfolio_id}, {stock_code}")
                return False
            db_session.delete(record)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to delete record: {e}")
        return False

    @staticmethod
    def delete_all_by_portfolio_and_date(portfolio_id: str, date: str) -> bool:
        """
        @brief 删除某组合在某一天的所有盈亏记录（用于重算当日快照）

        @param portfolio_id: 组合ID
        @param date: 交易日期
        @return: 是否删除成功
        """
        try:
            deleted_count = db_session.query(DailyPnLRecord)\
                .filter_by(portfolio_id=portfolio_id, date=date)\
                .delete(synchronize_session=False)
            db_session.commit()
            logger.info(f"Deleted {deleted_count} records for portfolio={portfolio_id} on date={date}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to delete all records for portfolio={portfolio_id} on date={date}: {e}")
        return False
