"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from models import Stock
from models.database import db_session
from utils.common import logger
from utils.common import get_today
from typing import List, Optional, Dict, Any
from sqlalchemy import func, and_
from sqlalchemy import or_, asc, desc

class StockService:

    @staticmethod
    def get_stock_by_symbol(
        symbol: str,
        fields: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        根据 symbol 获取股票信息，并支持筛选返回字段

        Args:
            symbol: 股票代码
            fields: 指定返回的字段列表（如 ["symbol", "name"]），为 None 时返回全部字段

        Returns:
            包含指定字段的字典，或 None（如果股票不存在）
        """
        stock = db_session.query(Stock).filter_by(symbol=symbol).first()
        if not stock:
            return None

        stock_dict = stock.to_dict()  # 假设 to_dict() 返回所有字段的字典

        if fields is not None:
            # 筛选字段，忽略不存在的字段
            return {field: stock_dict.get(field) for field in fields if field in stock_dict}
        else:
            return stock_dict

    @staticmethod
    def get_all_stocks(page: int = None, per_page: int = None) -> List[Dict[str, Any]]:
        """
        获取所有股票，支持分页。
        :param page: 页码（从1开始）
        :param per_page: 每页数量
        """
        query = db_session.query(Stock)
        if page is not None and per_page is not None:
            offset = (page - 1) * per_page
            stocks = query.offset(offset).limit(per_page).all()
        else:
            stocks = query.all()
        return [stock.to_dict() for stock in stocks]

    @staticmethod
    def get_monitoring_stock_pool(page=1, per_page=25, market=None) -> List[Dict[str, Any]]:
        stocks = StockService.search_stocks(
            securities_type='stock',
            monitoring=1,
            page=page,
            per_page=per_page,
            market=market
        )
        return stocks


    @staticmethod
    def get_etfs(page=1, per_page=25, market=None) -> List[Dict[str, Any]]:
        stocks = StockService.search_stocks(
            securities_type='etf',
            page=page,
            per_page=per_page,
            market=market
        )
        return stocks

    @staticmethod
    def search_stocks(
        keyword: str = None,
        market: str = None,
        concepts: str = None,
        securities_type: str = None,
        monitoring: int = None,
        page: int = 1,
        per_page: int = 50,
        fields: Optional[List[str]] = None,
        order_by: str = None,  # 新增：排序字段
        order_direction: str = 'asc'  # 新增：排序方向 ('asc' 或 'desc')
    ) -> List[Dict[str, Any]]:
        """
        多条件组合查询股票，支持字段筛选和排序。

        :param keyword: 在 name 或 ts_code 中模糊匹配
        :param market: 市场（如 'SZ', 'SH'）
        :param concepts: 概念
        :param securities_type: 证券类型
        :param monitoring: 个股监控标记
        :param page: 分页页码
        :param per_page: 每页数量
        :param fields: 指定返回的字段列表。如果为 None，返回所有字段。
        :param order_by: 指定排序的字段名 (例如 'name', 'market')
        :param order_direction: 排序方向，'asc' (升序) 或 'desc' (降序)，默认 'asc'
        :return: 股票字典列表
        """
        query = db_session.query(Stock)

        # --- 1. 应用过滤条件 ---
        if keyword:
            keyword = f"%{keyword}%"
            query = query.filter(or_(
                Stock.name.like(keyword)
            ))
        if market:
            query = query.filter(Stock.market == market)
        if concepts:
            query = query.filter(Stock.concepts == concepts)
        if securities_type:
            query = query.filter(Stock.securities_type == securities_type)
        if monitoring:
            query = query.filter(Stock.monitoring == monitoring)

        # --- 2. 字段选择 ---
        # 注意：如果指定了 order_by，建议确保排序字段包含在查询字段中，或者 SQLAlchemy 能够处理
        if fields:
            column_attributes = [getattr(Stock, field) for field in fields if hasattr(Stock, field)]
            if column_attributes:
                query = query.with_entities(*column_attributes)

        # --- 3. 应用排序逻辑 (新增部分) ---
        if order_by and hasattr(Stock, order_by):
            # 获取排序列属性
            sort_column = getattr(Stock, order_by)

            # 根据方向应用排序
            if order_direction.lower() == 'desc':
                query = query.order_by(desc(sort_column))
            else:
                # 默认为升序
                query = query.order_by(asc(sort_column))
        # 如果没有指定 order_by，或者指定的字段不存在于模型中，则保持默认顺序（通常是主键顺序或数据库物理顺序）

        # --- 4. 分页 ---
        offset = (page - 1) * per_page
        results = query.offset(offset).limit(per_page).all()

        # --- 5. 结果处理 ---
        if fields:
            # 如果指定了字段，需要手动构建字典
            # 注意：这里假设 results 中的元组顺序与 fields 列表顺序一致
            return [dict(zip(fields, result)) for result in results]
        else:
            # 未指定字段，使用原有的 to_dict() 方法
            return [stock.to_dict() for stock in results]

    @staticmethod
    def exists(symbol: str) -> bool:
        """判断股票是否已存在"""
        return db_session.query(Stock).filter_by(symbol=symbol).first() is not None

    @staticmethod
    def count() -> int:
        """返回股票总数"""
        return db_session.query(func.count(Stock.id)).scalar()

    @staticmethod
    def get_industries() -> List[str]:
        """获取所有不重复的行业列表"""
        industries = db_session.query(Stock.industry).distinct().all()
        return [ind[0] for ind in industries if ind[0]]

    @staticmethod
    def get_markets() -> List[str]:
        """获取所有不重复的市场列表"""
        markets = db_session.query(Stock.market).distinct().all()
        return [m[0] for m in markets if m[0]]

    @staticmethod
    def get_securities_types() -> List[str]:
        """获取所有不重复的证券类型列表"""
        types = db_session.query(Stock.securities_type).distinct().all()
        return [t[0] for t in types if t[0]]

    @staticmethod
    def count_stocks_by_industry() -> List[Dict[str, Any]]:
        """按行业统计股票数量"""
        result = db_session.query(Stock.industry, func.count(Stock.id)) \
                          .group_by(Stock.industry).all()
        return [{"industry": industry, "count": count} for industry, count in result if industry]

    # ==================== 写入类方法 ====================

    @staticmethod
    def add_stock(stock_data: Dict[str, Any]) -> bool:
        """添加单条股票记录，主键冲突时静默失败"""
        try:
            stock = Stock(**stock_data)
            db_session.add(stock)
            db_session.commit()
            return True
        except IntegrityError:
            db_session.rollback()
            logger.debug(f"Duplicate ts_code: {stock_data.get('ts_code')}")
            return False
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Failed to add stock: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error in add_stock: {e}")
            return False

    @staticmethod
    def batch_add(stocks_data: List[Dict[str, Any]], ignore_conflicts: bool = True) -> int:
        """
        批量添加股票，返回成功插入的数量。
        :param stocks_data: 股票数据列表
        :param ignore_conflicts: 是否忽略主键冲突（默认 True）
        :return: 成功插入的记录数
        """
        success_count = 0
        for stock_data in stocks_data:
            try:
                stock = Stock(**stock_data)
                db_session.add(stock)
                db_session.flush()  # 不提交，但获取可能的错误
                success_count += 1
            except IntegrityError:
                db_session.rollback()
                if not ignore_conflicts:
                    logger.warning(f"Conflict on ts_code: {stock_data.get('ts_code')}")
                # else: 静默跳过
            except Exception as e:
                db_session.rollback()
                logger.error(f"Error inserting stock {stock_data.get('ts_code')}: {e}")
        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            logger.error(f"Batch commit failed: {e}")
            return 0
        return success_count

    @staticmethod
    def upsert_stock(stock_data: Dict[str, Any]) -> bool:
        """
        插入或更新股票（基于 ts_code）。
        注意：SQLAlchemy ORM 无原生 upsert，此处采用“先查后插/更”策略。
        """
        symbol = stock_data.get('symbol')
        if not symbol:
            logger.error("symbol is required for upsert")
            return False
        existing = db_session.query(Stock).filter_by(symbol=symbol).first()
        try:
            if existing:
                # 更新
                stock_data.pop('symbol', None)  # 避免覆盖主键字段（虽然不影响）
                for key, value in stock_data.items():
                    setattr(existing, key, value)
                existing.last_update = get_today(_format='%Y-%m-%d %H:%M:%S')
            else:
                # 插入
                stock_data['last_update'] = get_today(_format='%Y-%m-%d %H:%M:%S')
                new_stock = Stock(**stock_data)
                db_session.add(new_stock)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Upsert failed for {symbol}: {e}")
            return False

    @staticmethod
    def update_stock_by_id(id: int, update_data: Dict[str, Any]) -> bool:
        """根据 id 更新股票信息"""
        stock = db_session.query(Stock).filter_by(id=id).first()
        if not stock:
            logger.warning(f"Stock with id {id} not found for update")
            return False
        try:
            update_data['last_update'] = get_today(_format='%Y-%m-%d %H:%M:%S')
            for key, value in update_data.items():
                if hasattr(stock, key):
                    setattr(stock, key, value)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Update by ts_code failed: {e}")
            return False

    @staticmethod
    def update_stock_by_ts_code(ts_code: str, update_data: Dict[str, Any]) -> bool:
        """根据 ts_code 更新股票信息"""
        stock = db_session.query(Stock).filter_by(ts_code=ts_code).first()
        if not stock:
            logger.warning(f"Stock with ts_code {ts_code} not found for update")
            return False
        try:
            update_data['last_update'] = get_today(_format='%Y-%m-%d %H:%M:%S')
            for key, value in update_data.items():
                if hasattr(stock, key):
                    setattr(stock, key, value)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Update by ts_code failed: {e}")
            return False

    @staticmethod
    def delete_stock(symbol: str) -> bool:
        """根据 symbol 删除股票"""
        stock = db_session.query(Stock).filter_by(symbol=symbol).first()
        if not stock:
            logger.warning(f"Record with ts_code {symbol} not found for deletion")
            return False
        try:
            db_session.delete(stock)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Deletion failed for {symbol}: {e}")
            return False
