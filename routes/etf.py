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
from utils.common import get_today, get_date_by_n
from utils.logger import logger
import pandas as pd

etf_router = APIRouter(prefix=api_prefix, tags=['ETF'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；写成 `async def`
# 会让下面循环里的同步 databull HTTP 调用直接占死事件循环 → 全站一起卡。

# ETF 监控清单（静态）。既用于列表接口，也作为详情页名称解析的兜底（上游 get_etf_list 在 dev 返回空）。
ETF_MONITOR_LIST = [
    {"name": "中证100ETF易方达", "symbol": "159901"},
    {"name": "沪深300ETF", "symbol": "159919"},
    {"name": "家电ETF国泰", "symbol": "159996"},
    {"name": "芯片ETF华夏", "symbol": "159995"},
    {"name": "通信ETF银华", "symbol": "159994"},
    {"name": "证券ETF鹏华", "symbol": "159993"},
    {"name": "创新药ETF银华", "symbol": "159992"}
]
ETF_NAME_MAP = {str(e["symbol"]): e.get("name") for e in ETF_MONITOR_LIST}


@etf_router.get('/etfs')
@cache(expire=3600)
def get_etfs():
    """
    获取ETF监控列表
    """
    etfs = [dict(e) for e in ETF_MONITOR_LIST]
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


@etf_router.get('/etf/{symbol}')
@cache(expire=3600)
def get_etf_detail(symbol: str):
    """
    获取ETF详情：基础信息 + 实时行情 + 52周高低
    """
    # 名称优先从监控清单解析（确定性、无网络依赖）；其余回退为代码本身
    name = ETF_NAME_MAP.get(str(symbol), symbol)

    # 实时行情（get_last_tick 偶发返回 None，与列表接口一致做兜底处理）
    ohlc = databull.get_last_tick(symbol=symbol, tick_type='etf') or {}
    last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
    if last_price is not None and last_close:
        ohlc['chg_pct'] = (last_price - last_close) / last_close * 100

    return {
        'symbol': symbol,
        'name': name,
        'ohlc_last': ohlc,
        '52week_low': FactorValueService.get_latest_factor_value(ticker=symbol, factor_name='52week_low'),
        '52week_high': FactorValueService.get_latest_factor_value(ticker=symbol, factor_name='52week_high'),
    }


@etf_router.get('/etf_info/{symbol}')
@cache(expire=3600)
def get_etf_info(symbol: str):
    """
    获取ETF基本资料：交易所、单位净值、每申赎单位净值、现金差额、申赎单位、类型、
    申赎开关、交易日等。上游无数据（404/未生成申赎清单）时返回空 dict，前端优雅降级。
    """
    try:
        data = databull.get_etf_info(symbol) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f'get_etf_info failed for {symbol}: {e}')
        return {}


@etf_router.get('/etf_history/{symbol}')
@cache(expire=3600)
def get_etf_history(
    symbol: str,
    period: str = Query('d'),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """
    获取ETF历史行情（日线），timestamp(ms) 转为 date 字符串返回
    """
    if start_date is None:
        start_date = get_date_by_n(-365)
    if end_date is None:
        end_date = get_today()

    df = databull.get_etf_history(symbol, start_date, end_date)
    if df is None or getattr(df, 'empty', True):
        return []

    df = df.copy()
    # 上游时间戳为毫秒级 epoch，转成 YYYY-MM-DD 便于前端展示
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d')
    keep_cols = [c for c in ['date', 'open', 'close', 'high', 'low', 'volume', 'chg_pct'] if c in df.columns]
    return df[keep_cols].to_dict(orient='records')


@etf_router.get('/etf_composition/{symbol}')
@cache(expire=3600)
def get_etf_composition(symbol: str):
    """
    获取ETF成分股构成（上游不支持时返回空列表，前端优雅降级）
    """
    try:
        data = databull.get_etf_composition(symbol)
        if data is None:
            return []
        if isinstance(data, dict):
            data = data.get('data', data.get('items', data.get('list', [])))
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        logger.warning(f'get_etf_composition failed for {symbol}: {e}')
        return []