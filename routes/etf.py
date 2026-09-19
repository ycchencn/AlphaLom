"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query
from app.fastapi_app import api_prefix
from utils.data_loader import databull
from service import FactorValueService
from fastapi_cache.decorator import cache

etf_router = APIRouter(prefix=api_prefix, tags=['ETF'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；写成 `async def`
# 会让下面循环里的同步 databull HTTP 调用直接占死事件循环 → 全站一起卡。


@etf_router.get('/etfs')
@cache(expire=3600)
def get_etfs():
    """
    获取ETF监控列表
    """
    etfs = [
        {"name": "中证100ETF易方达", "symbol": "159901"},
        {"name": "沪深300ETF", "symbol": "159919"},
        {"name": "家电ETF国泰", "symbol": "159996"},
        {"name": "芯片ETF华夏", "symbol": "159995"},
        {"name": "通信ETF银华", "symbol": "159994"},
        {"name": "证券ETF鹏华", "symbol": "159993"},
        {"name": "创新药ETF银华", "symbol": "159992"}
    ]
    for etf in etfs:
        etf['52week_low'] = FactorValueService.get_latest_factor_value(
            ticker=etf['symbol'],
            factor_name='52week_low'
        )
        etf['52week_high'] = FactorValueService.get_latest_factor_value(
            ticker=etf['symbol'],
            factor_name='52week_high'
        )
        ohlc = databull.get_last_tick(symbol=etf['symbol'], tick_type='etf') or {}
        # 远端偶发返回空结果（实测 159990 就会返回 {}）。原实现直接 ohlc['lastPrice'] 下标取值，
        # 一旦为空就 KeyError，导致**整个 ETF 列表接口 500**、全页打不开。
        # 前端对 ohlc_last 的各字段都有 `!= null` 兜底（显示 '--'），所以这里只需保证
        # ohlc_last 始终是 dict、拿不到数据时不写 chg_pct。
        last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
        if last_price is not None and last_close:
            ohlc['chg_pct'] = (last_price - last_close) / last_close * 100
        etf['ohlc_last'] = ohlc

    return etfs