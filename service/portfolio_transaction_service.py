"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models import PortfolioTransaction
from models.database import db_session
from utils.logger import logger


class PortfolioTransactionService:

    @staticmethod
    def add(transaction_data):
        """
        @brief 添加一个新的 PortfolioTransaction 记录

        @param transaction_data: 包含交易数据的字典
        @type transaction_data: dict

        @return: 是否成功添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            transaction_data = {
                'date': '2026-01-22',
                'action': 'BUY',
                'code': '603019',
                'name': '中科曙光',
                'qty': 600,
                'price': 91.28,
                'amount': 54768.0,
                'realized_pnl': 0.0,
                'portfolio_id': 8
            }
            success = PortfolioTransactionService.add(transaction_data)
            print(success)
        """
        try:
            transaction = PortfolioTransaction(**transaction_data)
            db_session.add(transaction)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def batch_add(transactions_data):
        """
        @brief 批量添加多个 PortfolioTransaction 记录

        @param transactions_data: 包含多个交易数据的列表
        @type transactions_data: list

        @return: 是否成功批量添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            transactions_data = [
                {
                    'date': '2026-01-22',
                    'action': 'BUY',
                    'code': '603019',
                    'name': '中科曙光',
                    'qty': 600,
                    'price': 91.28,
                    'amount': 54768.0,
                    'realized_pnl': 0.0,
                    'portfolio_id': 8
                },
                {
                    'date': '2026-01-23',
                    'action': 'SELL',
                    'code': '000001',
                    'name': '平安银行',
                    'qty': 1000,
                    'price': 15.50,
                    'amount': 15500.0,
                    'realized_pnl': 200.0,
                    'portfolio_id': 8
                }
            ]
            success = PortfolioTransactionService.batch_add(transactions_data)
            print(success)
        """
        try:
            for trans_data in transactions_data:
                transaction = PortfolioTransaction(**trans_data)
                db_session.add(transaction)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def get_by_id(trans_id):
        """
        @brief 根据 ID 获取 PortfolioTransaction 记录

        @param trans_id: 交易记录ID
        @type trans_id: int

        @return: 交易记录的字典表示，如果没有找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            trans = PortfolioTransactionService.get_by_id(1)
            print(trans)
        """
        try:
            transaction = db_session.query(PortfolioTransaction).filter_by(id=trans_id).first()
            if transaction:
                return transaction.to_dict()
            else:
                return None
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def get_by_portfolio_id(portfolio_id):
        """
        @brief 根据 portfolio_id 获取所有交易记录

        @param portfolio_id: 投资组合ID
        @type portfolio_id: int

        @return: 交易记录列表（每个为字典），若无则返回空列表
        @rtype: list

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            transactions = PortfolioTransactionService.get_by_portfolio_id(8)
            print(transactions)
        """
        try:
            transactions = db_session.query(PortfolioTransaction).filter_by(portfolio_id=portfolio_id).order_by(PortfolioTransaction.created_at.desc()).all()
            return [t.to_dict() for t in transactions]
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return []

    @staticmethod
    def get_by_code_and_date(code, trade_date):
        """
        @brief 根据股票代码和交易日期获取交易记录

        @param code: 股票代码（如 '603019'）
        @type code: str
        @param trade_date: 交易日期（格式：'YYYY-MM-DD' 或 date 对象）
        @type trade_date: str or date

        @return: 交易记录列表（每个为字典）
        @rtype: list

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            transactions = PortfolioTransactionService.get_by_code_and_date('603019', '2026-01-22')
            print(transactions)
        """
        try:
            transactions = db_session.query(PortfolioTransaction).filter(
                PortfolioTransaction.code == code,
                PortfolioTransaction.date == trade_date
            ).all()
            return [t.to_dict() for t in transactions]
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return []

    @staticmethod
    def update_by_id(trans_id, update_data):
        """
        @brief 根据 ID 更新 PortfolioTransaction 记录

        @param trans_id: 交易记录ID
        @type trans_id: int
        @param update_data: 包含更新字段的字典
        @type update_data: dict

        @return: 是否成功更新
        @rtype: bool

        @throws: IntegrityError 如果更新违反数据库约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            update_data = {'realized_pnl': 150.0}
            success = PortfolioTransactionService.update_by_id(1, update_data)
            print(success)
        """
        try:
            transaction = db_session.query(PortfolioTransaction).filter_by(id=trans_id).first()
            if transaction:
                for key, value in update_data.items():
                    if hasattr(transaction, key):
                        setattr(transaction, key, value)
                db_session.commit()
                return True
            else:
                logger.warning(f"Transaction with id {trans_id} not found.")
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def delete_by_id(trans_id):
        """
        @brief 根据 ID 删除 PortfolioTransaction 记录

        @param trans_id: 交易记录ID
        @type trans_id: int

        @return: 是否成功删除
        @rtype: bool

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            success = PortfolioTransactionService.delete_by_id(1)
            print(success)
        """
        try:
            transaction = db_session.query(PortfolioTransaction).filter_by(id=trans_id).first()
            if transaction:
                db_session.delete(transaction)
                db_session.commit()
                return True
            else:
                logger.warning(f"Transaction with id {trans_id} not found.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False
