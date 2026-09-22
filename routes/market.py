"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import datetime, timedelta
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


@market_router.get('/market/fear_greed')
@cache(expire=3600)
def get_market_fear_greed(
    index_code: str = Query(
        '000001',
        description="指数代码：000001-上证指数, 000300-沪深300, 399006-创业板指, 000905-中证500"
    ),
    days: int = Query(365, ge=1, le=1000, description="向前取多少个自然日"),
):
    """获取指数级「恐惧贪婪指数」日线（沪深大盘监控页）

    数据源为上游 `/cn/market/fear_greed`，**直连不落库**，原因见 README 说明：

    本地 `stocks_fear_greed` 表虽然字段与上游完全一致（trade_date / index_code /
    close / fear_greed / vol_score / mom_score），但里面存的是**个股**的恐惧贪婪
    （由 job_update_stock_greedy_data 本地计算写入），`index_code` 列实际放的是
    股票代码 —— 例如 `000001` 是平安银行（close≈11.73 元）而不是上证指数
    （close≈3949 点）。若把上游指数数据写进同一张表，主键 (trade_date, index_code)
    会与个股数据直接冲突并**覆盖掉平安银行的历史**。故指数维度单独走上游。

    字段说明：
    - fear_greed  综合指数 0~100（越高越贪婪）
    - vol_score   波动率分项
    - mom_score   动量分项
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')

    df = databull.get_market_fear_greed(
        index_code=index_code, start_date=start_date, end_date=end_date
    )
    if df is None or df.empty:
        logger.warning(f"指数 {index_code} 恐惧贪婪数据为空")
        return []

    # get_market_fear_greed 内部走 _to_dataframe(默认 date_col="date")，而上游返回的
    # 日期列名是 `trade_date` —— 列名对不上，所以**不会**被设成索引，
    # trade_date 仍是一个普通列（这也是下面能直接取 row['trade_date'] 的原因）。
    # reset_index() 只在恰好有名为 index 的列时才可能撞名，这里保留它是为了
    # 万一将来上游/封装对齐了列名也不会崩。排序保证前端折线是从旧到新。
    df = df.reset_index().sort_values('trade_date')
    records = []
    for row in df.to_dict('records'):
        trade_date = row.get('trade_date')
        records.append({
            'trade_date': trade_date.strftime('%Y-%m-%d') if hasattr(trade_date, 'strftime') else str(trade_date),
            'index_code': row.get('index_code') or index_code,
            'close': row.get('close'),
            'fear_greed': row.get('fear_greed'),
            'vol_score': row.get('vol_score'),
            'mom_score': row.get('mom_score'),
        })
    return records


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
