"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from models.database import db_session
from models import StockFinancialScore
from utils.logger import logger


class StockFinancialScoreService:

    # ─────────────────────────── 写操作 ───────────────────────────

    @staticmethod
    def upsert(data: dict):
        """
        插入或更新一条评分记录（按 code 唯一键）
        :param data: dict, 必须包含 'code'
        :return: bool
        """
        code = data.get('code')
        if not code:
            logger.error("upsert failed: 'code' is required")
            return False

        try:
            existing = db_session.query(StockFinancialScore).filter(
                StockFinancialScore.code == code
            ).first()

            if existing:
                for k, v in data.items():
                    if hasattr(existing, k) and k != 'id':
                        setattr(existing, k, v)
            else:
                db_session.add(StockFinancialScore(**data))

            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"upsert IntegrityError for code={code}: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"upsert error for code={code}: {e}")
        return False

    @staticmethod
    def batch_upsert(data_list: list):
        """
        批量插入或更新（逐条处理，与你的 batch_update_from_ai 风格一致）
        :param data_list: list of dict
        :return: (success_count, fail_count)
        """
        if not data_list:
            return 0, 0

        success, fail = 0, 0
        try:
            for item in data_list:
                code = item.get('code')
                if not code:
                    fail += 1
                    continue

                existing = db_session.query(StockFinancialScore).filter(
                    StockFinancialScore.code == code
                ).first()

                if existing:
                    for k, v in item.items():
                        if hasattr(existing, k) and k != 'id':
                            setattr(existing, k, v)
                else:
                    db_session.add(StockFinancialScore(**item))

                success += 1

            db_session.commit()
            return success, fail
        except Exception as e:
            db_session.rollback()
            logger.error(f"batch_upsert error: {e}")
            return success, len(data_list) - success

    @staticmethod
    def delete_by_code(code: str):
        """
        删除指定股票评分记录
        """
        try:
            item = db_session.query(StockFinancialScore).filter(
                StockFinancialScore.code == code
            ).first()
            if item:
                db_session.delete(item)
                db_session.commit()
                return True
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"delete_by_code error for '{code}': {e}")
            return False

    # ─────────────────────────── 读操作 ───────────────────────────

    @staticmethod
    def get_by_code(code: str):
        """
        按股票代码查询
        """
        try:
            return db_session.query(StockFinancialScore).filter(
                StockFinancialScore.code == code
            ).first()
        except Exception as e:
            logger.error(f"get_by_code error for '{code}': {e}")
            return None

    @staticmethod
    def get_top_scores(limit: int = 20, min_score: float = None):
        """
        获取综合评分最高的 N 条记录
        :param limit: 返回条数
        :param min_score: 最低评分过滤
        """
        try:
            query = db_session.query(StockFinancialScore)
            if min_score is not None:
                query = query.filter(
                    StockFinancialScore.composite_score >= min_score
                )
            return query.order_by(
                StockFinancialScore.composite_score.desc()
            ).limit(limit).all()
        except Exception as e:
            logger.error(f"get_top_scores error: {e}")
            return []

    @staticmethod
    def get_all(order_by='composite_score', desc=True):
        """
        获取全部记录，支持排序
        """
        try:
            query = db_session.query(StockFinancialScore)
            col = getattr(StockFinancialScore, order_by, None)
            if col is not None:
                query = query.order_by(col.desc() if desc else col.asc())
            return query.all()
        except Exception as e:
            logger.error(f"get_all error: {e}")
            return []

    @staticmethod
    def count():
        """总记录数"""
        try:
            return db_session.query(func.count(StockFinancialScore.id)).scalar()
        except Exception as e:
            logger.error(f"count error: {e}")
            return 0