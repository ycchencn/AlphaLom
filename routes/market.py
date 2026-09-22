"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from app.fastapi_app import api_prefix, json_resp
from service import MarketNewsService
from utils.logger import logger
from utils.data_loader import databull
from fastapi_cache.decorator import cache

market_router = APIRouter(prefix=api_prefix, tags=['市场数据'])

# ⚠️ 同步 `def` 路由会被 Starlette 自动丢进 anyio 线程池（默认 40 线程）；
# 写成 `async def` 则跑在唯一的事件循环线程上，Service 层的同步 pymysql / requests
# 调用会把整个 loop 占死，表现为「一个接口慢，全部接口卡」。详见 README 并发章节。


@market_router.get('/market/sectors')
@cache(expire=3600)
def get_market_sectors(
    sector_type: str = Query('sw1', description="板块类型：sw1-申万一级, sw2-申万二级")
):
    """获取沪深板块涨跌幅数据"""
    market_sector = databull.get_market_sector(sector_type=sector_type)
    return json_resp(market_sector)


@market_router.get('/market/news')
def get_news(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200)
):
    """获取市场新闻"""
    news = MarketNewsService.get_by_time_range(limit=page_size)
    return news


@market_router.get('/market/search_news')
def search_news(
    keyword: str = Query('', description="在新闻摘要（digest）中模糊搜索"),
    stock_code: str = Query(None, description="按关联股票代码精确匹配"),
    start_time: str = Query(None, description="起始时间，ISO8601"),
    end_time: str = Query(None, description="结束时间，ISO8601"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    relation_level_only: bool = Query(
        True,
        description="是否只返回「已关联」新闻（relation_level > 0）。"
                    "个股新闻列表与事件驱动「全部新闻」需传 false，"
                    "否则 relation_level 为 0/NULL 的新闻会被静默丢弃。"
    )
):
    """搜索市场新闻（按时间倒序分页）"""
    try:
        start_dt = None
        end_dt = None
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

        result = MarketNewsService.search(
            keyword=keyword,
            stock_code=stock_code,
            start_time=start_dt,
            end_time=end_dt,
            page=page,
            page_size=page_size,
            relation_level_only=relation_level_only
        )
        return result
    except Exception as e:
        logger.error(f"Unexpected error in search_news: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
