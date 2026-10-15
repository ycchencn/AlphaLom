"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 A股宽基 vs 美股宽基 风格强弱（中证A500 000510 ÷ 标普500 GSPC），支撑美股大盘监控页。

 口径说明：
   - A股腿：中证A500 000510（固定）
   - 美股腿：标普500 GSPC（market='us'）

 ⚠️ 为什么是 000510 而不是官方 CSI 代码 931337：上游 `get_index_history`
 对中证自编号段（930/931/932/92xxxx/.CSI）**全返 0 行**（详见
 growth_value_service.py 顶部说明），而 000510（中证A500 价格指数，基点 1000）
 实测有完整日线。所以 A股宽基用 000510 这个能取数的代码，名字本地写死「中证A500」。

 比值的读法：
   ratio = 中证A500 / 标普500。比值**上行 = A股跑赢美股**（A股占优），
   下行 = 美股跑赢 A股。注意比值本身没有绝对高低含义 —— 起点归一化后才有
   「相对强弱」的解释，所以这里同时给归一化净值（起点 1.0）。

 结构完全复用 growth_value_service.py 的 proven 逻辑：两条腿按交易日 inner join
 对齐（不 reindex+ffill，避免伪造横盘点），归一化到区间首日为 1.0，再算比值与
 各窗口区间涨跌幅。唯一差异是「两条腿来自不同市场、不同取数接口」。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from databull import DataBullError
from utils.data_loader import databull
from utils.logger import logger

# A股腿 / 美股腿
A500_CODE = '000510'
A500_NAME = '中证A500'
SP500_CODE = 'GSPC'
SP500_NAME = '标普500'

# 前端「近 N 个交易日」的合法范围
DEFAULT_DAYS = 250
MIN_DAYS = 20
MAX_DAYS = 2000

# ⚠️ 取数窗口必须**宽于**所需交易日数：区间内有春节 / 美国假期等连续休市，
# 自然日 ≠ 交易日。250 个交易日按 1.6 倍留余量（约 400 自然日）足够覆盖。
_WINDOW_FACTOR = 1.6

# 区间涨跌幅档位（前端迷你条用）——交易日数
PERIOD_WINDOWS = (5, 20, 60)


class A500Sp500Error(ValueError):
    """取数或对齐失败。路由层转成 422/404，不要把栈打给前端。"""


def _to_compact_date(d: datetime) -> str:
    return d.strftime('%Y%m%d')


def _fetch_close(index_code: str, market: str, start_compact: str, end_compact: str) -> pd.Series:
    """取一条指数日线收盘价序列（索引为日期的 Series）。

    ⚠️ 上游失败要**抛**，不能返回空序列 —— 两条腿里任何一条空着，
    比值曲线就整个没有意义。让路由层决定是回退还是报错，别在这里静默降级。

    :param market: 'cn' 走 `get_index_history`（返回带 DatetimeIndex 的 DataFrame），
                   'us' 走 `get_us_index_history`（返回 {data:{items:[{date,close}]}}）。
    """
    if market == 'us':
        try:
            res = databull.get_us_index_history(index_code, start_compact, end_compact, as_dataframe=False)
        except DataBullError as e:
            raise A500Sp500Error(f'指数 {index_code} 取数失败: {e}') from e
        except Exception as e:  # noqa: BLE001
            raise A500Sp500Error(f'指数 {index_code} 取数异常: {e}') from e

        if not isinstance(res, dict):
            raise A500Sp500Error(f'指数 {index_code} 返回结构异常: {type(res).__name__}')
        items = (res.get('data') or {}).get('items') or []
        if not items:
            raise A500Sp500Error(f'指数 {index_code} 无数据')

        rows: List[tuple] = []
        for it in items:
            close = it.get('close')
            if close is None:
                continue
            try:
                close = float(close)
            except (TypeError, ValueError):
                continue
            date_str = str(it.get('date') or '')[:10]
            if not date_str:
                continue
            rows.append((date_str, close))
        if not rows:
            raise A500Sp500Error(f'指数 {index_code} 收盘价全为空')

        s = pd.Series(
            [r[1] for r in rows],
            index=pd.to_datetime([r[0] for r in rows]).normalize(),
            name=index_code,
        )
        s = s[~s.index.duplicated(keep='last')].sort_index()
        return s.dropna()
    else:
        try:
            frame = databull.get_index_history(index_code, start_compact, end_compact)
        except DataBullError as e:
            raise A500Sp500Error(f'指数 {index_code} 取数失败: {e}') from e
        except Exception as e:  # noqa: BLE001
            raise A500Sp500Error(f'指数 {index_code} 取数异常: {e}') from e

        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty or 'close' not in frame.columns:
            raise A500Sp500Error(f'指数 {index_code} 无数据')

        close = pd.to_numeric(frame['close'], errors='coerce').astype('float64')
        # 上游日期有的带时区/时分秒，统一抹成 naive date，否则两条腿对齐时会因为
        # 00:00:00 与 .000000000 之类的差异对不上。
        close.index = pd.to_datetime(frame.index).normalize()
        close = close[~close.index.duplicated(keep='last')].sort_index()
        close.name = index_code
        return close.dropna()


class A500Sp500Service:

    @staticmethod
    def get_series(days: int = DEFAULT_DAYS) -> Dict[str, Any]:
        """取「A股 ÷ 美股」比值序列。

        :param days: 返回最近 N 个**交易日**（1 个点/日），已按日期升序。
        :return: {meta, points, periods}
        """
        try:
            days = int(days)
        except (TypeError, ValueError) as e:
            raise A500Sp500Error(f'days 必须是整数，收到 {days!r}') from e
        if days < MIN_DAYS or days > MAX_DAYS:
            raise A500Sp500Error(f'days 需在 {MIN_DAYS}~{MAX_DAYS} 之间')

        end = datetime.now()
        start = end - timedelta(days=int(days * _WINDOW_FACTOR))
        start_compact, end_compact = _to_compact_date(start), _to_compact_date(end)

        a500 = _fetch_close(A500_CODE, 'cn', start_compact, end_compact)
        sp500 = _fetch_close(SP500_CODE, 'us', start_compact, end_compact)

        # ⚠️ 用 inner join 对齐交易日，**不能 reindex + ffill**。
        # 两个市场的交易日不同（A股春节休市、美国节假日），ffill 会伪造横盘点，
        # inner join 干净地丢掉不同步的那天。误差是「少一个采样点」，比伪造一段
        # 横盘安全得多。
        joined = pd.concat([a500.rename('a500'), sp500.rename('sp500')], axis=1, join='inner')
        joined = joined.dropna()
        if joined.empty:
            raise A500Sp500Error('A股与美股两条指数没有共同交易日')

        joined = joined.tail(days)
        if joined.empty:
            raise A500Sp500Error('对齐后无数据')

        # 归一化：以区间首日为 1.0，让两条腿可比（绝对点位量纲不同：A股五千点级、
        # 美股五千点级虽然接近，但比值看的是相对变化）。
        base_a500 = float(joined['a500'].iloc[0])
        base_sp500 = float(joined['sp500'].iloc[0])
        if base_a500 <= 0 or base_sp500 <= 0:
            raise A500Sp500Error('基准日收盘价非法（<=0）')

        a500_norm = joined['a500'] / base_a500
        sp500_norm = joined['sp500'] / base_sp500
        ratio = a500_norm / sp500_norm  # 等价于 (A股/美股) 再按起点归一

        points: List[Dict[str, Any]] = []
        for dt, r in ratio.items():
            points.append({
                'trade_date': dt.strftime('%Y-%m-%d'),
                'ratio': round(float(r), 4),
                'a500_norm': round(float(a500_norm.loc[dt]), 4),
                'sp500_norm': round(float(sp500_norm.loc[dt]), 4),
                'a500_close': round(float(joined['a500'].loc[dt]), 2),
                'sp500_close': round(float(joined['sp500'].loc[dt]), 2),
            })

        return {
            'meta': {
                'a500_code': A500_CODE,
                'a500_name': A500_NAME,
                'sp500_code': SP500_CODE,
                'sp500_name': SP500_NAME,
                'start_date': points[0]['trade_date'],
                'end_date': points[-1]['trade_date'],
                'trade_days': len(points),
            },
            'points': points,
            'periods': A500Sp500Service._periods(points),
        }

    @staticmethod
    def _periods(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """各区间比值涨跌幅（近 5 / 20 / 60 个交易日）。

        用**当前比值**与「N 个交易日前那个点」的比值相除 —— 因为比值本身已按
        区间首日归一，直接比就是该窗口内的相对强弱变化。

        ⚠️ 取不到 N 个交易日前那个点时（比如只取了 20 个点却要算「近 20 日」），
        退化为「用区间最早那个点」而不是返回 None（避免界面出现一条恒为 `--` 的条）。
        """
        out: List[Dict[str, Any]] = []
        last = points[-1]
        for w in PERIOD_WINDOWS:
            past = points[-1 - w] if len(points) > w else points[0]
            if not past.get('ratio'):
                out.append({'days': w, 'change_pct': None})
                continue
            change = (last['ratio'] / past['ratio'] - 1) * 100
            out.append({'days': w, 'change_pct': round(change, 2)})
        return out
