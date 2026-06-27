"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from models import FactorValue
from models.database import db_session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from utils.common import logger
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal
from utils.common import get_today
from sqlalchemy import func


class FactorValueService:

    @staticmethod
    def create(trade_date: date, ticker: str, factor_name: str, value: float = None, source: str = 'custom') -> \
            Optional[FactorValue]:
        """
        创建一条因子记录。

        :param trade_date: 交易日期（date 对象）
        :param ticker: 股票代码（如 '600519.SH'）
        :param factor_name: 因子名称（如 'pe_ttm'）
        :param value: 因子值（float 或 None）
        :param source: 数据来源
        :return: 成功返回 FactorValue 实例，失败返回 None
        """
        try:
            if isinstance(trade_date, str):
                trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()

            # 将 float 转为 Decimal 以匹配 MySQL DECIMAL(18,6)
            db_value = Decimal(str(round(value, 6))) if value is not None else None

            record = FactorValue(
                trade_date=trade_date,
                ticker=str(ticker),
                factor_name=str(factor_name),
                value=db_value,
                source=source
            )
            db_session.add(record)
            db_session.commit()
            return record
        except IntegrityError as e:
            # 主键或唯一约束冲突：静默处理
            logger.debug(f"Duplicate record ignored in FactorValueService.create: "
                         f"trade_date={trade_date}, ticker={ticker}, factor_name={factor_name}. Error: {e}")
            db_session.rollback()
        except SQLAlchemyError as e:
            logger.error(f"Database error in FactorValueService.create: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in FactorValueService.create: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def bulk_create(records: List[Dict[str, Any]]) -> Optional[int]:
        """
        批量插入因子数据（高效方式）。

        :param records: 列表，每个 dict 包含 keys: trade_date, ticker, factor_name, value, [source]
        :return: 成功插入数量，失败返回 None
        """
        try:
            # objs = []
            for r in records:
                trade_date = r['trade_date']
                if isinstance(trade_date, str):
                    trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
                elif not isinstance(trade_date, date):
                    continue  # 跳过非法日期

                value = r.get('value')
                db_value = Decimal(str(round(value, 6))) if value is not None else None

                obj = FactorValue(
                    trade_date=trade_date,
                    ticker=str(r['ticker']),
                    factor_name=str(r['factor_name']),
                    value=db_value,
                    source=r.get('source', 'custom')
                )
                # objs.append(obj)
                db_session.add(obj)

            db_session.commit()
            return len(records)
        except SQLAlchemyError as e:
            logger.error(f"Database error during bulk create factors: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in FactorValueService.bulk_create: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def get_factor_snapshot(factor_name: str, trade_date: date, page: int = 1, page_size: int = 200) -> dict:
        """
        获取某因子在某交易日的全市场截面快照（分页）。

        :param factor_name: 因子名称
        :param trade_date: 交易日期
        :param page: 页码（从1开始）
        :param page_size: 每页数量（最大500）
        :return: 分页结果字典
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 500:
            page_size = 200

        try:
            query = db_session.query(FactorValue).filter(
                FactorValue.factor_name == factor_name,
                FactorValue.trade_date == trade_date
            )
            total = query.count()
            items = (
                query
                .order_by(FactorValue.ticker)
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [item.to_dict() for item in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": (page * page_size) < total
            }
        except Exception as e:
            logger.error(f"Error fetching factor snapshot for {factor_name} on {trade_date}: {e}")
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "has_more": False
            }

    @staticmethod
    def get_stock_factor_series(ticker: str, factor_name: str, start_date: date = None, end_date: date = None) -> List[
        dict]:
        """
        获取单只股票某个因子的时间序列。

        :param ticker: 股票代码
        :param factor_name: 因子名称
        :param start_date: 开始日期（可选）
        :param end_date: 结束日期（可选，默认今天）
        :return: 因子时间序列列表（按日期升序）
        """
        try:
            query = db_session.query(FactorValue).filter(
                FactorValue.ticker == ticker,
                FactorValue.factor_name == factor_name
            )
            if start_date:
                query = query.filter(FactorValue.trade_date >= start_date)
            if end_date:
                query = query.filter(FactorValue.trade_date <= end_date)

            results = query.order_by(FactorValue.trade_date).all()
            return [r.to_dict() for r in results]
        except Exception as e:
            logger.error(f"Error fetching factor series for {ticker}/{factor_name}: {e}")
            return []

    @staticmethod
    def delete_by_ticker(stock_code: str):
        """
        :param stock_code:
        :return:
        """
        try:
            deleted_count = db_session.query(FactorValue).filter(
                FactorValue.ticker == stock_code,
            ).delete(synchronize_session=False)
            db_session.commit()
            logger.info(f"Deleted {deleted_count} records for symbol: {stock_code}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to delete data for symbol {stock_code}: {e}")
            return False

    @staticmethod
    def delete_by_factor_and_date(factor_name: str, trade_date: date) -> bool:
        """
        删除某因子在某日的所有记录（用于重算覆盖）。
        """
        try:
            count = db_session.query(FactorValue).filter(
                FactorValue.factor_name == factor_name,
                FactorValue.trade_date == trade_date
            ).delete(synchronize_session=False)
            db_session.commit()
            logger.info(f"Deleted {count} records for factor '{factor_name}' on {trade_date}")
            return True
        except SQLAlchemyError as e:
            logger.error(f"DB error deleting factor {factor_name} on {trade_date}: {e}")
            db_session.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error in delete_by_factor_and_date: {e}")
            db_session.rollback()
            return False

    @staticmethod
    def get_latest_factor_date(factor_name: str) -> Optional[date]:
        """
        获取某因子最新计算日期（用于增量更新判断）。
        """
        try:
            latest = (
                db_session.query(FactorValue.trade_date)
                .filter(FactorValue.factor_name == factor_name)
                .order_by(FactorValue.trade_date.desc())
                .first()
            )
            return latest[0] if latest else None
        except Exception as e:
            logger.error(f"Error getting latest date for factor {factor_name}: {e}")
            return None

    @staticmethod
    def get_latest_factor_value(ticker, factor_name: str) -> Any:
        """
        获取某因子最新计算日期（用于增量更新判断）。
        """
        try:
            latest = (
                db_session.query(FactorValue.value)
                .filter(FactorValue.factor_name == factor_name, FactorValue.ticker == ticker)
                .order_by(FactorValue.trade_date.desc())
                .first()
            )
            return latest[0] if latest else ''
        except Exception as e:
            logger.error(f"Error getting latest date for factor {factor_name}: {e}")
            return ''

    @staticmethod
    def get_latest_trading_date(factor_name='cn_trading_date') -> Optional[date]:
        """
        获取最新的交易日数据
        """
        try:
            latest = (
                db_session.query(FactorValue.trade_date, FactorValue.value)
                .filter(FactorValue.factor_name == factor_name, FactorValue.trade_date <= get_today(_format='%Y-%m-%d'),
                        FactorValue.value == '1.0')
                .order_by(FactorValue.trade_date.desc())
                .first()
            )
            return latest[0] if latest else None
        except Exception as e:
            logger.error(f"Error getting latest date for factor {factor_name}: {e}")
            return None

    @staticmethod
    def is_trading_day(factor_name='cn_trading_date') -> Optional[date]:
        """
        判断今天是不是交易日
        """
        return FactorValueService.get_latest_trading_date(factor_name=factor_name).strftime('%Y-%m-%d') == get_today(
            _format='%Y-%m-%d')

    @staticmethod
    def df_to_records(df: pd.DataFrame, factor_name: str, source: str = 'custom') -> List[Dict[str, Any]]:
        """
        将 pandas DataFrame 转换为因子记录列表（便于 bulk_create）。
        要求 df.index 为 trade_date（datetime），columns 为 ticker，值为因子值。

        示例：
            df = pd.DataFrame({
                '600519.SH': [28.1, 28.5],
                '000001.SZ': [6.2, 6.3]
            }, index=[date(2024,12,1), date(2024,12,2)])

        :param df: 因子宽表 DataFrame
        :param factor_name: 因子名称
        :param source: 数据来源
        :return: 记录列表
        """
        records = []
        for trade_date, row in df.iterrows():
            if isinstance(trade_date, pd.Timestamp):
                trade_date = trade_date.date()
            for ticker, value in row.items():
                if pd.notna(value):
                    records.append({
                        'trade_date': trade_date,
                        'ticker': str(ticker),
                        'factor_name': factor_name,
                        'value': float(value),
                        'source': source
                    })
        return records

    @staticmethod
    def get_latest_factors_for_stock(ticker: str) -> Dict[str, Dict[str, Any]]:
        """
        获取某只股票所有因子的最新值及对应交易日期。
        原理：先用子查询求出每个因子在该股票上的最新 trade_date，
              再关联 FactorValue 取出该日期的 value。
        :param ticker: 股票代码，如 '600519.SH'
        :return: 字典，key 为 factor_name，value 为包含 'value' 和 'trade_date' 的字典。
                 示例：{'pe_ttm': {'value': 28.35, 'trade_date': datetime.date(2025,3,27)}, ...}
        """
        try:
            # 子查询：取每个因子的最大 trade_date
            subq = (
                db_session.query(
                    FactorValue.factor_name,
                    func.max(FactorValue.trade_date).label('max_date')
                )
                .filter(FactorValue.ticker == ticker)
                .group_by(FactorValue.factor_name)
                .subquery()
            )
            # 主查询：关联原表，取出完整的 factor_name + value + trade_date
            results = (
                db_session.query(FactorValue)
                .join(
                    subq,
                    (FactorValue.factor_name == subq.c.factor_name) &
                    (FactorValue.trade_date == subq.c.max_date) &
                    (FactorValue.ticker == ticker)  # 冗余条件，确保只取该 ticker
                )
                .filter(FactorValue.ticker == ticker)
                .all()
            )
            # 组装返回结果
            factors = {}
            for r in results:
                factors[r.factor_name] = {
                    'value': float(r.value) if r.value is not None else None,
                    'trade_date': r.trade_date
                }
            return factors
        except Exception as e:
            logger.error(f"Failed to fetch latest factors for stock {ticker}: {e}")
            return {}
