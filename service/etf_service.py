"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models.database import db_session
from models import EtfWatchlist
from utils.data_loader import databull
from utils.logger import logger


class EtfService:
    """ETF 自选（监控）列表的持久化层，对应 etf_watchlist 表。"""

    @staticmethod
    def list_watchlist():
        """读取全部监控 ETF（按加入时间倒序，最新加入的在最前）。"""
        try:
            return db_session.query(EtfWatchlist).order_by(EtfWatchlist.created_at.desc()).all()
        except Exception as e:
            logger.error(f"list_etf_watchlist failed: {e}")
            return []

    @staticmethod
    def add_watchlist(symbol: str, name: str = None) -> EtfWatchlist:
        """
        添加一只 ETF 到监控列表。
        - symbol 为空抛 ValueError；
        - 已存在则直接返回已有记录（幂等）；
        - name 未传时尝试从 databull.get_etf_info 取名称兜底；
        - 唯一约束冲突（极端并发）回滚后回查已有记录。
        """
        symbol = (symbol or '').strip()
        if not symbol:
            raise ValueError('ETF 代码不能为空')

        existing = db_session.query(EtfWatchlist).filter(EtfWatchlist.symbol == symbol).first()
        if existing:
            return existing

        if not name:
            try:
                info = databull.get_etf_info(symbol) or {}
                name = info.get('name') if isinstance(info, dict) else None
            except Exception as e:
                logger.warning(f"get_etf_info(name) failed for {symbol}: {e}")

        item = EtfWatchlist(symbol=symbol, name=name)
        try:
            db_session.add(item)
            db_session.commit()
            db_session.refresh(item)
            return item
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"EtfWatchlist duplicate on insert: {symbol}")
            return db_session.query(EtfWatchlist).filter(EtfWatchlist.symbol == symbol).first()
        except Exception as e:
            db_session.rollback()
            logger.error(f"add_etf_watchlist failed for {symbol}: {e}")
            raise

    @staticmethod
    def delete_watchlist(symbol: str) -> bool:
        """从监控列表移除一只 ETF，不存在返回 False。"""
        symbol = (symbol or '').strip()
        try:
            item = db_session.query(EtfWatchlist).filter(EtfWatchlist.symbol == symbol).first()
            if item:
                db_session.delete(item)
                db_session.commit()
                return True
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"delete_etf_watchlist failed for {symbol}: {e}")
            return False

    @staticmethod
    def search_etf(keyword: str, market: str = 'cn', limit: int = 50):
        """
        在全市场 ETF 目录里按代码/名称模糊搜索（databull get_etf_list）。
        返回 [{symbol, name}] 列表，最多 limit 条。
        """
        keyword = (keyword or '').strip()
        if not keyword:
            return []

        try:
            resp = databull.get_etf_list(market)
        except Exception as e:
            logger.warning(f"get_etf_list failed: {e}")
            return []

        if resp is None:
            return []

        # 接口既可能直接返回数组，也可能返回 {code,data,...} 信封，兼容处理
        if isinstance(resp, list):
            items = resp
        else:
            items = resp.get('data') or resp.get('items') or resp.get('list') or []

        kw = keyword.lower()
        result = []
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get('symbol') or it.get('code') or '')
            nm = str(it.get('name') or '')
            if kw in code.lower() or kw in nm.lower():
                result.append({'symbol': code, 'name': nm})
                if len(result) >= limit:
                    break
        return result
