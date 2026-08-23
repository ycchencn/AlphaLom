"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models.database import db_session
from models import UserWatchlist  # 假设模型导入路径
from utils.logger import logger


class UserWatchlistService:

    @staticmethod
    def add(watch_data):
        """
        添加一条自选股记录
        :param watch_data: dict, 包含 stock_code, stock_name, price 等字段
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            watch_item = UserWatchlist(**watch_data)
            db_session.add(watch_item)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed (IntegrityError): {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during insertion: {e}")
        return False

    @staticmethod
    def get_by_code(stock_code: str):
        """
        根据股票代码获取自选股信息
        :param stock_code: str, 股票代码
        :return: UserWatchlist object or None
        """
        try:
            return db_session.query(UserWatchlist).filter(
                UserWatchlist.stock_code == stock_code
            ).first()
        except Exception as e:
            logger.error(f"Error fetching watchlist by code '{stock_code}': {e}")
            return None

    @staticmethod
    def update_price_diff(stock_code: str, price: float, diff: float):
        """
        更新指定股票的行情数据（价格和涨跌幅）
        :param stock_code: str, 股票代码
        :param price: float, 当前价格
        :param diff: float, 涨跌幅
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            item = db_session.query(UserWatchlist).filter(
                UserWatchlist.stock_code == stock_code
            ).first()

            if not item:
                logger.warning(f"Stock '{stock_code}' not found in watchlist for update.")
                return False

            item.price = price
            item.diff = diff
            # 这里不需要手动更新时间戳，因为 created_at 有默认值，
            # 如果需要 updated_at 字段建议在模型中添加，此处仅更新业务数据

            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating price/diff for '{stock_code}': {e}")
            return False

    @staticmethod
    def delete_by_code(stock_code: str):
        """
        从自选股中移除股票
        :param stock_code: str, 股票代码
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            item = db_session.query(UserWatchlist).filter(
                UserWatchlist.stock_code == stock_code
            ).first()

            if item:
                db_session.delete(item)
                db_session.commit()
                return True
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error deleting stock '{stock_code}': {e}")
            return False

    @staticmethod
    def get_all(user_id=None, securities_type='stock'):
        """
        获取所有自选股列表
        注：当前模型未包含 user_id 字段，若需支持多用户，请在模型中添加该字段并在查询时过滤
        :return: list of UserWatchlist
        """
        try:
            query = db_session.query(UserWatchlist)
            query = query.filter(UserWatchlist.securities_type==securities_type)
            # 如果未来添加了 user_id 支持，可以在这里加上 .filter(UserWatchlist.user_id == user_id)
            return query.order_by(UserWatchlist.created_at.desc()).all()
        except Exception as e:
            logger.error(f"Error fetching all watchlist items: {e}")
            return []

    @staticmethod
    def batch_update_from_ai(ai_stocks):
        """
        批量更新或插入 AI 推荐的股票 (from_ai=1)
        :param ai_stocks: list of dict
        :return: bool
        """
        if not ai_stocks:
            return True

        try:
            # 简单实现：遍历处理。生产环境建议使用 bulk_upsert 或特定数据库的 ON CONFLICT DO UPDATE
            for stock_data in ai_stocks:
                stock_data['from_ai'] = 1  # 强制标记为AI推荐
                existing = db_session.query(UserWatchlist).filter(
                    UserWatchlist.stock_code == stock_data.get('stock_code')
                ).first()

                if existing:
                    # 更新现有记录
                    for k, v in stock_data.items():
                        if hasattr(existing, k):
                            setattr(existing, k, v)
                else:
                    # 新增记录
                    new_item = UserWatchlist(**stock_data)
                    db_session.add(new_item)

            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error in batch AI update: {e}")
            return False
