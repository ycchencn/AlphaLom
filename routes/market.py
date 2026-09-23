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
    market_sector = databull.get_sector_data(sector_type=sector_type)
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
    keyword: str = Query(''),
    stock_code: str = Query(None),
    start_time: str = Query(None),
    end_time: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200)
):
    """搜索新闻"""
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
            page_size=page_size
        )
        return result
    except Exception as e:
        logger.error(f"Unexpected error in search_news: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")