"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 沪深大盘指数卡片（支撑「市场监控 → 沪深大盘」页的指数卡片行）。

 ⚠️ 与美股页（`us_index_service.py`）**共用同一套卡片算法**
 （`index_card_common.build_card`）—— 两页的卡片长得一样，算法就不能各写一份。
 本模块只负责沪深特有的两件事：

  1. 数据源是**两个**接口拼起来的：实时 tick（`get_realtime`，有盘中最新价）
     + 日线（`get_index_history`，给迷你走势和近 5 日/年初至今）。
     美股只有日线，所以那边不走 tick。
  2. 指数代码表与中文名映射（上游 tick 不带名称）。

 ⚠️ **实时 tick 的字段里没有 `change` / `changePercent`**（实测只有 time /
 lastPrice / open / high / low / lastClose / amount / volume）→ 涨跌一律
 `lastPrice - lastClose` 自己算。前端原先也是自己算的，现在收到卡片里统一算。

 ⚠️ 上游 tick 时间戳是**毫秒**（字段名 `time`，不是 `tick_time`）。

 ⚠️ `get_index_history` **没有 `as_dataframe` 参数**（与 `get_us_index_history`
 不同），返回带 DatetimeIndex 的 DataFrame、收盘列名为 `close`。

 ⚠️ 沪深300（000300）**不在列表里**：它是被 commit feb32a6 明确移除的，别顺手加回来
 （前端 `INDICES_NAME` 里还留着这个名字，但后端不返回 → 那张卡根本不会渲染，这是
 既有行为）。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from databull import DataBullError

from service.index_card_common import (
    FETCH_WORKERS,
    build_card,
    history_window,
    merge_live,
    normalize_bars,
)
from utils.data_loader import databull
from utils.logger import logger

# 指数代码表 = 页面展示顺序。
# ⚠️ 与 `routes/index.py::get_index_last` 的列表**必须一致**：前端有名字而这里不返回的
# 指数，卡片根本不会渲染（不是显示空值）。000300 见文件头说明，故意不加。
CN_INDEX_CODES: List[str] = ['000001', '399001', '399006', '000688', '000692']

# 中文名。上游 tick 不带名称（日线 DataFrame 也不带），只能本地映射。
# 名称缺失时退回代码，至少不会渲染出空白卡片。
CN_INDEX_NAMES: Dict[str, str] = {
    '000001': '上证指数',
    '399001': '深证成指',
    '399006': '创业板指',
    '000688': '科创50',
    '000692': '科创200',
    '000300': '沪深300',
}


class CnIndexError(RuntimeError):
    """取数失败。路由层转成 502，不把栈打给前端。"""


def _fetch_history_bars(code: str, start: str, end: str) -> List[Dict[str, Any]]:
    """取单个指数的日线，归一化成升序 bar 列表。取不到就**抛**。"""
    try:
        frame = databull.get_index_history(code, start, end)
    except DataBullError as e:
        raise CnIndexError(f'指数 {code} 日线取数失败: {e}') from e
    except Exception as e:  # noqa: BLE001
        raise CnIndexError(f'指数 {code} 日线取数异常: {e}') from e

    if frame is None or getattr(frame, 'empty', True) or 'close' not in getattr(frame, 'columns', []):
        raise CnIndexError(f'指数 {code} 无日线数据')

    raw = []
    for idx, row in frame.iterrows():
        # DatetimeIndex → 'YYYY-MM-DD'
        raw.append({
            'date': str(getattr(idx, 'date', lambda: idx)())[:10],
            'close': row.get('close'),
            'open': row.get('open'),
            'high': row.get('high'),
            'low': row.get('low'),
        })
    bars = normalize_bars(raw)
    if not bars:
        raise CnIndexError(f'指数 {code} 收盘价全为空')
    return bars


def _fetch_tick(code: str) -> Optional[Dict[str, Any]]:
    """取实时 tick。失败返回 None（**不抛**）—— 没有 tick 还有日线兜底，
    不该因为盘中行情抖动让整张卡消失。"""
    try:
        res = databull.get_realtime(code, tick_type='index', market='cn')
    except DataBullError as e:
        logger.warning(f'cn index tick failed for {code}: {e}')
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f'cn index tick error for {code}: {e}')
        return None
    return res if isinstance(res, dict) and res.get('lastPrice') is not None else None


def _tick_date(tick: Dict[str, Any]) -> Optional[str]:
    """tick 的毫秒时间戳 → 'YYYY-MM-DD'。解析不出来就返回 None。"""
    ts = tick.get('time')
    if ts is None:
        return None
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    # 13 位毫秒；10 位秒（兼容上游将来改精度）
    if ts > 1e12:
        ts = ts / 1000.0
    try:
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except (OverflowError, OSError, ValueError):
        return None


def _build_one(code: str, start: str, end: str) -> Dict[str, Any]:
    """单张卡：日线 + tick 拼成卡片。

    除卡片本身外**额外回传 `tick_ms`**（毫秒时间戳）—— 顶部「数据时间」要精确到
    时分，而卡片的 `trade_date` 只有日期。tick_ms 不放进卡片对象里，免得污染
    与美股共用的卡片结构。
    """
    bars = _fetch_history_bars(code, start, end)
    tick = _fetch_tick(code)

    prev_close = None
    last_open = last_high = last_low = None
    if tick:
        # tick 的 lastClose 是**最权威的昨收**（比日线倒数第二根更准：日线偶有缺失/复权差异）
        try:
            lc = tick.get('lastClose')
            prev_close = float(lc) if lc is not None else None
        except (TypeError, ValueError):
            prev_close = None
        last_open = tick.get('open')
        last_high = tick.get('high')
        last_low = tick.get('low')

        # 把盘中最新价并进走势序列末端（上游可能还没落当日 K 线）
        tdate = _tick_date(tick)
        try:
            last_price = float(tick.get('lastPrice'))
        except (TypeError, ValueError):
            last_price = None
        if tdate and last_price is not None:
            bars = merge_live(bars, tdate, last_price)
            # 并入后若末根就是 tick 当日，开高低也用 tick 的（日线那根可能是半截）
            if bars[-1]['date'] == tdate:
                last_open, last_high, last_low = (
                    tick.get('open'), tick.get('high'), tick.get('low'))

    card = build_card(
        bars,
        code=code,
        name=CN_INDEX_NAMES.get(code, code),
        prev_close=prev_close,
        last_open=last_open,
        last_high=last_high,
        last_low=last_low,
    )
    card['tick_ms'] = tick.get('time') if tick else None
    return card


class CnIndexService:
    """沪深大盘指数卡片数据。"""

    @staticmethod
    def get_cards() -> Dict[str, Any]:
        """取全部沪深指数的卡片数据。

        :return: ``{meta, items}``；``items`` 是**扁平列表**、按 `CN_INDEX_CODES`
            原序（不要按涨跌幅排 —— 那样每次刷新卡片顺序都在跳）。
            单个指数失败只跳过（记入 ``meta.failed``），全部失败才抛。
        """
        start, end = history_window()

        results: Dict[str, Any] = {}
        failed: List[Dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {pool.submit(_build_one, c, start, end): c for c in CN_INDEX_CODES}
            for fut, code in futures.items():
                try:
                    results[code] = fut.result()
                except CnIndexError as e:
                    logger.warning(f'cn index card failed for {code}: {e}')
                    failed.append({'code': code, 'reason': str(e)})

        if not results:
            raise CnIndexError('全部沪深指数取数失败')

        # ⚠️ 按 CN_INDEX_CODES 原序输出，别用 dict 插入序（并发完成顺序不定）。
        cards = [results[c] for c in CN_INDEX_CODES if c in results]

        # ⚠️ 从卡片里摘掉 tick_ms 再对外输出（它只用于算下面的 data_time，
        # 不该混进与美股共用的卡片结构里）。
        tick_times = [c.pop('tick_ms', None) for c in cards]
        tick_times = [t for t in tick_times if t]

        # 主日期 = 众数（tick 已并入，正常全部一致；个别停更的会被标出）。
        dates = [c['trade_date'] for c in cards if c.get('trade_date')]
        main_date = max(set(dates), key=dates.count) if dates else ''
        stale = [c['code'] for c in cards if c.get('trade_date') and c['trade_date'] < main_date]

        return {
            'meta': {
                'data_date': main_date,
                'total': len(cards),
                'expected': len(CN_INDEX_CODES),
                # 精度到毫秒的行情时间（前端顶部显示「数据时间」用）；没有 tick 时为 None
                'data_time_ms': max(tick_times) if tick_times else None,
                'stale_codes': stale,
                'failed': failed,
                'trade_timezone': 'Asia/Shanghai',
                # 沪深有实时 tick（盘中可直接看到最新价，不像美股只有收盘日线）
                'realtime_available': True,
            },
            'items': cards,
        }
