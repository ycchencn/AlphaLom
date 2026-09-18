"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import MarketNews
from models.database import db_session
from sqlalchemy.exc import SQLAlchemyError
from utils.logger import logger


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
    def search(
        keyword=None,
        stock_code=None,
        start_time=None,
        end_time=None,
        page=1,
        page_size=20
    ):
        """
        通用市场新闻搜索接口。

        :param keyword: 在 digest（新闻摘要）中进行模糊搜索（不区分大小写）
        :param stock_code: 在 relations_stocks 中精确匹配股票代码（如 "AAPL"）
        :param start_time: 起始时间（datetime）
        :param end_time: 结束时间（datetime）
        :param page: 页码（从 1 开始）
        :param page_size: 每页数量（最大 100）
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
        if page_size > 1000:
            page_size = 1000

        try:
            query = db_session.query(MarketNews)

            # 时间范围过滤
            if start_time:
                query = query.filter(MarketNews.news_time >= start_time)
            if end_time:
                query = query.filter(MarketNews.news_time <= end_time)

            # 关键字搜索：digest 模糊匹配（忽略大小写）
            if keyword:
                # SQLite / MySQL / PostgreSQL 兼容写法
                query = query.filter(MarketNews.tags.ilike(f"%{keyword}%"))

            # 股票代码匹配：假设 relations_stocks 存储为 JSON 字符串数组，如 ["TSLA", "AAPL"]
            if stock_code:
                # 精确匹配元素：确保是独立的 JSON 字符串项
                pattern = f'%"{stock_code}"%'
                query = query.filter(MarketNews.relations_stocks.like(pattern))

            # 默认取关联新闻
            query = query.filter(MarketNews.relation_level > 0)

            # 排序 + 分页
            total = query.count()
            items = (
                query
                .order_by(MarketNews.news_time.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

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
        if page_size > 100:
            page_size = 100  # 防止过大查询

        try:
            query = db_session.query(MarketNews)

            # 筛选条件
            if bullish_level is not None:
                query = query.filter(MarketNews.bullish_level == bullish_level)
            if relation_level is not None:
                query = query.filter(MarketNews.relation_level == relation_level)
            if start_time:
                query = query.filter(MarketNews.news_time >= start_time)
            if end_time:
                query = query.filter(MarketNews.news_time <= end_time)

            # 注意：JSON 字段的模糊查询依赖数据库方言
            # 以下为通用方案（但 tags_contains 和 stock_code 在 SQLite/MySQL/PG 表现不同）

            # 示例：tags 包含某个字符串（假设 tags 是字符串数组）
            if tags_contains:
                # MySQL: JSON_CONTAINS(tags, '"value"')
                # PostgreSQL: tags ? 'value'
                # 这里使用通用方式：转换为字符串模糊匹配（不推荐用于生产，仅示例）
                # 更佳做法是根据数据库类型写特定查询
                query = query.filter(MarketNews.tags.like(f'%{tags_contains}%'))

            # 示例：relations_stocks 包含某股票代码（简单字符串匹配）
            if stock_code:
                query = query.filter(MarketNews.relations_stocks.like(f'%"{stock_code}"%'))

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
