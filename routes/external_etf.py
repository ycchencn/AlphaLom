"""
 * @author Yc
 * 对外（外部交易决策系统）ETF 数据接口。
 *
 * 全部只读，且每个接口都显式 `Depends(require_api_user)`（API Key 鉴权 + 每日配额）。
 * 不放在路由级 dependencies 里，是为了避免「路由级 + 端点级」重复执行导致配额被计两次
 * （与 routes.external_stock / routes.external_portfolio 保持一致）。
 *
 * 数据形状与内部 /api/v1/etf* 接口对齐，并复用内部逻辑，不重复实现：
 *   - 监控清单：etf_watchlist（用户私有，按 user_id 隔离）；
 *   - 详情/基本资料/历史/成分：databull（get_etf_info / get_etf_history /
 *     get_etf_composition / get_etf_pcf），兜底与内部 routes/etf.py 完全一致；
 *   - 因子：FactorValueService（52 周高低，批量查询避免 N+1）；
 *   - 恐贪：StockFearGreedService（与个股共用 stocks_fear_greed 表，按 index_code 存）。
 *
 * ⚠️ 所有写库/写缓存的操作都不要出现在这里——对外接口是「数据面」，只读。
 *
 * ⚠️ 路由顺序：`/etfs/watchlist`、`/etfs/search` 必须声明在 `/etfs/{symbol}` 之前，
 * FastAPI 按声明顺序匹配，否则 "watchlist" / "search" 会被当成 symbol 吞掉。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd

from routes.etf import (
    _etf_name_from_databull,
    _fetch_latest_prices,
    _pcf_composition,
    _split_component_code,
)
from service.etf_service import EtfService
from service.factor_service import FactorValueService
from service.stock_fear_greed_service import StockFearGreedService
from utils.api_auth import require_api_user
from utils.common import get_date_by_n, get_today
from utils.data_loader import databull
from utils.logger import logger

ext_etf_router = APIRouter(prefix='/etfs', tags=['ETFs'])

# 成分股取价只支持沪深北（跨境 ETF 的港股/美股成分走另一套报价源，见 routes/etf.py）
_CN_EXCHANGES = {'SH', 'SZ', 'BJ'}


def _validate_etf_symbol(symbol: str):
    """对外接口的代码防御：ETF 代码为 6 位纯数字（159901 / 512480…）。"""
    if not isinstance(symbol, str) or not symbol.isdigit() or len(symbol) != 6:
        raise HTTPException(status_code=400, detail=f'Invalid ETF symbol: {symbol}')


# ---------------------------------------------------------------------------
# ETF 监控清单（用户私有）
# ---------------------------------------------------------------------------
@ext_etf_router.get('/watchlist')
def get_etf_watchlist(user_id: int = Depends(require_api_user)):
    """当前 API Key 所属用户的 ETF 监控清单（含名称、52 周高低、最新行情）。

    按 user_id 隔离，只返回该用户自己加入监控的 ETF；每只批量注入
    `52week_low` / `52week_high`（factor_values）与 `ohlc_last`（databull 实时行情，
    失败时为 {}，不拖垮整表）。
    """
    rows = EtfService.list_watchlist(user_id)
    if not rows:
        return []
    symbols = [r.symbol for r in rows]

    factor_map = FactorValueService.get_latest_factor_values(
        symbols, ('52week_low', '52week_high'))

    result = []
    for row in rows:
        symbol = row.symbol
        # 名称优先用持久化的 name；为空再回退 databull，最后回退代码本身
        name = row.name or _etf_name_from_databull(symbol, fallback=symbol)
        try:
            ohlc = databull.get_realtime(symbol=symbol, tick_type='etf')
        except Exception as e:
            logger.warning(f'get_realtime(etf) failed for {symbol}: {e}')
            ohlc = None
        if not isinstance(ohlc, dict):
            ohlc = {}
        last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
        if last_price is not None and last_close:
            ohlc['chg_pct'] = (last_price - last_close) / last_close * 100
        result.append({
            'symbol': symbol,
            'name': name,
            '52week_low': factor_map.get((symbol, '52week_low')),
            '52week_high': factor_map.get((symbol, '52week_high')),
            'ohlc_last': ohlc,
        })
    return result


@ext_etf_router.get('/search')
def search_etf_ext(
    keyword: str = Query(..., min_length=1, description='代码或名称关键字'),
    market: str = Query('cn', description='市场：cn（默认）'),
    limit: int = Query(50, ge=1, le=200),
    user_id: int = Depends(require_api_user),
):
    """按代码/名称在全市场 ETF 目录中模糊搜索（databull get_etf_list）。

    返回 [{symbol, name}]，最多 limit 条；无匹配返回 []。
    """
    return EtfService.search_etf(keyword, market=market, limit=limit)


# ---------------------------------------------------------------------------
# 单只 ETF
# ---------------------------------------------------------------------------
@ext_etf_router.get('/{symbol}')
def get_etf_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """ETF 详情：名称 + 实时行情 + 52 周高低。"""
    _validate_etf_symbol(symbol)
    name = _etf_name_from_databull(symbol, fallback=symbol)
    try:
        ohlc = databull.get_realtime(symbol=symbol, tick_type='etf')
    except Exception as e:
        logger.warning(f'get_realtime(etf) failed for {symbol}: {e}')
        ohlc = None
    if not isinstance(ohlc, dict):
        ohlc = {}
    last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
    if last_price is not None and last_close:
        ohlc['chg_pct'] = (last_price - last_close) / last_close * 100
    factor_map = FactorValueService.get_latest_factor_values(
        [symbol], ('52week_low', '52week_high'))
    return {
        'symbol': symbol,
        'name': name,
        'ohlc_last': ohlc,
        '52week_low': factor_map.get((symbol, '52week_low')),
        '52week_high': factor_map.get((symbol, '52week_high')),
    }


@ext_etf_router.get('/{symbol}/info')
def get_etf_info_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """ETF 基本资料：交易所、单位净值、申赎单位、类型等。

    上游无数据（404 / 未生成申赎清单）时返回空 dict，调用方优雅降级。
    """
    _validate_etf_symbol(symbol)
    try:
        data = databull.get_etf_info(symbol) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f'get_etf_info failed for {symbol}: {e}')
        return {}


@ext_etf_router.get('/{symbol}/history')
def get_etf_history_ext(
    symbol: str,
    start_date: str = Query(None, description='起始日期 YYYY-MM-DD，默认近一年'),
    end_date: str = Query(None, description='结束日期 YYYY-MM-DD，默认今天'),
    user_id: int = Depends(require_api_user),
):
    """ETF 历史日线行情（timestamp 已转为 YYYY-MM-DD）。

    返回 [{date, open, close, high, low, volume, chg_pct}]，无数据返回 []。
    """
    _validate_etf_symbol(symbol)
    if start_date is None:
        start_date = get_date_by_n(-365)
    if end_date is None:
        end_date = get_today()
    df = databull.get_etf_history(symbol, start_date, end_date)
    if df is None or getattr(df, 'empty', True):
        return []
    df = df.copy()
    # 上游时间戳为毫秒级 epoch，转成 YYYY-MM-DD 便于外部系统消费
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d')
    keep_cols = [c for c in ['date', 'open', 'close', 'high', 'low', 'volume', 'chg_pct'] if c in df.columns]
    return df[keep_cols].to_dict(orient='records')


@ext_etf_router.get('/{symbol}/composition')
def get_etf_composition_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """ETF 成分股构成（轻量：代码/名称，来自 databull get_etf_composition）。

    上游返回空对象或查不到时返回 []。
    """
    _validate_etf_symbol(symbol)
    try:
        data = databull.get_etf_composition(symbol)
        if data is None:
            return []
        if isinstance(data, dict):
            data = data.get('data', data.get('items', data.get('list', [])))
        if not isinstance(data, list):
            return []
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


@ext_etf_router.get('/{symbol}/pcf')
def get_etf_pcf_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """ETF 申赎清单（PCF）成分明细：代码 / 名称 / 交易所 / 每篮子股数。

    `source`：'pcf' 带股数，'composition' 是回退（只有代码/名称）；`trading_day` 是清单生成日。
    """
    _validate_etf_symbol(symbol)
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


@ext_etf_router.get('/{symbol}/pcf-weight')
def get_etf_pcf_weight_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """估算 ETF 成分股占净值比：weight = 每篮子股数 × 最新价，再按 Σ 归一化成百分比。

    `supported=False` 表示篮子不是 A 股（跨境 ETF）或没有 PCF，此时不发取价请求。
    `coverage` = 取到价的成分占比；缺价的 price/weight 为 null。
    """
    _validate_etf_symbol(symbol)
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

    foreign = sorted({e for _, _, e, _ in parsed if e and e not in _CN_EXCHANGES})
    if foreign or any(not e for _, _, e, _ in parsed):
        return {
            'symbol': symbol, 'supported': False,
            'reason': 'non_cn_components', 'exchanges': foreign,
            'trading_day': trading_day, 'coverage': 0,
            'items': [{'code': r.get('code'), 'price': None, 'weight': None} for r in rows],
        }

    prices = _fetch_latest_prices([c for _, c, _, _ in parsed])

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


@ext_etf_router.get('/{symbol}/fear-greed')
def get_etf_fear_greed_ext(
    symbol: str,
    limit: int = Query(250, ge=1, le=1000, description='返回最近 N 个交易日的记录'),
    user_id: int = Depends(require_api_user),
):
    """ETF 恐惧贪婪数据（按交易日倒序）。

    与个股走同一张表 `stocks_fear_greed`（按 index_code 存，ETF 代码号段自然落入），
    由日更任务用 ETF 自己的日线计算，非上游直读。
    """
    _validate_etf_symbol(symbol)
    return StockFearGreedService.get_by_index_all(index_code=symbol, limit=limit)


@ext_etf_router.get('/{symbol}/analysis')
def get_etf_analysis_ext(
    symbol: str,
    history_days: int = Query(120, ge=1, le=500, description='聚合里附带的历史日线天数'),
    user_id: int = Depends(require_api_user),
):
    """ETF 聚合分析：一次调用拿全（详情 + 基本资料 + 成分 + 恐贪 + 近 N 日历史）。

    任一分项取数失败不影响其它分项（失败项返回 null/[]），便于外部决策系统稳健消费。
    """
    _validate_etf_symbol(symbol)

    result = {
        'symbol': symbol,
        'profile': None,        # 名称 + 行情 + 52 周
        'info': None,           # 基本资料
        'composition': None,    # 成分股（轻量）
        'pcf': None,            # 申赎清单
        'fear_greed': None,     # 恐贪序列
        'history': None,        # 近 N 日历史
    }

    # 详情（名称/行情/52周）
    try:
        name = _etf_name_from_databull(symbol, fallback=symbol)
        try:
            ohlc = databull.get_realtime(symbol=symbol, tick_type='etf')
        except Exception as e:
            logger.warning(f'get_realtime(etf) failed for {symbol}: {e}')
            ohlc = None
        if not isinstance(ohlc, dict):
            ohlc = {}
        last_price, last_close = ohlc.get('lastPrice'), ohlc.get('lastClose')
        if last_price is not None and last_close:
            ohlc['chg_pct'] = (last_price - last_close) / last_close * 100
        factor_map = FactorValueService.get_latest_factor_values(
            [symbol], ('52week_low', '52week_high'))
        result['profile'] = {
            'symbol': symbol, 'name': name, 'ohlc_last': ohlc,
            '52week_low': factor_map.get((symbol, '52week_low')),
            '52week_high': factor_map.get((symbol, '52week_high')),
        }
    except Exception as e:
        result['profile'] = {'error': str(e)}

    # 基本资料
    try:
        data = databull.get_etf_info(symbol) or {}
        result['info'] = data if isinstance(data, dict) else {}
    except Exception as e:
        result['info'] = {'error': str(e)}

    # 成分股（轻量）
    try:
        data = databull.get_etf_composition(symbol)
        if isinstance(data, dict):
            data = data.get('data', data.get('items', data.get('list', [])))
        items = []
        for it in (data if isinstance(data, list) else []):
            if isinstance(it, dict):
                items.append({
                    'code': it.get('component_code') or it.get('code') or '',
                    'name': it.get('component_name') or it.get('name') or '',
                })
        result['composition'] = items
    except Exception as e:
        result['composition'] = {'error': str(e)}

    # 申赎清单
    try:
        rows, trading_day, source = _pcf_composition(symbol)
        result['pcf'] = {
            'symbol': symbol, 'trading_day': trading_day,
            'count': len(rows), 'source': source, 'composition': rows,
        }
    except Exception as e:
        result['pcf'] = {'error': str(e)}

    # 恐贪
    try:
        result['fear_greed'] = StockFearGreedService.get_by_index_all(index_code=symbol, limit=250)
    except Exception as e:
        result['fear_greed'] = {'error': str(e)}

    # 历史日线
    try:
        start_date = get_date_by_n(-max(history_days * 2, 400))
        end_date = get_today()
        df = databull.get_etf_history(symbol, start_date, end_date)
        if df is None or getattr(df, 'empty', True):
            result['history'] = []
        else:
            df = df.copy()
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d')
            keep_cols = [c for c in ['date', 'open', 'close', 'high', 'low', 'volume', 'chg_pct'] if c in df.columns]
            result['history'] = df[keep_cols].tail(history_days).to_dict(orient='records')
    except Exception as e:
        result['history'] = {'error': str(e)}

    return result
