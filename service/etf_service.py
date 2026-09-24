"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models.database import db_session
from models import EtfWatchlist

from utils.logger import logger
from utils.data_loader import databull


class EtfService:
    """ETF 自选（监控）列表的持久化层，对应 etf_watchlist 表。

    多用户：这张表是**用户私有**的，读写都要带 user_id。
    ⚠️ 唯一约束是 (user_id, symbol)，所以「加过没有」的判断也必须限定在同一个用户内 ——
    只按 symbol 查会把别的用户的记录当成本用户已有，导致「加不上也报成功」。
    """

    @staticmethod
    def list_watchlist(user_id):
        """
        读取**某个用户**的监控 ETF（按加入时间倒序，最新加入的在最前）。

        ⚠️ user_id 必传，None 直接抛 ValueError：用户私有数据没有「不传就取全部」
        这种合理语义，而静默返回全部用户的清单正是多用户下最危险的默认行为。
        定时任务要拿「全站并集」请用 `list_all_symbols()`。
        """
        if user_id is None:
            raise ValueError('list_watchlist 必须指定 user_id（任务侧请用 list_all_symbols）')
        try:
            return db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == int(user_id)
            ).order_by(EtfWatchlist.created_at.desc()).all()
        except Exception as e:
            logger.error(f"list_etf_watchlist failed: {e}")
            return []

    @staticmethod
    def list_all_symbols():
        """
        **全部用户**自选的去重并集（按代码排序）。

        给日更任务用：它们没有用户上下文（也不该有），而恐贪/因子都是「按标的算」的
        公共数据 —— 两个用户都选了同一只 ETF 时只应算一次，所以这里 DISTINCT。
        """
        try:
            rows = db_session.query(EtfWatchlist.symbol).distinct().all()
            return sorted({r[0] for r in rows if r[0]})
        except Exception as e:
            logger.error(f"list_all_etf_symbols failed: {e}")
            return []

    @staticmethod
    def add_watchlist(user_id, symbol: str, name: str = None) -> EtfWatchlist:
        """
        把一只 ETF 加入**指定用户**的监控列表。
        - user_id 为空抛 ValueError（宁可报错也不要插一条无主数据 —— 那条数据谁都看不见）；
        - symbol 为空抛 ValueError；
        - 该用户已加过则直接返回已有记录（幂等）；
        - name 未传时尝试从 databull.get_etf_info 取名称兜底；
        - 唯一约束冲突（极端并发）回滚后回查已有记录。
        """
        if user_id is None:
            raise ValueError('add_watchlist 必须指定 user_id')
        user_id = int(user_id)

        symbol = (symbol or '').strip()
        if not symbol:
            raise ValueError('ETF 代码不能为空')

        # ⚠️ 幂等查询必须同时限定 user_id：只按 symbol 查会把别的用户已加的记录
        # 当成本用户已有，直接返回它 —— 用户以为加上了，实际自己的清单里没有。
        existing = db_session.query(EtfWatchlist).filter(
            EtfWatchlist.user_id == user_id,
            EtfWatchlist.symbol == symbol,
        ).first()
        if existing:
            return existing

        if not name:
            try:
                info = databull.get_etf_info(symbol) or {}
                name = info.get('name') if isinstance(info, dict) else None
            except Exception as e:
                logger.warning(f"get_etf_info(name) failed for {symbol}: {e}")

        item = EtfWatchlist(user_id=user_id, symbol=symbol, name=name)
        try:
            db_session.add(item)
            db_session.commit()
            db_session.refresh(item)
            return item
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"EtfWatchlist duplicate on insert: user={user_id} {symbol}")
            return db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == user_id,
                EtfWatchlist.symbol == symbol,
            ).first()
        except Exception as e:
            db_session.rollback()
            logger.error(f"add_etf_watchlist failed for {symbol}: {e}")
            raise

    @staticmethod
    def delete_watchlist(user_id, symbol: str) -> bool:
        """
        从**指定用户**的监控列表移除一只 ETF。该用户没加过返回 False。

        ⚠️ 删除必须限定 user_id：否则 A 的删除动作会把 B 清单里的同一只 ETF 删掉，
        而且看起来「删成功了」，B 那边只会发现自己的自选莫名少了一行。
        """
        if user_id is None:
            raise ValueError('delete_watchlist 必须指定 user_id')
        symbol = (symbol or '').strip()
        try:
            item = db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == int(user_id),
                EtfWatchlist.symbol == symbol,
            ).first()
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
        按代码/名称搜索全市场 ETF 目录。

        走 databull get_etf_list 的**服务端 search 过滤**（不再全量拉取后本地过滤），
        因此关键字直接交给上游匹配，支持代码/名称模糊搜索。
        返回 [{symbol, name}]，最多 limit 条。
        """
        keyword = (keyword or '').strip()
        if not keyword:
            return []

        try:
            resp = databull.get_etf_list(market=market, search=keyword)
        except Exception as e:
            logger.warning(f"get_etf_list(search={keyword}) failed: {e}")
            return []

        if resp is None:
            return []

        # 接口既可能直接返回数组，也可能返回 {code,data,...} 信封，兼容处理
        if isinstance(resp, list):
            items = resp
        else:
            items = resp.get('data') or resp.get('items') or resp.get('list') or []

        result, seen = [], set()
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get('symbol') or it.get('code') or '').strip()
            if not code or code in seen:
                continue
            seen.add(code)
            result.append({'symbol': code, 'name': str(it.get('name') or '').strip()})

        # 相关度排序：代码完全一致 > 代码前缀命中 > 代码包含 > 其余（名称命中）
        kw = keyword.lower()

        def _rank(item):
            code = item['symbol'].lower()
            if code == kw:
                return 0
            if code.startswith(kw):
                return 1
            if kw in code:
                return 2
            return 3

        result.sort(key=_rank)
        return result[:limit]
