"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

申万行业日快照（板块轮动图数据源）的回归测试。

重点钉住三类容易静默出错的地方：
  1. **幂等性** —— 队列是「至少一次」投递，同一 job 可能重投；日更任务重跑
     绝对不能产生重复行（主键冲突或行数翻倍都算缺陷）。
  2. **复合主键** —— (stat_date, sector_type, sector_name)。只声明 stat_date 会让
     ORM 把「同一天不同板块」当成同一行而静默去重（`stocks_fear_greed` 踩过）。
  3. **上游只给最新一天** —— 历史只能靠逐日累积，且 stat_date 不等于「今天」是正常的
     （周末/节假日跑拿到的是上一交易日），不能因此丢弃数据。

全部用例都不碰网络：上游调用一律打桩。
"""

import importlib
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ 不能用 `from job import job_update_sector_daily as job_mod`：
# job/__init__.py 里有 `from job.job_update_sector_daily import job_update_sector_daily`，
# 包属性会被同名**函数**覆盖 → 拿到的是函数而不是模块，job_mod._parse_stat_date 直接炸。
# 模块名与函数名同名是这类模块的固有陷阱，必须用 importlib 显式取模块对象。
job_mod = importlib.import_module('job.job_update_sector_daily')
from service.sector_daily_service import SectorDailyService, normalize_sector_type


class TestSectorTypeNormalize(unittest.TestCase):
    """sw1 / SW1 / Sw1 必须都归一成 DB 里存的 SW1；非法值必须返回 None。"""

    def test_case_insensitive(self):
        for raw in ('sw1', 'SW1', 'Sw1', ' sW1 '):
            self.assertEqual(normalize_sector_type(raw), 'SW1', raw)

    def test_all_levels(self):
        self.assertEqual(normalize_sector_type('sw2'), 'SW2')
        self.assertEqual(normalize_sector_type('sw3'), 'SW3')

    def test_invalid_returns_none(self):
        for raw in ('sw4', 'sw', '', None, '   ', 'l1'):
            self.assertIsNone(normalize_sector_type(raw), repr(raw))


class TestCompositePrimaryKey(unittest.TestCase):
    """主键必须三列齐全 —— 少任何一列都会让多行被静默合并成一行。"""

    def test_primary_key_columns(self):
        from models import SectorDailyStat
        pk = [c.name for c in SectorDailyStat.__table__.primary_key]
        self.assertEqual(set(pk), {'stat_date', 'sector_type', 'sector_name'},
                         '缺少复合主键列会导致 ORM 按主键去重、静默丢行')

    def test_stat_date_alone_is_not_enough(self):
        # 反向断言：如果哪天有人把主键改成只有 stat_date，这条会失败并提示原因
        from models import SectorDailyStat
        pk = [c.name for c in SectorDailyStat.__table__.primary_key]
        self.assertGreater(len(pk), 1,
                           '只声明 stat_date 做主键会让同日不同板块互相覆盖')


class TestStatDateParsing(unittest.TestCase):
    """上游 stat_date 形态不定，解析失败会整批丢数据，必须覆盖常见形态。"""

    def test_common_formats(self):
        f = job_mod._parse_stat_date
        d = date(2026, 9, 23)
        self.assertEqual(f('2026-09-23'), d)
        self.assertEqual(f('20260923'), d)
        self.assertEqual(f('2026/09/23'), d)

    def test_date_and_datetime_passthrough(self):
        from datetime import datetime
        f = job_mod._parse_stat_date
        self.assertEqual(f(date(2026, 9, 23)), date(2026, 9, 23))
        self.assertEqual(f(datetime(2026, 9, 23, 15, 0)), date(2026, 9, 23))

    def test_unparseable_returns_none(self):
        f = job_mod._parse_stat_date
        for raw in (None, '', 'garbage', '2026-13-45'):
            self.assertIsNone(f(raw), repr(raw))


class TestRowNormalize(unittest.TestCase):
    """上游字段 → DB 字段的映射，含几个「上游给了不可信值」的字段。"""

    def test_maps_all_fields(self):
        raw = {
            'id': 1, 'stat_date': '2026-09-23', 'sector_name': '电子', 'sector_type': 'SW1',
            'change_pct': '0.8', 'stock_count': 493, 'up_count': 282, 'down_count': 209,
            'flat_count': 2, 'up_down_ratio': 1.35, 'top_stock': '慧智微-U',
            'top_stock_pct': 20.03, 'bottom_stock': '华体科技', 'bottom_stock_pct': -10.0,
            'total_trade_amount': 4928.96, 'total_market_cap': 0.0, 'avg_turnover': 0.0,
        }
        row = job_mod._normalize_row(raw, date(2026, 9, 23), 'SW1')
        self.assertEqual(row['sector_name'], '电子')
        self.assertEqual(row['sector_type'], 'SW1')
        self.assertAlmostEqual(row['change_pct'], 0.8)
        self.assertEqual(row['stock_count'], 493)
        self.assertEqual(row['top_stock'], '慧智微-U')
        # 上游恒为 0 的字段不该被带进来
        self.assertNotIn('total_market_cap', row)
        self.assertNotIn('avg_turnover', row)
        self.assertNotIn('id', row)

    def test_missing_name_returns_none(self):
        self.assertIsNone(job_mod._normalize_row({'stat_date': '2026-09-23'}, date(2026, 9, 23), 'SW1'))

    def test_bad_numbers_become_none_not_crash(self):
        raw = {'sector_name': 'X', 'change_pct': 'N/A', 'stock_count': '', 'top_stock_pct': None}
        row = job_mod._normalize_row(raw, date(2026, 9, 23), 'SW1')
        self.assertIsNone(row['change_pct'])
        self.assertIsNone(row['stock_count'])
        self.assertIsNone(row['top_stock_pct'])


class TestJobIdempotency(unittest.TestCase):
    """任务重跑不能产生重复行 —— 这是队列「至少一次」语义的硬要求。"""

    def setUp(self):
        self.calls = []

    def _fake_data(self):
        return [
            {'stat_date': '2026-09-23', 'sector_name': '电子', 'sector_type': 'SW1',
             'change_pct': 0.8, 'stock_count': 493, 'up_count': 282, 'down_count': 209,
             'flat_count': 2, 'up_down_ratio': 1.35, 'top_stock': 'A', 'top_stock_pct': 1.0,
             'bottom_stock': 'B', 'bottom_stock_pct': -1.0, 'total_trade_amount': 100.0},
            {'stat_date': '2026-09-23', 'sector_name': '银行', 'sector_type': 'SW1',
             'change_pct': -0.43, 'stock_count': 42, 'up_count': 10, 'down_count': 30,
             'flat_count': 2, 'up_down_ratio': 0.33, 'top_stock': 'C', 'top_stock_pct': 2.0,
             'bottom_stock': 'D', 'bottom_stock_pct': -3.0, 'total_trade_amount': 50.0},
        ]

    def test_calls_upsert_once_per_type(self):
        with patch.object(job_mod.databull, 'get_sector_data', return_value=self._fake_data()):
            with patch.object(job_mod.SectorDailyService, 'upsert_daily',
                              side_effect=lambda rows: self.calls.append(rows) or len(rows)) as m:
                summary = job_mod.job_update_sector_daily()
        # 三个级别各调一次
        self.assertEqual(m.call_count, 3)
        self.assertEqual(summary, {'SW1': 2, 'SW2': 2, 'SW3': 2})
        # 每次写入的行数等于上游行数（未翻倍）
        for rows in self.calls:
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({(r['stat_date'], r['sector_type'], r['sector_name']) for r in rows}), 2,
                             '同一批里出现了重复主键')

    def test_partial_failure_does_not_abort_other_types(self):
        """某个级别取数失败时，其它级别仍要落库。"""
        def flaky(sector_type):
            if sector_type == 'sw2':
                raise RuntimeError('上游 500')
            return self._fake_data()

        with patch.object(job_mod.databull, 'get_sector_data', side_effect=flaky):
            with patch.object(job_mod.SectorDailyService, 'upsert_daily',
                              side_effect=lambda rows: len(rows)) as m:
                summary = job_mod.job_update_sector_daily()

        self.assertEqual(summary['SW2'], 0, '失败级别应记 0 而不是抛出去')
        self.assertEqual(summary['SW1'], 2, 'SW1 不该被 SW2 的失败拖垮')
        self.assertEqual(summary['SW3'], 2)

    def test_empty_upstream_is_skipped(self):
        with patch.object(job_mod.databull, 'get_sector_data', return_value=[]):
            with patch.object(job_mod.SectorDailyService, 'upsert_daily') as m:
                summary = job_mod.job_update_sector_daily(sector_types=['sw1'])
        m.assert_not_called()
        self.assertEqual(summary, {'SW1': 0})

    def test_all_rows_unparseable_is_skipped(self):
        """整批 stat_date 都解析不出来时不应写空数据。"""
        with patch.object(job_mod.databull, 'get_sector_data',
                          return_value=[{'stat_date': 'garbage', 'sector_name': 'X'}]):
            with patch.object(job_mod.SectorDailyService, 'upsert_daily') as m:
                summary = job_mod.job_update_sector_daily(sector_types=['sw1'])
        m.assert_not_called()
        self.assertEqual(summary, {'SW1': 0})


class TestRotationRanks(unittest.TestCase):
    """轮动排名矩阵：按日分组、涨跌幅降序、rank 从 1 开始。"""

    def _row(self, d, name, pct):
        return {'stat_date': d.isoformat(), 'sector_type': 'SW1', 'sector_name': name,
                'change_pct': pct, 'stock_count': 1, 'up_count': 1, 'down_count': 0,
                'flat_count': 0, 'up_down_ratio': 1.0, 'top_stock': '', 'top_stock_pct': 0,
                'bottom_stock': '', 'bottom_stock_pct': 0, 'total_trade_amount': 0}

    def test_ranks_sorted_desc_per_day(self):
        d1, d2 = date(2026, 9, 22), date(2026, 9, 23)
        rows = [
            self._row(d1, '甲', -1.0), self._row(d1, '乙', 2.0), self._row(d1, '丙', 0.5),
            self._row(d2, '甲', 3.0), self._row(d2, '乙', -0.5), self._row(d2, '丙', 1.0),
        ]
        with patch.object(SectorDailyService, 'get_history', return_value=rows):
            out = SectorDailyService.get_rotation_ranks('sw1', limit_days=10)

        self.assertEqual([d['trade_date'] for d in out], ['2026-09-22', '2026-09-23'],
                         '日期必须升序')
        # 第一天：乙(2.0) > 丙(0.5) > 甲(-1.0)
        self.assertEqual([r['sector_name'] for r in out[0]['ranks']], ['乙', '丙', '甲'])
        self.assertEqual([r['rank'] for r in out[0]['ranks']], [1, 2, 3])
        # 第二天：甲(3.0) > 丙(1.0) > 乙(-0.5)
        self.assertEqual([r['sector_name'] for r in out[1]['ranks']], ['甲', '丙', '乙'])

    def test_same_name_can_move_between_days(self):
        """轮动图的本质：同一板块的名次每天在变。"""
        d1, d2 = date(2026, 9, 22), date(2026, 9, 23)
        rows = [self._row(d1, '甲', 5.0), self._row(d1, '乙', 1.0),
                self._row(d2, '甲', -5.0), self._row(d2, '乙', 1.0)]
        with patch.object(SectorDailyService, 'get_history', return_value=rows):
            out = SectorDailyService.get_rotation_ranks('sw1', limit_days=10)
        self.assertEqual(out[0]['ranks'][0]['sector_name'], '甲')
        self.assertEqual(out[1]['ranks'][-1]['sector_name'], '甲')

    def test_empty_history_returns_empty(self):
        with patch.object(SectorDailyService, 'get_history', return_value=[]):
            self.assertEqual(SectorDailyService.get_rotation_ranks('sw1'), [])

    def test_none_change_pct_sorted_last(self):
        """涨跌幅缺失的板块排到最后，不能因为 None 比较而崩。"""
        d1 = date(2026, 9, 22)
        rows = [self._row(d1, '甲', None), self._row(d1, '乙', -3.0)]
        with patch.object(SectorDailyService, 'get_history', return_value=rows):
            out = SectorDailyService.get_rotation_ranks('sw1', limit_days=10)
        self.assertEqual(out[0]['ranks'][0]['sector_name'], '乙')
        self.assertEqual(out[0]['ranks'][-1]['sector_name'], '甲')


class TestReadGuards(unittest.TestCase):
    """非法级别的读操作必须返回空而不是抛异常（接口层再转 400）。"""

    def test_get_by_date_invalid_type(self):
        self.assertEqual(SectorDailyService.get_by_date(date(2026, 9, 23), 'bogus'), [])

    def test_get_history_invalid_type(self):
        self.assertEqual(SectorDailyService.get_history('bogus'), [])


if __name__ == '__main__':
    unittest.main()
