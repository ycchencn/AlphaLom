"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from models import Stock
from models.database import db_session

from utils.logger import logger
from utils.data_loader import databull
from utils.common import get_today
from typing import List, Optional, Dict, Any
from sqlalchemy import func, and_
from sqlalchemy import or_, asc, desc

import threading
import time

# ==================== 股票目录（搜索联想）缓存与探测 ====================
# 上游 `GET /cn/stocks` 在 OpenAPI 中未定义任何查询参数，传 search/q 会被忽略并原样返回
# 全量列表。因此这里：探测一次上游服务端过滤是否生效；不生效则缓存全量目录到进程内，
# 后续按代码/名称本地过滤（目录属静态参照数据，按需更新而非每日刷新，TTL 取 1h）。
_STOCK_CATALOG_TTL = 3600                       # 目录缓存有效期（秒）
_stock_catalog_cache: Dict[str, Dict[str, Any]] = {}   # market -> {'ts': float, 'items': [...]}
_stock_catalog_lock = threading.Lock()
_stock_server_search_supported: Optional[bool] = None  # None=未探测, True/False=已探测


def _normalize_stock_items(resp) -> List[Dict[str, str]]:
    """把上游清单响应归一化为 [{symbol, name}]（兼容数组与 {code,data} 信封两种写法）。"""
    if resp is None:
        return []
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
    return result


def _probe_stock_server_search(market: str = 'cn') -> bool:
    """
    探测上游服务端关键词过滤是否真的生效，结果缓存在进程内（只探一次）。

    判据：用一个必然搜不到的关键字调用；若上游**确实**按关键字过滤，应返回空列表；
    若原样返回全量列表，说明该参数被忽略。响应无效（请求异常 / 返回 None）时保守判为
    「不支持」，避免退化成每次按键都向上游拉一份全量清单。
    """
    global _stock_server_search_supported
    if _stock_server_search_supported is not None:
        return _stock_server_search_supported
    try:
        resp = databull.get_stock_list(market=market, search='__alphalom_no_such_keyword__')
        probe = _normalize_stock_items(resp)
        _stock_server_search_supported = bool(resp is not None and not probe)
    except Exception as e:
        logger.warning(f"probe stock server-side search failed: {e}")
        _stock_server_search_supported = False
    logger.info(f"stock server-side search supported = {_stock_server_search_supported}")
    return _stock_server_search_supported


def _get_stock_catalog(market: str = 'cn') -> List[Dict[str, str]]:
    """获取（并缓存）全市场股票目录，供本地过滤使用。拉取失败时沿用旧缓存。"""
    cached = _stock_catalog_cache.get(market)
    if cached and time.time() - cached['ts'] < _STOCK_CATALOG_TTL:
        return cached['items']

    with _stock_catalog_lock:
        cached = _stock_catalog_cache.get(market)
        if cached and time.time() - cached['ts'] < _STOCK_CATALOG_TTL:
            return cached['items']
        try:
            items = _normalize_stock_items(databull.get_stock_list(market=market))
        except Exception as e:
            logger.warning(f"get_stock_list failed: {e}")
            items = []
        if items:
            _stock_catalog_cache[market] = {'ts': time.time(), 'items': items}
            return items
        return cached['items'] if cached else []


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

        :param keyword: 在 name 或 symbol 中模糊匹配
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
                Stock.name.like(keyword),
                Stock.symbol.like(keyword)
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
    def search_stock_catalog(keyword: str, market: str = 'cn', limit: int = 50) -> List[Dict[str, Any]]:
        """
        按代码/名称搜索全市场股票目录，返回 [{symbol, name}]，最多 limit 条。
        用于「添加个股监控」弹窗的搜索联想。

        实现说明：上游 `GET /cn/stocks` 的 OpenAPI 定义里**没有任何查询参数**，实测传
        search/q 会被忽略并原样返回全量列表（keyword=600519 与 keyword=平安 返回同一份数据）。
        所以这里不直接假设上游行为：
          1) 若探测到上游服务端过滤真的生效 → 直接用上游结果（省掉本地全量过滤）；
          2) 否则退化为「进程内缓存全量目录 + 本地按代码/名称过滤」，
             避免每次按键都向上游拉一份全量清单。
        """
        keyword = (keyword or '').strip()
        if not keyword:
            return []
        kw = keyword.lower()

        candidates = []
        if _stock_server_search_supported is not False and _probe_stock_server_search(market):
            try:
                raw = _normalize_stock_items(databull.get_stock_list(market=market, search=keyword))
                candidates = [it for it in raw
                              if kw in it['symbol'].lower() or kw in it['name'].lower()]
            except Exception as e:
                logger.warning(f"get_stock_list(search={keyword}) failed: {e}")

        if not candidates:
            # 上游不过滤（或过滤无结果）→ 用缓存的全量目录做本地匹配
            catalog = _get_stock_catalog(market)
            candidates = [it for it in catalog
                          if kw in it['symbol'].lower() or kw in it['name'].lower()]

        # 相关度排序：代码完全一致 > 代码前缀命中 > 代码包含 > 其余（名称命中）
        def _rank(item):
            code = item['symbol'].lower()
            if code == kw:
                return 0
            if code.startswith(kw):
                return 1
            if kw in code:
                return 2
            return 3

        candidates.sort(key=_rank)
        return candidates[:limit]

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
            logger.debug(f"Duplicate symbol: {stock_data.get('symbol')}")
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
                    logger.warning(f"Conflict on symbol: {stock_data.get('symbol')}")
                # else: 静默跳过
            except Exception as e:
                db_session.rollback()
                logger.error(f"Error inserting stock {stock_data.get('symbol')}: {e}")
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
        插入或更新股票（基于 symbol）。
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
    def company_profile_fields(symbol: str, market: str = 'cn') -> Dict[str, Any]:
        """拉取公司概况并压平成 stocks 表的行业 / 地域字段。

        原先每个调用点都要自己写 `resp = databull.get_company_profile(...)` +
        `profile = resp.get('data')` 再逐个 `.get()`，这里统一收口，
        并把原始 profile 原样放进 `company_profile` 字段留档。

        Args:
            symbol: 股票代码
            market: 市场，默认 cn

        Returns:
            形如 {'industry', 'province', 'city', 'district', 'company_profile'} 的字典。
            上游无数据时前四项为 None、`company_profile` 为 {}（调用方不必再判空）
        """
        # ⚠️ SDK 的 get_company_profile 返回 {code, data} 信封（旧本地客户端已解包成 data 本身），
        # 必须自己取内层 data —— 否则 industry/province 等全部取到 None 且不报错。
        resp = databull.get_company_profile(symbol, market)
        profile = resp.get('data') if isinstance(resp, dict) else None
        # 上游无此标的时 data 为空，异常结构也一并按空处理，避免下游 .get() 报错
        if not isinstance(profile, dict):
            profile = {}
        return {
            'industry': profile.get('industry'),
            'province': profile.get('province'),
            'city': profile.get('city'),
            'district': profile.get('district'),
            'company_profile': profile,
        }

    @staticmethod
    def ensure_stock_from_api(
        symbol: str,
        market: str = 'cn',
        securities_type: str = 'stock',
        monitoring: int = 1,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """个股不在 stocks 表时，从 databull 补全基础信息后入库（幂等）。

        「不在库 → 查 API → upsert」这段逻辑原先在 routes/stock.py、
        job/job_stock_analysis.py、job/private/stock_pool_overide.py 里各抄了一份，
        且已经漂移（只有 routes 那份带公司概况）。这里统一成一份：
        名称取 get_stock_info，行业 / 省市 / 公司概况取 get_company_profile。

        注意：本方法是**幂等**的，已在库则直接返回 False、不做任何修改。
        调用方若还要区分「已存在时更新调用方自己的字段」，可先判 StockService.exists。

        Args:
            symbol: 股票代码
            market: 市场，默认 cn（info 与 profile 两个接口共用）
            securities_type: 证券类型，默认 stock
            monitoring: 是否纳入监控，默认 1
            extra: 额外写入的字段（如 {'monitor_by': 'a500_20260920'}），同名键覆盖上面的默认值

        Returns:
            True = 原先不在库且写入成功；False = 已在库（未做任何修改）或写入失败
        """
        if StockService.exists(symbol):
            return False

        stock_api = databull.get_stock_info(symbol, market=market)
        name = stock_api.get('name') if isinstance(stock_api, dict) else None

        record: Dict[str, Any] = {
            'symbol': symbol,
            'name': name,
            'market': market,
            'securities_type': securities_type,
            'monitoring': monitoring,
        }
        record.update(StockService.company_profile_fields(symbol, market))
        if extra:
            record.update(extra)
        return StockService.upsert_stock(record)

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
            logger.error(f"Update by id failed: {e}")
            return False

    @staticmethod
    def delete_stock(symbol: str) -> bool:
        """根据 symbol 删除股票"""
        stock = db_session.query(Stock).filter_by(symbol=symbol).first()
        if not stock:
            logger.warning(f"Record with symbol {symbol} not found for deletion")
            return False
        try:
            db_session.delete(stock)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"Deletion failed for {symbol}: {e}")
            return False
