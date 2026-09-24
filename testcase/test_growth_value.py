"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

「成长 vs 价值」比值（创业板指 ÷ 上证红利）的回归测试。

重点钉住三类容易静默出错的地方：
  1. **对齐方式必须是 inner join** —— 两条指数单边缺一天时，reindex+ffill 会把
     缺的那天补成前一日收盘价、伪造出一段「比值没变」的横盘，看上去像真实行情。
     inner join 是干净地少一个采样点。二者在图上很难分辨，但后者是假数据。
  2. **归一化基准必须是区间首日** —— 比值本身没有绝对高低含义，起点的选择
     直接决定「>1 叫成长占优」是否成立。若误用 1.0 或最后一日做基准，
     整个卡片的方向判断会反。
  3. **区间涨跌幅的窗口对齐** —— 「近 5 日」必须是「今天 vs 5 个交易日前」，
     不是「今天 vs 第 5 个点」（差一位就整体偏移一天）。

全部用例都不碰网络：上游 `get_index_history` 一律打桩。
"""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.growth_value_service import (  # noqa: E402
    GROWTH_CODE,
    MAX_DAYS,
    MIN_DAYS,
    VALUE_CODE,
    GrowthValueError,
    GrowthValueService,
)


def _frame(dates, closes):
    """造一个和上游 get_index_history 同构的 DataFrame（索引名为 date）。"""
    idx = pd.to_datetime(dates)
    df = pd.DataFrame({'close': closes, 'open': closes, 'high': closes, 'low': closes},
                      index=idx)
    df.index.name = 'date'
    return df


def _patch_history(mapping):
    """按 index_code 分派返回值；mapping 里没有的代码返回空 DataFrame。"""
    def _fake(index_code, start, end):
        return mapping.get(index_code, pd.DataFrame())
    return patch('service.growth_value_service.databull.get_index_history', side_effect=_fake)


class TestGrowthValueRatio(unittest.TestCase):

    def test_basic_ratio_and_normalization(self):
        """起点归一为 1.0；比值 = 两条腿归一化净值之比。"""
        dates = ['2026-09-01', '2026-09-02', '2026-09-03']
        growth = _frame(dates, [100.0, 110.0, 120.0])   # 归一后 1.0 / 1.1 / 1.2
        value = _frame(dates, [200.0, 200.0, 240.0])    # 归一后 1.0 / 1.0 / 1.2

        with _patch_history({GROWTH_CODE: growth, VALUE_CODE: value}):
            d = GrowthValueService.get_series(days=MIN_DAYS)

        pts = d['points']
        self.assertEqual(len(pts), 3)
        # 首日两个基准都归一为 1.0 → 比值必为 1.0
        self.assertAlmostEqual(pts[0]['ratio'], 1.0, places=4)
        self.assertAlmostEqual(pts[0]['growth_norm'], 1.0, places=4)
        self.assertAlmostEqual(pts[0]['value_norm'], 1.0, places=4)
        # 次日：成长 1.1 / 红利 1.0 → 成长跑赢（比值 > 1）
        self.assertAlmostEqual(pts[1]['ratio'], 1.1, places=4)
        self.assertGreater(pts[1]['ratio'], 1.0)
        # 第三日：1.2 / 1.2 → 回到 1.0（同步上涨，相对强弱不变）
        self.assertAlmostEqual(pts[2]['ratio'], 1.0, places=4)

    def test_ratio_moves_with_growth_not_with_absolute_level(self):
        """比值只反映**相对**强弱：两条腿同涨同跌时比值不动。"""
        dates = ['2026-09-01', '2026-09-02']
        growth = _frame(dates, [100.0, 150.0])
        value = _frame(dates, [100.0, 150.0])

        with _patch_history({GROWTH_CODE: growth, VALUE_CODE: value}):
            pts = GrowthValueService.get_series(days=MIN_DAYS)['points']

        self.assertAlmostEqual(pts[-1]['ratio'], 1.0, places=4)

    def test_inner_join_drops_unmatched_day(self):
        """两条腿缺的交易日不一致时，取交集——绝不能 ffill 补出假平点。"""
        g_dates = ['2026-09-01', '2026-09-02', '2026-09-03']
        v_dates = ['2026-09-01', '2026-09-03']          # 少 09-02
        growth = _frame(g_dates, [100.0, 200.0, 300.0])
        value = _frame(v_dates, [100.0, 300.0])

        with _patch_history({GROWTH_CODE: growth, VALUE_CODE: value}):
            pts = GrowthValueService.get_series(days=MIN_DAYS)['points']

        got = [p['trade_date'] for p in pts]
        self.assertEqual(got, ['2026-09-01', '2026-09-03'],
                         '必须只保留共同交易日；出现 09-02 说明被 ffill 补了假点')
        # 09-03 比值应为 3.0/3.0 = 1.0（双方都涨 3 倍），而不是拿 09-02 的假值算
        self.assertAlmostEqual(pts[-1]['ratio'], 1.0, places=4)

    def test_tail_limits_points(self):
        """days 限制返回的**交易日**个数（从尾部取）。"""
        dates = pd.date_range('2026-01-01', periods=120, freq='B').strftime('%Y-%m-%d').tolist()
        closes = [100.0 + i for i in range(120)]
        with _patch_history({GROWTH_CODE: _frame(dates, closes),
                             VALUE_CODE: _frame(dates, closes)}):
            pts = GrowthValueService.get_series(days=MIN_DAYS)['points']
        self.assertEqual(len(pts), MIN_DAYS)
        self.assertEqual(pts[-1]['trade_date'], dates[-1])


class TestGrowthValuePeriods(unittest.TestCase):
    """区间涨跌幅：窗口必须对齐到「N 个交易日前」，不能差一位。"""

    def test_period_change_uses_exact_lag(self):
        dates = pd.date_range('2026-01-01', periods=30, freq='B').strftime('%Y-%m-%d').tolist()
        # 成长每天 +1%，红利不动 → 比值每天相对前一天 +1%，但相对区间首日持续走高
        growth = _frame(dates, [100.0 * (1.01 ** i) for i in range(30)])
        value = _frame(dates, [100.0] * 30)

        with _patch_history({GROWTH_CODE: growth, VALUE_CODE: value}):
            pts = GrowthValueService.get_series(days=MIN_DAYS)['points']

        periods = GrowthValueService._periods(pts)
        by_days = {p['days']: p['change_pct'] for p in periods}
        # 近 5 日：最近点比值 / 倒数第 6 个点比值
        expect_5 = (pts[-1]['ratio'] / pts[-1 - 5]['ratio'] - 1) * 100
        self.assertAlmostEqual(by_days[5], round(expect_5, 2), places=2)
        # 单调上涨的比值，近 20 日涨幅应大于近 5 日
        self.assertGreater(by_days[20], by_days[5])

    def test_period_falls_back_to_earliest_point(self):
        """窗口点数不足时退化为「最早点 → 今天」，而不是返回 None。

        否则 days 取在下限（20）附近时，界面会出现一条恒为 `--` 的近 20 日区间条，
        看起来像 bug，而实际上数据足以说明问题。
        """
        dates = ['2026-09-01', '2026-09-02']
        pts = [{'trade_date': d, 'ratio': r} for d, r in zip(dates, [0.8, 1.2])]
        out = GrowthValueService._periods(pts)
        self.assertTrue(all(p['change_pct'] is not None for p in out),
                        '点数不足时不应返回 None')
        for p in out:
            # 两个点都不足以覆盖 5/20/60 日 → 全部退化为「最早点→今天」
            expect = round((1.2 / 0.8 - 1) * 100, 2)
            self.assertAlmostEqual(p['change_pct'], expect, places=2)


class TestGrowthValueValidation(unittest.TestCase):

    def test_rejects_out_of_range_days(self):
        for bad in (MIN_DAYS - 1, MAX_DAYS + 1, 0, -5):
            with self.assertRaises(GrowthValueError, msg=repr(bad)):
                GrowthValueService.get_series(days=bad)

    def test_rejects_non_integer_days(self):
        """非整数入参必须是 GrowthValueError（→422），不能漏成 ValueError（→500）。"""
        for bad in ('abc', None, [1]):
            with self.assertRaises(GrowthValueError, msg=repr(bad)):
                GrowthValueService.get_series(days=bad)

    def test_raises_when_one_leg_empty(self):
        """任何一条腿空着都要抛 —— 静默降级会让比值曲线整个失去意义。"""
        dates = ['2026-09-01', '2026-09-02']
        with _patch_history({GROWTH_CODE: _frame(dates, [100.0, 101.0]),
                             VALUE_CODE: pd.DataFrame()}):
            with self.assertRaises(GrowthValueError):
                GrowthValueService.get_series(days=MIN_DAYS)

    def test_raises_when_no_common_trading_day(self):
        g = _frame(['2026-09-01', '2026-09-02'], [100.0, 101.0])
        v = _frame(['2026-08-03', '2026-08-04'], [200.0, 201.0])
        with _patch_history({GROWTH_CODE: g, VALUE_CODE: v}):
            with self.assertRaises(GrowthValueError):
                GrowthValueService.get_series(days=MIN_DAYS)


if __name__ == '__main__':
    unittest.main()
