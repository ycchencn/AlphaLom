"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models import PortfolioDailySummary
from models.database import db_session
from utils.logger import logger
from typing import Dict, Any, List, Optional


class PortfolioDailySummaryService:

    @staticmethod
    def add(summary_data: Dict[str, Any]) -> bool:
        """
        @brief 添加一个新的 PortfolioDailySummary 记录

        @param summary_data: 包含组合日度汇总数据的字典
        @type summary_data: dict

        @return: 是否成功添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束（如 date + portfolio_id 重复）
        @throws: Exception 如果发生其他错误

        @example:
            summary_data = {
                'date': '2025-12-31',
                'portfolio_id': 'port_001',
                'total_assets': 1000000.00,
                'total_unrealized_pnl': 50000.00,
                'total_pnl_pct': 5.0000,
                'position_ratio': 0.8500,
                'cash_balance': 150000.00
            }
            success = PortfolioDailySummaryService.add(summary_data)
            print(success)
        """
        try:
            summary = PortfolioDailySummary(**summary_data)
            db_session.add(summary)
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
    def batch_add(summaries_data: List[Dict[str, Any]]) -> bool:
        """
        @brief 批量添加多个 PortfolioDailySummary 记录

        @param summaries_data: 包含多个组合日度汇总数据的列表
        @type summaries_data: list of dict

        @return: 是否成功批量添加记录
        @rtype: bool

        @throws: IntegrityError 如果任一记录违反唯一性约束（如重复日期+组合ID）
        @throws: Exception 如果发生其他错误

        @example:
            summaries_data = [
                {
                    'date': '2025-12-30',
                    'portfolio_id': 'port_001',
                    'total_assets': 990000.00,
                    ...
                },
                {
                    'date': '2025-12-31',
                    'portfolio_id': 'port_001',
                    'total_assets': 1000000.00,
                    ...
                }
            ]
            success = PortfolioDailySummaryService.batch_add(summaries_data)
            print(success)
        """
        try:
            for data in summaries_data:
                summary = PortfolioDailySummary(**data)
                db_session.add(summary)
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
    def get_by_date_and_portfolio(date: str, portfolio_id: str) -> Optional[Dict[str, Any]]:
        """
        @brief 根据日期和组合ID获取单条 PortfolioDailySummary 记录

        @param date: 交易日期（格式：'YYYY-MM-DD'）
        @type date: str
        @param portfolio_id: 组合ID
        @type portfolio_id: str

        @return: 记录的字典表示，若未找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            record = PortfolioDailySummaryService.get_by_date_and_portfolio('2025-12-31', 'port_001')
            print(record)
        """
        try:
            summary = db_session.query(PortfolioDailySummary).filter_by(
                date=date,
                portfolio_id=portfolio_id
            ).first()
            return summary.to_dict() if summary else None
        except Exception as e:
            logger.error(f"Failed to fetch record by date={date} and portfolio_id={portfolio_id}: {e}")
        return None

    @staticmethod
    def get_all_by_portfolio_id(portfolio_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        @brief 根据组合ID获取所有 PortfolioDailySummary 记录（按日期升序）

        @param portfolio_id: 组合ID
        @type portfolio_id: str

        @return: 记录列表（每个元素为字典），若无记录则返回空列表
        @rtype: list of dict

        @throws: Exception 如果发生其他错误

        @example:
            records = PortfolioDailySummaryService.get_all_by_portfolio_id('port_001')
            print(records)
        """
        try:
            summaries = db_session.query(PortfolioDailySummary)\
                .filter_by(portfolio_id=portfolio_id)\
                .order_by(PortfolioDailySummary.date.asc())\
                .all()
            return [s.to_dict() for s in summaries]
        except Exception as e:
            logger.error(f"Failed to fetch all records for portfolio_id={portfolio_id}: {e}")
        return []

    @staticmethod
    def update_by_date_and_portfolio(date: str, portfolio_id: str, update_data: Dict[str, Any]) -> bool:
        """
        @brief 根据日期和组合ID更新 PortfolioDailySummary 记录

        @param date: 交易日期（格式：'YYYY-MM-DD'）
        @type date: str
        @param portfolio_id: 组合ID
        @type portfolio_id: str
        @param update_data: 需要更新的字段字典
        @type update_data: dict

        @return: 是否成功更新
        @rtype: bool

        @throws: IntegrityError 如果更新导致唯一性冲突
        @throws: Exception 如果发生其他错误

        @example:
            update_data = {
                'total_assets': 1010000.00,
                'cash_balance': 140000.00
            }
            success = PortfolioDailySummaryService.update_by_date_and_portfolio('2025-12-31', 'port_001', update_data)
            print(success)
        """
        try:
            summary = db_session.query(PortfolioDailySummary).filter_by(
                date=date,
                portfolio_id=portfolio_id
            ).first()
            if not summary:
                logger.warning(f"No record found for date={date}, portfolio_id={portfolio_id}")
                return False

            for key, value in update_data.items():
                if hasattr(summary, key):
                    setattr(summary, key, value)
                else:
                    logger.warning(f"Ignoring unknown field: {key}")
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
    def delete_by_date_and_portfolio(date: str, portfolio_id: str) -> bool:
        """
        @brief 根据日期和组合ID删除 PortfolioDailySummary 记录

        @param date: 交易日期（格式：'YYYY-MM-DD'）
        @type date: str
        @param portfolio_id: 组合ID
        @type portfolio_id: str

        @return: 是否成功删除
        @rtype: bool

        @throws: Exception 如果发生其他错误

        @example:
            success = PortfolioDailySummaryService.delete_by_date_and_portfolio('2025-12-31', 'port_001')
            print(success)
        """
        try:
            summary = db_session.query(PortfolioDailySummary).filter_by(
                date=date,
                portfolio_id=portfolio_id
            ).first()
            if not summary:
                logger.warning(f"Record not found for deletion: date={date}, portfolio_id={portfolio_id}")
                return False

            db_session.delete(summary)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to delete record: {e}")
        return False

    @staticmethod
    def get_last_by_portfolio_id(portfolio_id) -> Optional[Dict[str, Any]]:
        """
        @brief 获取指定 portfolio_id 的最新一条 PortfolioDailySummary 记录（按 date 降序取第一条）

        @param portfolio_id: 组合ID
        @type portfolio_id: str

        @return: 最新记录的字典表示，若不存在则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他数据库错误

        @example:
            latest = PortfolioDailySummaryService.get_last_by_portfolio_id('port_001')
            if latest:
                print(f"Latest assets: {latest['total_assets']}")
        """
        try:
            summary = db_session.query(PortfolioDailySummary)\
                .filter_by(portfolio_id=portfolio_id)\
                .order_by(PortfolioDailySummary.date.desc())\
                .first()
            return summary.to_dict() if summary else None
        except Exception as e:
            logger.error(f"Failed to fetch latest record for portfolio_id={portfolio_id}: {e}")
        return None
