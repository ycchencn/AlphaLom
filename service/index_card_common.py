"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 指数卡片（沪深 / 美股大盘两页共用）的**取数口径与卡片计算**。

 为什么要抽出来：沪深大盘页与美股大盘页用**同一套卡片视觉**（名称/代码、点位、
 当日涨跌、近 5 日、年初至今、近 60 日迷你走势）。两页的数据源不同（沪深有实时
 tick + 日线，美股只有日线），但**卡片的算法必须完全一致** —— 否则同一天两个页面的
 「当日涨跌」会因为一个读上游 `chg_pct`、一个自己算而在小数点后分叉。
 所以：口径（`pct` / YTD 基准 / 近 5 日定义）只在这里写一次。

 ⚠️ 三条口径红线（历史踩过，改之前先看）：
  1. **当日涨跌自己用相邻收盘价算**，不读上游派生字段 —— 上游把**窗口首根**的
     `chg_pct`/`change_amount` 置 0（实测美股 08-01~10-07 第一根为 0.0），
     照抄会让「区间第一段」显示成 0.00%。
  2. **YTD 基准 = 当年第一根 K 线的收盘**，不是「本年 1 月 1 日之后的第一根开盘」。
     后者会漏掉上年最后收盘，YTD 偏小一截。
  3. **算不出来要给 None**，不能给 0 —— 0 会被前端渲染成「涨跌 0.00%」，
     把「没数据」伪装成「没涨没跌」。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# 迷你走势取近 60 个交易日。
SPARK_DAYS = 60

# 取数窗口（自然日）。卡片要算「年初至今」，所以至少要跨过 1 月 1 日；
# 60 个交易日 + 周末 + 长假，400 自然日足够，且不会把上游全量历史拖下来。
HISTORY_CALENDAR_DAYS = 400

# 并发度：单次取数约 1s，5~11 个指数串行会到 5~11s，页面首屏直接超时。
# 上游是读接口，不需要限流到 1。
FETCH_WORKERS = 6


def to_compact_date(d: datetime) -> str:
    """统一成上游能吃两种格式里的紧凑那种（YYYYMMDD）。"""
    return d.strftime('%Y%m%d')


def pct(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    """区间涨跌幅（%）。base 非法或为 0 时返回 None（**不是 0**，见文件头红线 3）。"""
    if base in (0, None) or cur is None:
        return None
    return (cur - base) / base * 100.0


def normalize_bars(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把上游日线归一化成**升序、按日期去重、close 非空**的 bar 列表。

    ⚠️ 不要赌上游一定升序：实测美股 VIX 那类数据偶有乱序。同日重复（多源合并）
    保留最后一条。
    """
    bars = []
    for it in raw or []:
        close = it.get('close')
        if close is None:
            continue
        try:
            close = float(close)
        except (TypeError, ValueError):
            continue
        bars.append({
            'date': str(it.get('date') or '')[:10],
            'close': close,
            'open': it.get('open'),
            'high': it.get('high'),
            'low': it.get('low'),
        })
    bars.sort(key=lambda b: b['date'])
    deduped: Dict[str, Dict[str, Any]] = {}
    for b in bars:
        if b['date']:
            deduped[b['date']] = b
    return [deduped[d] for d in sorted(deduped)]


def merge_live(bars: List[Dict[str, Any]], live_date: str,
               live_close: Optional[float]) -> List[Dict[str, Any]]:
    """把**实时价**并入日线序列，让迷你走势的末端落在当前价上。

    - 实时日期 == 末根日线日期 → **替换**末根收盘（盘中上游可能已落了一根当日的
      半截 K 线，直接追加会出现同名日期的两个点）；
    - 实时日期 > 末根日期 → **追加**（上游还没落当日 K 线）；
    - 实时日期 < 末根日期 / 没有实时值 → 原样返回（不往回改历史）。

    ⚠️ 沪深页有实时 tick、美股页没有，所以这个函数只有沪深会真的用到；
    但放在公共模块是为了让「卡片末端价」在两页有唯一定义。
    """
    if live_close is None or not live_date or not bars:
        return bars
    if live_date < bars[-1]['date']:
        return bars
    merged = [dict(b) for b in bars]
    if live_date == merged[-1]['date']:
        merged[-1]['close'] = live_close
    else:
        merged.append({'date': live_date, 'close': live_close})
    return merged


def build_card(bars: List[Dict[str, Any]], *, code: str, name: str,
               category: str = 'broad', is_volatility: bool = False,
               prev_close: Optional[float] = None,
               last_open: Optional[float] = None,
               last_high: Optional[float] = None,
               last_low: Optional[float] = None) -> Dict[str, Any]:
    """把一条**升序、已并入实时价**的收盘序列压成一张卡片所需字段。

    :param bars: `[{date, close, ...}]`，升序，最后一项代表「现在」
    :param prev_close: 优先用外部给的「昨收」（沪深实时 tick 的 `lastClose` 最权威）；
        不给就退化为序列里倒数第二根
    :param last_open/high/low: 当日开高低（沪深 tick 有，美股日线也有）
    """
    last = bars[-1]
    close = last['close']

    if prev_close is None and len(bars) >= 2:
        prev_close = bars[-2]['close']
    chg_pct = pct(close, prev_close)
    chg_amount = (close - prev_close) if prev_close is not None else None

    # 年初至今：当年**第一根 K 线**的收盘（见文件头红线 2）。
    year = last['date'][:4] if last['date'] else ''
    year_start = next((b['close'] for b in bars if b['date'][:4] == year), None)
    ytd_pct = pct(close, year_start)

    # 近 5 个交易日（bars 升序，回看 5 根；不足 6 根就没有「5 日前」这个基准）。
    pct_5d = pct(close, bars[-6]['close']) if len(bars) >= 6 else None

    spark = [{'date': b['date'], 'close': b['close']} for b in bars[-SPARK_DAYS:]]

    return {
        'code': code,
        'name': name,
        'category': category,
        'trade_date': last['date'],
        'close': close,
        'open': last_open if last_open is not None else last.get('open'),
        'high': last_high if last_high is not None else last.get('high'),
        'low': last_low if last_low is not None else last.get('low'),
        'prev_close': prev_close,
        'chg_amount': chg_amount,
        'chg_pct': chg_pct,
        'pct_5d': pct_5d,
        'pct_ytd': ytd_pct,
        'is_volatility': is_volatility,
        'spark': spark,
    }


def history_window(now: Optional[datetime] = None):
    """取数窗口（紧凑格式的 start/end）。"""
    end = now or datetime.now()
    return (to_compact_date(end - timedelta(days=HISTORY_CALENDAR_DAYS)),
            to_compact_date(end))
