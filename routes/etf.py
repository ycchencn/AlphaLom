"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query
from app.fastapi_app import api_prefix
from utils.data_loader import databull
from service import FactorValueService

etf_router = APIRouter(prefix=api_prefix, tags=['ETF'])


@etf_router.get('/etfs')
async def get_etfs():
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
        {"name": "创新药ETF银华", "symbol": "159992"},
        {"name": "创业板大盘ETF招商", "symbol": "159990"}
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
        etf['ohlc_last'] = databull.get_last_tick(symbol=etf['symbol'], tick_type='etf')
        etf['ohlc_last']['chg_pct'] = (etf['ohlc_last']['lastPrice'] - etf['ohlc_last']['lastClose']) / etf['ohlc_last']['lastClose'] * 100

    return etfs