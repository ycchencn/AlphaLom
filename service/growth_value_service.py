"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 「成长 vs 价值」风格强弱（创业板指 ÷ 红利指数），支撑沪深大盘监控页。

 口径说明（与用户确认过）：
   - 成长腿：创业板指 399006（固定，按需求原话）
   - 价值腿：**上证红利 000015**，不是中证红利 000922

 ⚠️ 为什么不是「中证红利」：上游 databull 的指数目录（/cn/index/search）里
 000922.CSI 名称确实是「中证红利」，但 `/cn/index/history` 对 000922.CSI /
 399922.SZ / 000922 全都返回**空**（只有目录条目、没有 K 线），
 实测 `get_index_history` 亦然。这不是本项目封装的问题 —— 直连上游接口同样为空。
 有完整日线的红利指数是：000015（上证红利）/ 399321（国证红利）/ 399324（深证红利）。
 取「上证红利」是因为它就是「红利指数」本尊、A 股红利风格最常用的代理。

 比值的读法：
   ratio = 创业板指 / 上证红利。比值**上行 = 成长跑赢价值**（成长风格占优），
   下行 = 价值跑赢成长。注意比值本身没有绝对高低含义 —— 起点归一化后才有
   「相对强弱」的解释，所以这里同时给归一化净值（起点 1.0）。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from databull import DataBullError
from utils.data_loader import databull
from utils.logger import logger

# 成长腿 / 价值腿（代码保持与上游一致；market='cn'）
GROWTH_CODE = '399006'
GROWTH_NAME = '创业板指'
VALUE_CODE = '000015'
VALUE_NAME = '上证红利'

# 前端「近 N 个交易日」的合法范围。252 ≈ 一年交易日。
DEFAULT_DAYS = 250
MIN_DAYS = 20
MAX_DAYS = 2000

# ⚠️ 取数窗口必须**宽于**所需交易日数：区间内有春节等连续休市，
# 自然日 ≠ 交易日。250 个交易日按 1.6 倍留余量（约 400 自然日）足够覆盖。
_WINDOW_FACTOR = 1.6

# 区间涨跌幅档位（前端迷你条用）——交易日数
PERIOD_WINDOWS = (5, 20, 60)


class GrowthValueError(ValueError):
    """取数或对齐失败。路由层转成 422/404，不要把栈打给前端。"""


def _to_compact_date(d: datetime) -> str:
    return d.strftime('%Y%m%d')


def _fetch_close(index_code: str, start_compact: str, end_compact: str) -> pd.Series:
    """取一条指数日线收盘价序列（索引为日期的 Series）。

    ⚠️ 上游失败要**抛**，不能返回空序列 —— 两条腿里任何一条空着，
    比值曲线就整个没有意义。让路由层决定是回退还是报错，别在这里静默降级。
    """
    try:
        frame = databull.get_index_history(index_code, start_compact, end_compact)
    except DataBullError as e:
        raise GrowthValueError(f'指数 {index_code} 取数失败: {e}') from e
    except Exception as e:  # noqa: BLE001
        raise GrowthValueError(f'指数 {index_code} 取数异常: {e}') from e

    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty or 'close' not in frame.columns:
        raise GrowthValueError(f'指数 {index_code} 无数据')

    close = pd.to_numeric(frame['close'], errors='coerce').astype('float64')
    # 上游日期有的带时区/时分秒，统一抹成 naive date，否则两条腿对齐时会因为
    # 00:00:00 与 .000000000 之类的差异对不上。
    close.index = pd.to_datetime(frame.index).normalize()
    close = close[~close.index.duplicated(keep='last')].sort_index()
    close.name = index_code
    return close.dropna()


class GrowthValueService:

    @staticmethod
    def get_series(days: int = DEFAULT_DAYS) -> Dict[str, Any]:
        """取「成长 ÷ 价值」比值序列。

        :param days: 返回最近 N 个**交易日**（1 个点/日），已按日期升序。
        :return: {meta, points, periods}
        """
        # ⚠️ 先转 int 再比区间，且转换失败要抛 GrowthValueError 而不是让
        # int('abc') 的 ValueError 漏出去 —— 路由层只捕获 GrowthValueError，
        # 漏出去会变成 500，而这是纯粹的入参问题、应该是 422。
        try:
            days = int(days)
        except (TypeError, ValueError) as e:
            raise GrowthValueError(f'days 必须是整数，收到 {days!r}') from e
        if days < MIN_DAYS or days > MAX_DAYS:
            raise GrowthValueError(f'days 需在 {MIN_DAYS}~{MAX_DAYS} 之间')

        end = datetime.now()
        start = end - timedelta(days=int(days * _WINDOW_FACTOR))
        start_compact, end_compact = _to_compact_date(start), _to_compact_date(end)

        growth = _fetch_close(GROWTH_CODE, start_compact, end_compact)
        value = _fetch_close(VALUE_CODE, start_compact, end_compact)

        # ⚠️ 用 inner join 对齐交易日，**不能 reindex + ffill**。
        # 两个指数的交易日理论上一致，但上游偶有单边缺一天（维护/停牌）。
        # ffill 会把缺的那天补成前一日收盘价、伪装成「比值没变」，凭空造出一个
        # 平坦点；inner join 则是干净地丢掉这天。后者的误差是「少一个采样点」，
        # 前者的误差是「伪造一段横盘」——后者危险得多。
        joined = pd.concat([growth.rename('growth'), value.rename('value')], axis=1, join='inner')
        joined = joined.dropna()
        if joined.empty:
            raise GrowthValueError('成长与价值两条指数没有共同交易日')

        joined = joined.tail(days)
        if joined.empty:
            raise GrowthValueError('对齐后无数据')

        # 归一化：以区间首日为 1.0，让两条腿可比（绝对点位量纲不同：创业板指
        # 三千点级、上证红利三千点级虽然接近，但比值看的是相对变化）。
        base_growth = float(joined['growth'].iloc[0])
        base_value = float(joined['value'].iloc[0])
        if base_growth <= 0 or base_value <= 0:
            raise GrowthValueError('基准日收盘价非法（<=0）')

        growth_norm = joined['growth'] / base_growth
        value_norm = joined['value'] / base_value
        ratio = growth_norm / value_norm  # 等价于 (成长/价值) 再按起点归一

        points: List[Dict[str, Any]] = []
        for dt, r in ratio.items():
            points.append({
                'trade_date': dt.strftime('%Y-%m-%d'),
                'ratio': round(float(r), 4),
                'growth_norm': round(float(growth_norm.loc[dt]), 4),
                'value_norm': round(float(value_norm.loc[dt]), 4),
                'growth_close': round(float(joined['growth'].loc[dt]), 2),
                'value_close': round(float(joined['value'].loc[dt]), 2),
            })

        return {
            'meta': {
                'growth_code': GROWTH_CODE,
                'growth_name': GROWTH_NAME,
                'value_code': VALUE_CODE,
                'value_name': VALUE_NAME,
                'start_date': points[0]['trade_date'],
                'end_date': points[-1]['trade_date'],
                'trade_days': len(points),
            },
            'points': points,
            'periods': GrowthValueService._periods(points),
        }

    @staticmethod
    def _periods(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """各区间比值涨跌幅（近 5 / 20 / 60 个交易日）。

        用**当前比值**与「N 个交易日前那个点」的比值相除 —— 因为比值本身已按
        区间首日归一，直接比就是该窗口内的相对强弱变化，不需要再除法。

        ⚠️ 取不到 N 个交易日前那个点时（比如只取了 20 个点却要算「近 20 日」），
        退化为「用区间最早那个点」而不是返回 None。返回 None 会让界面上出现一条
        恒为 `--` 的区间条，看起来像 bug —— 而实际上数据是够说明问题的
        （最早点到今天）。这是 days 取在下限附近时的常态。
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
