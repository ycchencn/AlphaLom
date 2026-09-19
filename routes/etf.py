"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query, HTTPException
from fastapi_cache.decorator import cache
from pydantic import BaseModel
from typing import Optional
from app.fastapi_app import api_prefix
from utils.data_loader import databull
from service import FactorValueService
from service.etf_service import EtfService
from utils.common import get_today, get_date_by_n
from utils.logger import logger
import pandas as pd

etf_router = APIRouter(prefix=api_prefix, tags=['ETF'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；写成 `async def`
# 会让下面循环里的同步 databull HTTP 调用直接占死事件循环 → 全站一起卡。

# ETF 监控清单（静态）。仅作为列表接口的符号枚举来源（上游 get_etf_list 在 dev 返回空）；
# 名称不再从这里取 —— 统一从 databull 的 get_etf_info 接口获取（见 _etf_name_from_databull）。
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


def _etf_name_from_databull(symbol: str, fallback: str = None) -> str:
    """
    ETF 名称统一从 databull 接口取（get_etf_info 返回的 data 含 name 字段）。
    databull 不可用 / 无 name 时回退到 fallback（通常为静态清单名或代码本身）。
    """
    try:
        info = databull.get_etf_info(symbol) or {}
        if isinstance(info, dict) and info.get('name'):
            return info['name']
    except Exception as e:
        logger.warning(f'get_etf_info (name) failed for {symbol}: {e}')
    return fallback if fallback is not None else str(symbol)


@etf_router.get('/etfs')
def get_etfs():
    """
    获取ETF监控列表（持久化在 etf_watchlist 表）。
    不挂 @cache：增删需即时可见，且每只 ETF 的行情来自 databull 实时接口。
    """
    rows = EtfService.list_watchlist()
    result = []
    for row in rows:
        symbol = row.symbol
        etf = {
            # 名称优先用持久化的 name；为空（早期脏数据/接口失败）再回退 databull，最后回退代码
            'symbol': symbol,
            'name': row.name or _etf_name_from_databull(symbol, fallback=symbol),
            '52week_low': FactorValueService.get_latest_factor_value(
                ticker=symbol, factor_name='52week_low'
            ),
            '52week_high': FactorValueService.get_latest_factor_value(
                ticker=symbol, factor_name='52week_high'
            ),
        }
        ohlc = databull.get_last_tick(symbol=symbol, tick_type='etf') or {}
        # 远端偶发返回空结果（实测 159990 就会返回 {}）。原实现直接 ohlc['lastPrice'] 下标取值，
        # 一旦为空就 KeyError，导致**整个 ETF 列表接口 500**、全页打不开。
        # 前端对 ohlc_last 的各字段都有 `!= null` 兜底（显示 '--'），所以这里只需保证
        # ohlc_last 始终是 dict、拿不到数据时不写 chg_pct。
        last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
        if last_price is not None and last_close:
            ohlc['chg_pct'] = (last_price - last_close) / last_close * 100
        etf['ohlc_last'] = ohlc
        result.append(etf)

    return result


@etf_router.get('/etf_search')
def search_etf(
    keyword: str = Query('', description='代码或名称关键字'),
    market: str = Query('cn'),
    limit: int = Query(50, ge=1, le=200),
):
    """
    按代码/名称在全市场 ETF 目录中模糊搜索（databull get_etf_list）。
    用于「添加 ETF」弹窗的搜索联想。
    """
    return EtfService.search_etf(keyword, market=market, limit=limit)


class EtfAddRequest(BaseModel):
    symbol: str
    name: Optional[str] = None


@etf_router.post('/etf')
def add_etf(req: EtfAddRequest):
    """
    添加一只 ETF 到监控列表（持久化）。symbol 必填，name 可选（不传则由接口取）。
    """
    try:
        item = EtfService.add_watchlist(req.symbol, name=req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'code': 0, 'message': 'ok', 'data': item.to_dict()}


@etf_router.delete('/etf/{symbol}')
def delete_etf(symbol: str):
    """
    从监控列表移除一只 ETF。
    """
    ok = EtfService.delete_watchlist(symbol)
    if not ok:
        raise HTTPException(status_code=404, detail=f'ETF {symbol} 不在监控列表中')
    return {'code': 0, 'message': 'ok'}


@etf_router.get('/etf/{symbol}')
@cache(expire=3600)
def get_etf_detail(symbol: str):
    """
    获取ETF详情：基础信息 + 实时行情 + 52周高低
    """
    # 名称统一从 databull 接口取（get_etf_info 含 name）；上游不可用时回退静态清单名/代码
    name = _etf_name_from_databull(symbol, fallback=ETF_NAME_MAP.get(str(symbol), symbol))

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
# @cache(expire=3600)
def get_etf_composition(symbol: str):
    """
    获取ETF成分股构成（databull get_etf_composition：component_code / component_name）。
    上游返回空对象 {} 或查不到时返回空列表，前端优雅降级。
    """
    try:
        # SDK 已修正路径并直接回传 data 数组；此处做 None/类型兜底
        data = databull.get_etf_composition(symbol)
        if data is None:
            return []
        if isinstance(data, dict):
            # 防御：若将来 SDK 改回返回 {code,data} 整体
            data = data.get('data', data.get('items', data.get('list', [])))
        if not isinstance(data, list):
            return []
        # 取需要的字段并补默认值，字段缺失不至于让前端整列空白
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            result.append({
                'code': item.get('component_code') or item.get('code') or '',
                'name': item.get('component_name') or item.get('name') or '',
            })
        return result
    except Exception as e:
        logger.warning(f'get_etf_composition failed for {symbol}: {e}')
        return []