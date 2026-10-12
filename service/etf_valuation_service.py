"""
 * @author Yc
 * ETF 估值辅助：成分股 + 估算权重（从 PCF 股数 × 最新价归一）。

设计：把原 routes/etf.py 里「ETF 成分股权重」的逻辑抽到 service 层，供两类用途复用：
  1. HTTP 接口（routes/etf.py::get_etf_pcf_weight）直接暴露给前端；
  2. 计算任务（FactorCalService 算 etf_pe_ttm 因子）在进程内直接调用，**不走 HTTP**。

权重口径与边界判定与历史接口完全一致：跨境/商品成分 → supported=False。

⚠️ 市盈率（etf_pe_ttm）的数据基础：成分股 PE 来自 `stock_daily_valuation`（仅 A 股、
由估值日更任务落库）。本服务同时提供「列出某 ETF 的 A 股成分」入口，供估值覆盖扩展
把 ETF 成分股纳入 `stock_daily_valuation` 的落库范围——否则大多数 ETF 的成分股没有 PE，
etf_pe_ttm 会整段为空。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from databull import DataBullError
from utils.data_loader import databull
from utils.logger import logger

# 只有沪深北成分能取到报价：跨境 ETF 的港股/美股成分走另一套报价源，
# 实测 513050 覆盖率 0/34。先按后缀识别，非 A 股成分直接判定不支持。
CN_EXCHANGES = {'SH', 'SZ', 'BJ'}

# 权重取价并发与超时（见 routes/etf.py 原注释）
WEIGHT_FETCH_WORKERS = 16
WEIGHT_FETCH_DEADLINE = 20.0


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
        resp = databull.get_etf_pcf(symbol)
    except DataBullError as e:
        logger.warning(f'get_etf_pcf failed for {symbol}: {e}')
        resp = None

    # ⚠️ SDK 的 get_etf_pcf 返回 {code, data} 信封（旧本地客户端已解包成 data 本身）。
    # 不取内层 data 会拿不到 composition，于是静默退化成「没有股数」的回退链路。
    pcf = resp.get('data') if isinstance(resp, dict) else resp
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
            tick = databull.get_realtime(symbol=code, tick_type='stock') or {}
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


def get_etf_constituent_weights(symbol: str) -> dict:
    """估算 ETF 成分股占净值比：weight = 每篮子股数 × 最新价，再按 Σ 归一化成百分比。

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
        logger.warning(f'get_etf_constituent_weights failed for {symbol}: {e}')
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


def get_etf_pe_weight_map(symbol: str) -> dict:
    """给「ETF 市盈率」因子计算用的轻量版本：返回 {6位A股代码: 占净值比(%)}，
    仅包含 supported 且 weight 非 None 的成分。返回 None 表示该 ETF 不支持 PE。
    """
    w = get_etf_constituent_weights(symbol)
    if not w.get('supported'):
        return None
    out = {}
    for it in w['items']:
        if it.get('weight') is None:
            continue
        code, _ = _split_component_code(it['code'])
        if code:
            out[code] = it['weight']
    return out


def list_etf_astock_constituents(symbol: str) -> set:
    """列出某 ETF 的 A 股成分代码（6 位，去后缀），用于把 ETF 成分股纳入估值覆盖。

    跨境/商品 ETF（无 A 股篮子）返回空 set。失败也返回空 set（不阻断调用方）。
    """
    try:
        rows, _day, _src = _pcf_composition(symbol)
    except Exception:
        return set()
    out = set()
    for row in rows:
        code, exch = _split_component_code(row.get('code'))
        if code and exch in CN_EXCHANGES:
            out.add(code)
    return out
