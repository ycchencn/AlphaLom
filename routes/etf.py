"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

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

# ---------- 申赎清单（PCF）与成分股权重 ----------
# PCF 只给「每个篮子包含多少股」（component_volume），要换算成占净值比必须乘最新价。
# 上游没有批量报价接口（/cn/tick/tickall 在非交易日直接回 {}），只能逐只走
# /cn/stock/tick。实测 282 只 / 16 并发 ≈ 2.5s，因此**权重单独一个接口**、各挂 1h 缓存，
# 不让取价拖慢成分股列表的首屏渲染（列表本身只要 1 次上游请求）。
WEIGHT_FETCH_WORKERS = 16
WEIGHT_FETCH_DEADLINE = 20.0  # 秒。到点就用手上已有报价，缺的权重留空并降低 coverage

# 只有沪深北成分能取到报价：跨境 ETF 的港股/美股成分走的是另一套报价源，
# 实测 513050 覆盖率 0/34。先按后缀识别，非 A 股成分直接判定不支持，
# 省掉几十次必然落空的请求（这些请求还会各自重试 3 次）。
CN_EXCHANGES = {'SH', 'SZ', 'BJ'}

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


def _split_component_code(raw) -> tuple:
    """'000001.SZ' -> ('000001', 'SZ')；无后缀时交易所为空串。"""
    text = str(raw or '').strip().upper()
    if '.' in text:
        code, exch = text.rsplit('.', 1)
        return code, exch
    return text, ''


def _pcf_composition(symbol: str):
    """取 ETF 成分明细，返回 (rows, trading_day, source)。

    rows 每项：{code, name, exchange, volume, trading_day}。
    优先走 PCF（唯一能拿到 component_volume 的来源）；上游没有 PCF、或 PCF 里
    composition 为空（货币 ETF 就返回空数组）时回退轻量成分接口，此时 volume 为
    None —— 前端据此少显示一列，而不是整块空白。
    """
    day = None
    rows = []

    try:
        pcf = databull.get_etf_pcf(symbol)
    except Exception as e:
        logger.warning(f'get_etf_pcf failed for {symbol}: {e}')
        pcf = None

    if isinstance(pcf, dict):
        day = pcf.get('trading_day')
        items = pcf.get('composition')
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                code, exch = _split_component_code(item.get('component_code'))
                if not code:
                    continue
                rows.append({
                    # code 保留上游带后缀的完整写法（页面一直这么展示），
                    # exchange 另给一份，前端要单独分列时不用再切字符串
                    'code': item.get('component_code') or code,
                    'name': item.get('component_name') or '',
                    'exchange': exch,
                    'volume': item.get('component_volume'),
                    'trading_day': item.get('trading_day') or day,
                })
        if rows:
            return _sort_composition(rows), day, 'pcf'

    # 回退：轻量成分接口只有代码/名称
    try:
        fallback = databull.get_etf_composition(symbol)
    except Exception as e:
        logger.warning(f'get_etf_composition(fallback) failed for {symbol}: {e}')
        fallback = None

    if isinstance(fallback, dict):
        fallback = fallback.get('data', fallback.get('items', fallback.get('list', [])))
    if isinstance(fallback, list):
        for item in fallback:
            if not isinstance(item, dict):
                continue
            raw_code = item.get('component_code') or item.get('code') or ''
            code, exch = _split_component_code(raw_code)
            if not code:
                continue
            rows.append({
                'code': raw_code,
                'name': item.get('component_name') or item.get('name') or '',
                'exchange': exch,
                'volume': None,
                'trading_day': day,
            })

    # 一条成分都没取到（上游异常 / 确实无数据）时 source 置 None：
    # 这里若报 'composition'，调用方会以为「回退链路成功返回了数据」。
    return _sort_composition(rows), day, ('composition' if rows else None)


def _sort_composition(rows: list) -> list:
    """按代码升序（字段缺失的排后面），保证接口返回稳定可复现。"""
    return sorted(rows, key=lambda r: (not r.get('code'), str(r.get('code') or '')))


def _fetch_latest_prices(codes: list) -> dict:
    """并发取一组 A 股代码的最新价，返回 {code: price 或 None}。

    3 个要点：
    1. 上游没有批量报价接口，只能逐只请求，所以并发 + 超时上限都不能省；
    2. `as_completed(timeout=...)` 到点抛 TimeoutError，此时**保留已到手的报价**继续算，
       而不是整块失败；
    3. 退出时必须 `shutdown(wait=False)` —— 用 with 语句会等所有在途请求结束，
       一次网络抖动就能把接口拖到分钟级。
    """
    result = {}
    if not codes:
        return result

    def _one(code):
        try:
            tick = databull.get_last_tick(symbol=code, tick_type='stock') or {}
            price = tick.get('lastPrice') if isinstance(tick, dict) else None
            return code, float(price) if price else None
        except Exception:
            return code, None

    executor = ThreadPoolExecutor(max_workers=WEIGHT_FETCH_WORKERS)
    try:
        futures = [executor.submit(_one, c) for c in codes]
        try:
            for fut in as_completed(futures, timeout=WEIGHT_FETCH_DEADLINE):
                code, price = fut.result()
                result[code] = price
        except TimeoutError:
            logger.warning(
                f'latest price fetch timed out, got {len(result)}/{len(codes)}'
            )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return result


@etf_router.get('/etf_pcf/{symbol}')
@cache(expire=3600)
def get_etf_pcf(symbol: str):
    """
    获取 ETF 申赎清单（PCF）里的成分明细：代码 / 名称 / 交易所 / **每篮子股数**。

    刻意不再重复透出 PCF 的清单头（现金差额、最小申赎单位、申赎开关、净值……），
    因为 /etf_info/{symbol} 返回的头部字段与 PCF 完全一致，透两份会变成两个事实来源。
    这里只额外给出 `trading_day`（清单日期）：它是**清单生成日**而非查询日，
    实测上游快照停在 2026-04-27，所以列表必须把它显示出来，否则用户会误以为
    拿到的股数是当日篮子。

    `source` 表明数据来自哪条链路：'pcf' 带股数，'composition' 是回退（只有代码/名称）。
    """
    try:
        rows, trading_day, source = _pcf_composition(symbol)
    except Exception as e:
        logger.warning(f'get_etf_pcf failed for {symbol}: {e}')
        return {'symbol': symbol, 'trading_day': None, 'count': 0, 'source': None, 'composition': []}

    return {
        'symbol': symbol,
        'trading_day': trading_day,
        'count': len(rows),
        'source': source,
        'composition': rows,
    }


@etf_router.get('/etf_pcf_weight/{symbol}')
@cache(expire=3600)
def get_etf_pcf_weight(symbol: str):
    """
    估算成分股占净值比：weight = 每篮子股数 × 最新价，再按 Σ 归一化成百分比。

    为什么不直接用「股数」当权重：PCF 的股数是**绝对股数**，与价格挂钩，
    直接展示会让低价股权重虚高。乘价再归一后，篮子整体水平的偏差（PCF 篮子
    与当前价之间存在时间差）会被约掉，剩下的是相对价格变化带来的误差，可接受，
    所以这里一律标注为「估算」。

    返回 items 与成分列表等长（缺价的 price/weight 为 null），前端按 code 合并。
    `supported=False` 表示这条 ETF 的篮子不是 A 股（跨境 ETF）或没有 PCF，
    此时不会发任何取价请求。
    """
    try:
        rows, trading_day, source = _pcf_composition(symbol)
    except Exception as e:
        logger.warning(f'get_etf_pcf_weight failed for {symbol}: {e}')
        return {'symbol': symbol, 'supported': False, 'reason': 'error', 'items': []}

    if not rows:
        return {
            'symbol': symbol, 'supported': False, 'reason': 'no_composition',
            'trading_day': trading_day, 'coverage': 0, 'items': [],
        }

    parsed = []
    for row in rows:
        code, exch = _split_component_code(row.get('code'))
        volume = row.get('volume')
        parsed.append((row['code'], code, exch, volume))

    foreign = sorted({e for _, _, e, _ in parsed if e and e not in CN_EXCHANGES})
    if foreign or any(not e for _, _, e, _ in parsed):
        return {
            'symbol': symbol, 'supported': False,
            'reason': 'non_cn_components', 'exchanges': foreign,
            'trading_day': trading_day, 'coverage': 0,
            'items': [{'code': r.get('code'), 'price': None, 'weight': None} for r in rows],
        }

    prices = _fetch_latest_prices([c for _, c, _, _ in parsed])

    # 先用「股数 × 最新价」算篮子内市值，再归一；缺价的不计入分母，
    # 否则其它成分的权重会被系统性放大。
    values = []
    total = 0.0
    for full, code, _exch, volume in parsed:
        price = prices.get(code)
        value = (float(volume) * price) if (price and volume) else 0.0
        values.append((full, price, value))
        total += value

    items = []
    for full, price, value in values:
        items.append({
            'code': full,
            'price': round(price, 4) if price else None,
            'weight': round(value / total * 100, 4) if total > 0 and value > 0 else None,
        })

    priced = sum(1 for _, price, _ in values if price)
    return {
        'symbol': symbol,
        'supported': True,
        'reason': None,
        'trading_day': trading_day,
        'source': source,
        'priced': priced,
        'total': len(rows),
        'coverage': round(priced / len(rows), 4),
        'items': items,
    }