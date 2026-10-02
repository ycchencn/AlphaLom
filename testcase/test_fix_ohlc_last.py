"""
美股 / 港股 ohlc_last 为空的根因回归测试。

问题：job_fix_ohlc_last 调 databull.get_realtime 时没传 market，默认 'cn'，
导致美/港股走错实时行情路径、取不到数据、ohlc_last 恒为空。

本测试打桩 databull / StockService，验证「按市场走对路径」的路由逻辑：
- 美股（库内 market='us'）→ get_realtime(market='us')
- 港股（库内 market='hk'）→ get_realtime(market='hk')
- 未传 market 且无库记录 → 回退 'cn'
- 显式传 market → 不查库、直接用
- 返回无 lastPrice → 返回 False、不落库
"""
import os
import unittest
from unittest.mock import patch

# 测试默认不加载 .env.dev（load_env(None) 只尝试 .env.None），但本模块导入链会构造
# databull 客户端（需 DATABULL_KEY）。若环境变量里没有，则显式加载 .env.dev 兜底，
# 保证导入可行（与 dev 运行栈一致，且只是本地测试）。
if not os.environ.get('DATABULL_KEY'):
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path='.env.dev', override=False)
    except Exception:
        pass

import job.job_stock_daily_update as job_mod


def _fake_tick(last_price, last_close):
    return {
        'lastPrice': last_price,
        'lastClose': last_close,
        'open': last_price - 1,
        'high': last_price + 1,
        'low': last_price - 2,
        'amount': 12345,
    }


class TestFixOhlcLastMarket(unittest.TestCase):

    def test_us_stock_routes_to_us_market(self):
        tick = _fake_tick(150.0, 148.0)
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'us'}) as mock_get, \
                patch.object(job_mod.StockService, 'upsert_stock') as mock_upsert:
            mock_db.get_realtime.return_value = tick
            ok = job_mod.job_fix_ohlc_last('AAPL.US')

            args, kwargs = mock_db.get_realtime.call_args
            self.assertEqual(kwargs.get('symbol'), 'AAPL.US')
            self.assertEqual(kwargs.get('market'), 'us')
            self.assertTrue(ok)

            upserted = mock_upsert.call_args[0][0]
            self.assertEqual(upserted['symbol'], 'AAPL.US')
            self.assertEqual(upserted['ohlc_last']['close'], 150.0)
            self.assertAlmostEqual(
                upserted['ohlc_last']['chg_pct'],
                (150.0 - 148.0) / 148.0 * 100, places=4)

    def test_hk_stock_routes_to_hk_market(self):
        tick = _fake_tick(100.0, 99.0)
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'hk'}), \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_realtime.return_value = tick
            ok = job_mod.job_fix_ohlc_last('00700.HK')

            self.assertEqual(mock_db.get_realtime.call_args.kwargs.get('market'), 'hk')
            self.assertTrue(ok)

    def test_cn_default_when_no_market_record(self):
        tick = _fake_tick(10.0, 9.5)
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value=None), \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_realtime.return_value = tick
            ok = job_mod.job_fix_ohlc_last('600519')

            # 库内无记录 → 回退默认 cn（而不是 us/hk）
            self.assertEqual(mock_db.get_realtime.call_args.kwargs.get('market'), 'cn')
            self.assertTrue(ok)

    def test_explicit_market_overrides_lookup(self):
        tick = _fake_tick(10.0, 9.5)
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'cn'}) as mock_get, \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_realtime.return_value = tick
            ok = job_mod.job_fix_ohlc_last('AAPL.US', market='us')

            # 显式传入时不查库
            mock_get.assert_not_called()
            self.assertEqual(mock_db.get_realtime.call_args.kwargs.get('market'), 'us')
            self.assertTrue(ok)

    def test_missing_lastprice_returns_false(self):
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'us'}), \
                patch.object(job_mod.StockService, 'upsert_stock') as mock_upsert:
            mock_db.get_realtime.return_value = {}  # 无 lastPrice
            ok = job_mod.job_fix_ohlc_last('AAPL.US')

            self.assertFalse(ok)
            mock_upsert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
