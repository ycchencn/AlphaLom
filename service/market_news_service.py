"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import MarketNews
from models.database import db_session
from sqlalchemy.exc import SQLAlchemyError
from utils.logger import logger
# MARK: - 常量 -------------------------------------------------------------
# 分页上限：路由层 /market/search_news 的 page_size 校验是 le=200，
# 这里作为 Service 层兜底保持一致（原 search=1000 / get_list=100 两个值互相打架）。
MAX_PAGE_SIZE = 200

# MARK: - LIKE 通配符转义 ----------------------------------------------------
# keyword / stock_code 都会拼进 LIKE 模式串，若不转义，用户输入的 '%' 会变成
# 通配符、'_' 会变成单字符通配（搜 'a_b' 会命中 'axb'），既是结果污染也是注入面。
# MySQL 的 LIKE 默认转义符是反斜杠，故统一转义 \ % _ 三者。
_LIKE_ESCAPE_TABLE = str.maketrans({
    '\\': '\\\\',
    '%': '\\%',
    '_': '\\_',
})


def _escape_like(value):
    """转义 LIKE 模式串中的通配符，返回可安全拼进 %...% 的片段。"""
    if value is None:
        return ''
    return str(value).translate(_LIKE_ESCAPE_TABLE)


class MarketNewsService:
    @staticmethod
    def create(digest, tags=None, relation_level=None, bullish_level=False, relations_stocks=None,
               news_time=None, news_type=None, news_md5=None, sources=None, url=None):
        """
        创建一条新的市场新闻记录。
        :param digest: 新闻摘要（必填）
        :param tags: 标签列表，默认为空列表
        :param relation_level: 关联程度等级
        :param bullish_level: 是否看涨，默认 False
        :param relations_stocks: 关联股票列表，默认为空列表
        :param news_time: 新闻发布时间（建议传入 datetime 对象）
        :param news_type: 新闻类型
        :param news_md5: 新闻唯一哈希值
        :param sources: 新闻来源
        :param url: 新闻url
        :return: 成功返回 MarketNews 实例，失败返回 None
        """
        try:
            # 处理默认可变参数
            if tags is None:
                tags = []
            if relations_stocks is None:
                relations_stocks = []

            new_news = MarketNews(
                digest=digest,
                tags=tags,
                relation_level=relation_level,
                bullish_level=bullish_level,
                relations_stocks=relations_stocks,
                news_time=news_time,
                news_type=news_type,
                news_md5=news_md5,
                sources=sources,
                url=url
            )
            db_session.add(new_news)
            db_session.commit()
            return new_news
        except SQLAlchemyError as e:
            logger.error(f"Database error occurred while creating market news: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in MarketNewsService.create: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def get_all():
        """
        获取所有市场新闻记录。
        :return: MarketNews 对象列表
        """
        try:
            return db_session.query(MarketNews).all()
        except Exception as e:
            logger.error(f"Error fetching all market news: {e}")
            return []

    @staticmethod
    def get_by_id(news_id):
        try:
            return db_session.query(MarketNews).get(news_id)
        except Exception as e:
            logger.error(f"Error fetching market news by ID {news_id}: {e}")
            return None

    @staticmethod
    def get_by_id_dict(news_id):
        """
        根据 ID 获取单条市场新闻的字典形式。
        :param news_id: 新闻 ID
        :return: dict 或 None
        """
        news = MarketNewsService.get_by_id(news_id)
        return news.to_dict() if news else None

    @staticmethod
    def get_by_md5(news_md5):
        if not isinstance(news_md5, str) or len(news_md5) != 32:
            logger.warning(f"Invalid MD5 format: {news_md5}")
            return None
        try:
            return db_session.query(MarketNews).filter(MarketNews.news_md5 == news_md5).first()
        except Exception as e:
            logger.error(f"Error fetching market news by MD5 {news_md5}: {e}")
            return None

    @staticmethod
    def get_by_time_range(start_time=None, end_time=None, stock_code=None, limit=100):
        """
        按时间范围查询新闻（按 news_time 倒序），可选按关联股票代码过滤。
        :param start_time: 起始时间（datetime）
        :param end_time: 结束时间（datetime）
        :param stock_code: 股票代码（字符串），用于在 relations_stocks 中模糊匹配
        :param limit: 最大返回数量，默认 100
        :return: list of dict (news records)
        """
        try:
            query = db_session.query(MarketNews)

            if start_time:
                query = query.filter(MarketNews.news_time >= start_time)
            if end_time:
                query = query.filter(MarketNews.news_time <= end_time)

            # 默认取关联新闻
            query = query.filter(MarketNews.relation_level > 0)

            # 模糊匹配 stock_code 在 relations_stocks（假设存储为 JSON 字符串）
            if stock_code:
                # 匹配形如 ["AAPL", "MSFT"] 的 JSON 数组中的元素
                # 使用 %"%stock_code"% 防止部分匹配（如 "APPL" 匹配到 "AAPL"）
                # 更安全的方式是确保格式为 ["...", "..."]
                pattern = f'%"{stock_code}"%'
                query = query.filter(MarketNews.relations_stocks.like(pattern))

            news = query.order_by(MarketNews.news_time.desc()).limit(limit).all()
            return [new.to_dict() for new in news]
        except Exception as e:
            logger.error(f"Error fetching market news by time range: {e}")
            return []

    @staticmethod
    def _build_query(
        keyword=None,
        stock_code=None,
        start_time=None,
        end_time=None,
        relation_level_only=True
    ):
        """
        构造市场新闻的筛选 Query（不含排序 / 分页），供 search / get_list 复用。

        :param keyword: 在 **digest（新闻摘要）** 中模糊搜索，不区分大小写；
                        通配符已转义，用户输入的 % / _ 按字面匹配。
        :param stock_code: 在 relations_stocks 中精确匹配股票代码（如 "600519"）
        :param start_time: 起始时间（datetime）
        :param end_time: 结束时间（datetime）
        :param relation_level_only: 是否只取「已关联」新闻（relation_level > 0）。
                        默认 True 保持历史行为；调用方要「全部新闻」时传 False。
        :return: SQLAlchemy Query
        """
        query = db_session.query(MarketNews)

        # 时间范围过滤
        if start_time:
            query = query.filter(MarketNews.news_time >= start_time)
        if end_time:
            query = query.filter(MarketNews.news_time <= end_time)

        # 关键字搜索：digest 模糊匹配（忽略大小写）
        # ⚠️ 这里过滤的是 digest。历史实现写的是 tags.ilike(...)，但 docstring 声称是
        #    digest —— JSON 列的 LIKE 语义依赖方言、无法走索引，且 tags 里只存
        #    「美联储」这类短词，用户按摘要用词搜索是搜不到的。
        if keyword:
            query = query.filter(MarketNews.digest.ilike(f"%{_escape_like(keyword)}%"))

        # 股票代码匹配：relations_stocks 以 JSON 数组存储，如 [{"code": "600519", "name": "贵州茅台"}]
        if stock_code:
            # 精确匹配 JSON 字符串项，避免 "0519" 命中 "600519"
            pattern = f'%"{_escape_like(stock_code)}"%'
            query = query.filter(MarketNews.relations_stocks.like(pattern))

        # 是否只取已关联新闻（历史默认行为）
        if relation_level_only:
            query = query.filter(MarketNews.relation_level > 0)

        return query

    @staticmethod
    def search(
        keyword=None,
        stock_code=None,
        start_time=None,
        end_time=None,
        page=1,
        page_size=20,
        relation_level_only=True
    ):
        """
        通用市场新闻搜索接口。

        :param keyword: 在 **digest（新闻摘要）** 中进行模糊搜索（不区分大小写）
        :param stock_code: 在 relations_stocks 中精确匹配股票代码（如 "600519"）
        :param start_time: 起始时间（datetime）
        :param end_time: 结束时间（datetime）
        :param page: 页码（从 1 开始）
        :param page_size: 每页数量（上限 MAX_PAGE_SIZE，与路由层校验一致）
        :param relation_level_only: 是否只取 relation_level > 0 的新闻。
                        **默认 True 仅为兼容历史行为**；个股新闻、事件驱动「全部新闻」
                        等场景应显式传 False，否则 relation_level 为 0 / NULL 的新闻
                        会被静默丢弃。
        :return: dict {
            'items': [news.to_dict(), ...],
            'total': int,
            'page': int,
            'page_size': int,
            'has_more': bool
        }
        """
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > MAX_PAGE_SIZE:
            page_size = MAX_PAGE_SIZE

        try:
            query = MarketNewsService._build_query(
                keyword=keyword,
                stock_code=stock_code,
                start_time=start_time,
                end_time=end_time,
                relation_level_only=relation_level_only
            )

            # 排序 + 分页。
            # 多取 1 条来判定 has_more，省掉一次独立的 COUNT 全表统计
            # （原实现对同一条件先 count() 再取 items，是两次独立往返）。
            rows = (
                query
                .order_by(MarketNews.news_time.desc())
                .offset((page - 1) * page_size)
                .limit(page_size + 1)
                .all()
            )

            has_more = len(rows) > page_size
            item_dicts = [item.to_dict() for item in rows[:page_size]]

            return {
                "items": item_dicts,
                # ⚠️ 这不是全表精确总数，而是「本页返回条数」下界。
                #    要精确总数必须额外一次 COUNT；调用方若需要它（例如分页器显示
                #    总页数），请改用 get_list()，不要拿这个值算 total_pages。
                "total": len(item_dicts),
                "page": page,
                "page_size": page_size,
                "has_more": has_more
            }

        except Exception as e:
            logger.error(f"Error in MarketNewsService.search: {e}")
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "has_more": False
            }

    @staticmethod
    def update(news_id, **kwargs):
        """
        更新指定 ID 的市场新闻记录。
        :param news_id: 要更新的新闻 ID
        :param kwargs: 可更新字段：digest, tags, relation_level, bullish_level, relations_stocks, news_time
        :return: 更新后的 MarketNews 对象或 None
        """
        news = db_session.query(MarketNews).get(news_id)
        if not news:
            return None

        # 安全更新：只允许更新模型中存在的字段
        for key, value in kwargs.items():
            if hasattr(news, key):
                setattr(news, key, value)

        try:
            db_session.commit()
            return news
        except SQLAlchemyError as e:
            logger.error(f"Database error during update of market news {news_id}: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in MarketNewsService.update: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def delete(news_id):
        """
        删除指定 ID 的市场新闻。
        :param news_id: 要删除的新闻 ID
        :return: True 成功，False 失败
        """
        news = db_session.query(MarketNews).get(news_id)
        if not news:
            return False

        try:
            db_session.delete(news)
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error during deletion of market news {news_id}: {e}")
            db_session.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error in MarketNewsService.delete: {e}")
            db_session.rollback()
            return False

    @staticmethod
    def get_list(
        page=1,
        page_size=20,
        bullish_level=None,
        relation_level=None,
        start_time=None,
        end_time=None,
        tags_contains=None,
        stock_code=None
    ):
        """
        获取市场新闻列表，支持分页和多条件筛选。

        :param page: 页码（从 1 开始）
        :param page_size: 每页数量（建议 <= 100）
        :param bullish_level: 看涨级别（整数，如 0/1）
        :param relation_level: 关联程度等级（整数）
        :param start_time: 起始时间（datetime），包含
        :param end_time: 结束时间（datetime），包含
        :param tags_contains: 标签中是否包含某字符串（模糊匹配，仅适用于 JSON 中有字符串标签）
        :param stock_code: 是否关联某股票代码（在 relations_stocks.code 中查找）

        :return: dict {
            'items': [news.to_dict(), ...],
            'total': int,
            'page': int,
            'page_size': int,
            'has_more': bool
        }
        """
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > MAX_PAGE_SIZE:
            page_size = MAX_PAGE_SIZE  # 防止过大查询

        try:
            # 公开筛选条件复用 _build_query（relation_level_only=False）：
            # 是否「只取关联新闻」由 relation_level 参数显式控制，不在这里隐式过滤。
            query = MarketNewsService._build_query(
                keyword=None,
                stock_code=stock_code,
                start_time=start_time,
                end_time=end_time,
                relation_level_only=False
            )

            if bullish_level is not None:
                query = query.filter(MarketNews.bullish_level == bullish_level)
            if relation_level is not None:
                query = query.filter(MarketNews.relation_level == relation_level)

            # tags 是 JSON 列，跨方言没有统一的「包含某字符串」写法：
            #   MySQL 8 → JSON_CONTAINS(tags, JSON_QUOTE(:v))
            #   PostgreSQL → tags ? :v
            # 此处沿用通用（但无法走索引）的字符串模糊匹配，并转义通配符。
            if tags_contains:
                query = query.filter(MarketNews.tags.like(f'%{_escape_like(tags_contains)}%'))

            # 总数（用于分页）
            total = query.count()

            # 排序 + 分页
            items = (
                query
                .order_by(MarketNews.news_time.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            # 转为字典
            item_dicts = [item.to_dict() for item in items] if items else []

            has_more = (page * page_size) < total

            return {
                "items": item_dicts,
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": has_more
            }

        except Exception as e:
            logger.error(f"Error in MarketNewsService.get_list: {e}")
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "has_more": False
            }
