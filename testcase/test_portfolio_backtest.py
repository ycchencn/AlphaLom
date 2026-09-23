"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

组合回测（等权买入持有）的测试。

分两类：
- **纯计算**：不碰网络的入参归一化与绩效指标（手工构造净值序列，能钉住算法本身）。
- **集成**：打真上游跑一次完整回测，验证取数 → 对齐 → 组合 → 基准这条链路。
  这类用例依赖网络与上游数据，偶发失败先看是不是上游抖动，不要直接改断言。
"""

import unittest

import pandas as pd

from service.portfolio_backtest_service import (
    MAX_SYMBOLS,
    BacktestError,
    PortfolioBacktestService,
    _max_drawdown_detail,
    _normalize_symbols,
    _performance_metrics,
    _to_compact_date,
)


class TestParamNormalization(unittest.TestCase):
    """入参归一化：这是唯一能在打上游之前拦下脏入参的地方。"""

    def test_normalize_symbols_dedup_and_suffix(self):
        # 带交易所后缀要去掉、重复项要去重、顺序要保持（前端按顺序展示 chips）
        self.assertEqual(_normalize_symbols('600519.SH, 600519 ,510300'), ['600519', '510300'])
        self.assertEqual(_normalize_symbols(['000001', '000001']), ['000001'])
        # 中文逗号也要能吃下（用户从别处粘贴常见）
        self.assertEqual(_normalize_symbols('600519，510300'), ['600519', '510300'])

    def test_normalize_symbols_rejects_bad_format(self):
        for bad in ('ABCDEF', '12345', '1234567', '60051X'):
            with self.assertRaises(BacktestError, msg=bad):
                _normalize_symbols(bad)

    def test_normalize_symbols_rejects_empty(self):
        for empty in ('', None, [], '  ,  '):
            with self.assertRaises(BacktestError):
                _normalize_symbols(empty)

    def test_normalize_symbols_caps_count(self):
        too_many = ','.join(f'{600000 + i}' for i in range(MAX_SYMBOLS + 1))
        with self.assertRaises(BacktestError):
            _normalize_symbols(too_many)
        # 恰好等于上限要放行（别把边界也拦了）
        self.assertEqual(len(_normalize_symbols(','.join(f'{600000 + i}' for i in range(MAX_SYMBOLS)))), MAX_SYMBOLS)

    def test_to_compact_date(self):
        self.assertEqual(_to_compact_date('2025-01-02', '起始日期'), '20250102')
        self.assertEqual(_to_compact_date('2025/01/02', '起始日期'), '20250102')
        self.assertEqual(_to_compact_date('20250102', '起始日期'), '20250102')
        for bad in ('2025-1-2x', '202501', '', None):
            with self.assertRaises(BacktestError, msg=repr(bad)):
                _to_compact_date(bad, '起始日期')


class TestPerformanceMetrics(unittest.TestCase):
    """绩效指标：手工构造净值序列，逐个指标钉死。

    equity 序列刻意设计成「先涨到 1.2 → 跌到 0.9（-25%）→ 再涨到 1.3 并修复」，
    覆盖最大回撤的「峰 → 谷 → 修复」三段。
    """

    @staticmethod
    def _equity():
        return pd.Series(
            [1.0, 1.2, 0.9, 1.1, 1.3],
            index=pd.date_range('2025-01-01', periods=5, freq='D'),
            dtype='float64',
        )

    def test_total_and_annual_return(self):
        m = _performance_metrics(self._equity())
        self.assertAlmostEqual(m['total_return'], 0.3, places=10)
        self.assertEqual(m['trading_days'], 5)
        self.assertEqual(m['span_days'], 4)
        # 年化按自然日跨度折算：4 天涨 30% 会年化成一个很大的数（原样算，不封顶）
        self.assertAlmostEqual(m['annual_return'], 1.3 ** (365.25 / 4) - 1, places=6)

    def test_max_drawdown_peak_trough_recovery(self):
        eq = self._equity()
        detail = _max_drawdown_detail(eq)
        self.assertAlmostEqual(detail['value'], -0.25, places=10)   # 1.2 -> 0.9
        self.assertEqual(detail['start'], '2025-01-02')             # 峰值日
        self.assertEqual(detail['end'], '2025-01-03')               # 谷底日
        self.assertEqual(detail['recovery'], '2025-01-05')          # 首次回到 1.2 以上

    def test_max_drawdown_unrecovered(self):
        # 一路新高后回落且再没回去 -> recovery 必须是 None，不能瞎填一个日期
        eq = pd.Series([1.0, 1.5, 1.2, 1.3],
                       index=pd.date_range('2025-01-01', periods=4, freq='D'), dtype='float64')
        detail = _max_drawdown_detail(eq)
        self.assertEqual(detail['start'], '2025-01-02')
        self.assertEqual(detail['end'], '2025-01-03')
        self.assertIsNone(detail['recovery'])

    def test_win_rate_and_zero_volatility(self):
        m = _performance_metrics(self._equity())
        # 日收益 [0.2, -0.25, 2/9, 2/11] -> 3 正 1 负
        self.assertAlmostEqual(m['win_rate'], 0.75, places=10)

        # 净值完全不动：波动率为 0，夏普必须返回 0 而不是 inf/NaN
        flat = pd.Series([1.0] * 5,
                         index=pd.date_range('2025-01-01', periods=5, freq='D'), dtype='float64')
        fm = _performance_metrics(flat)
        self.assertEqual(fm['volatility'], 0.0)
        self.assertEqual(fm['sharpe'], 0.0)
        self.assertEqual(fm['max_drawdown'], 0.0)
        self.assertEqual(fm['calmar'], 0.0)

    def test_rejects_too_short_series(self):
        one = pd.Series([1.0], index=pd.date_range('2025-01-01', periods=1), dtype='float64')
        with self.assertRaises(BacktestError):
            _performance_metrics(one)


class TestBacktestIntegration(unittest.TestCase):
    """打真上游的集成用例。上游抖动导致的失败不要靠改断言绕过。"""

    def test_single_stock(self):
        r = PortfolioBacktestService.run('600519', start_date='2025-01-01', end_date='2026-09-22')
        meta, series, metrics = r['meta'], r['series'], r['metrics']

        self.assertEqual(meta['symbols'], ['600519'])
        self.assertEqual(meta['weight_per_symbol'], 1.0)
        self.assertEqual(r['skipped'], [])

        # 净值序列基本不变量
        n = len(series['dates'])
        self.assertGreater(n, 200)
        for key in ('equity', 'drawdown', 'benchmark_equity', 'benchmark_drawdown'):
            self.assertEqual(len(series[key]), n, f'{key} 与 dates 长度不一致')
        self.assertAlmostEqual(series['equity'][0], 1.0, places=9)
        self.assertAlmostEqual(series['benchmark_equity'][0], 1.0, places=9)
        self.assertTrue(all(v <= 1e-9 for v in series['drawdown']), '回撤序列出现正值')

        # 单只等权组合：组合收益必须恰好等于该只标的的区间收益
        self.assertAlmostEqual(metrics['total_return'], r['holdings'][0]['total_return'], places=10)
        self.assertEqual(metrics['trading_days'], n)

    def test_stock_and_etf_mixed_contribution_is_additive(self):
        r = PortfolioBacktestService.run(
            '600519,510300,159915', start_date='2024-01-01', end_date='2026-09-22'
        )
        self.assertEqual(len(r['holdings']), 3)
        self.assertAlmostEqual(r['meta']['weight_per_symbol'], 1 / 3, places=9)

        # 权重不做 round，Σweight 必须精确等于 1（前端「贡献 = 权重 × 区间收益」依赖这一点）
        self.assertAlmostEqual(sum(h['weight'] for h in r['holdings']), 1.0, places=12)

        # 等权买入持有下「Σ(权重 × 单只收益) == 组合总收益」是恒等式，
        # 这条断言能一次性兜住归一化 / 权重 / 对齐三处的静默错误
        self.assertAlmostEqual(
            sum(h['contribution'] for h in r['holdings']),
            r['metrics']['total_return'],
            places=10,
        )

        # 个股与 ETF 走的是两个不同端点，两者都要真的取到数
        asset_types = {h['symbol']: h['asset_type'] for h in r['holdings']}
        self.assertEqual(asset_types['600519'], 'stock')
        self.assertEqual(asset_types['510300'], 'etf')
        self.assertEqual(asset_types['159915'], 'etf')

    def test_invalid_symbol_is_skipped_not_fatal(self):
        r = PortfolioBacktestService.run('600519,999998', start_date='2025-01-01', end_date='2026-09-22')
        # 无效代码不能拖垮整次回测：剔除它，等权在可用标的上重新分配
        self.assertEqual(r['meta']['symbols'], ['600519'])
        self.assertEqual(r['meta']['weight_per_symbol'], 1.0)
        self.assertEqual([s['symbol'] for s in r['skipped']], ['999998'])
        self.assertTrue(any('剔除' in w for w in r['warnings']))

    def test_benchmark_can_be_disabled(self):
        r = PortfolioBacktestService.run('510300', start_date='2025-01-01', end_date='2026-09-22',
                                         benchmark='')
        self.assertIsNone(r['meta']['benchmark'])
        self.assertIsNone(r['benchmark_metrics'])
        self.assertEqual(r['series']['benchmark_equity'], [])

    def test_rejects_reversed_date_range(self):
        with self.assertRaises(BacktestError):
            PortfolioBacktestService.run('600519', start_date='2026-01-01', end_date='2025-01-01')

    def test_rejects_no_data_at_all(self):
        with self.assertRaises(BacktestError):
            PortfolioBacktestService.run('999998')


if __name__ == '__main__':
    unittest.main()
