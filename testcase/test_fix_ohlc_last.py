"""
美股 / 港股 ohlc_last 为空的根因回归测试。

问题：databull 的实时接口（/us/stock/tick、/hk/stock/tick）不提供美股/港股数据，
因此 job_fix_ohlc_last 对美/港股不能走 get_realtime，必须改用日线接口
（get_us_stock_history / get_hk_stock_history）取最新一根 K 线，并映射成与
A 股 get_realtime 同构的 ohlc_last（lastPrice / lastClose / close / chg_pct …）。

本测试打桩 databull / StockService，验证「按市场走对路径 + 格式对齐」：
- 美股（market='us'）→ get_us_stock_history，构造出含 lastPrice/lastClose/chg_pct 的 ohlc_last
- 港股（market='hk'）→ get_hk_stock_history
- 美股代码带 .US 后缀 → 调日线前剥后缀
- A 股（market='cn'）→ 仍走 get_realtime（原有逻辑不变）
- 库内无记录且未传 market → 回退 'cn'
- 日线返回空（None）→ 返回 False、不落库
"""
import os
import unittest
from unittest.mock import patch

import pandas as pd

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


def _fake_daily(close, prev_close, ts=1790726400000):
    """构造两行日线，最后一行收盘=close、上一行收盘=prev_close。"""
    return pd.DataFrame([
        {
            'date': '2026-09-29', 'open': prev_close - 1, 'close': prev_close,
            'high': prev_close + 1, 'low': prev_close - 1, 'volume': 100,
            'change_amount': 0.0, 'chg_pct': 0.0, 'timestamp': ts - 86400000,
        },
        {
            'date': '2026-09-30', 'open': prev_close + 0.5, 'close': close,
            'high': close + 1, 'low': prev_close, 'volume': 200,
            'change_amount': close - prev_close,
            'chg_pct': (close - prev_close) / prev_close * 100,
            'timestamp': ts,
        },
    ]).set_index('date')


class TestFixOhlcLastMarket(unittest.TestCase):

    def test_us_stock_uses_daily_history(self):
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'us'}), \
                patch.object(job_mod.StockService, 'upsert_stock') as mock_upsert:
            mock_db.get_us_stock_history.return_value = _fake_daily(333.02, 329.40)
            ok = job_mod.job_fix_ohlc_last('AAPL')

            # 必须走日线接口，而不是 get_realtime
            mock_db.get_us_stock_history.assert_called_once()
            mock_db.get_realtime.assert_not_called()
            self.assertEqual(
                mock_db.get_us_stock_history.call_args.args[0], 'AAPL')
            self.assertTrue(ok)

            upserted = mock_upsert.call_args[0][0]
            ohlc = upserted['ohlc_last']
            self.assertEqual(upserted['symbol'], 'AAPL')
            self.assertEqual(ohlc['lastPrice'], 333.02)
            self.assertAlmostEqual(ohlc['lastClose'], 329.40)
            self.assertAlmostEqual(
                ohlc['chg_pct'], (333.02 - 329.40) / 329.40 * 100, places=4)
            self.assertEqual(ohlc['close'], 333.02)

    def test_us_symbol_suffix_stripped(self):
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'us'}), \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_us_stock_history.return_value = _fake_daily(333.02, 329.40)
            ok = job_mod.job_fix_ohlc_last('AAPL.US')

            self.assertEqual(
                mock_db.get_us_stock_history.call_args.args[0], 'AAPL')
            self.assertTrue(ok)

    def test_hk_stock_uses_daily_history(self):
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'hk'}), \
                patch.object(job_mod.StockService, 'upsert_stock') as mock_upsert:
            mock_db.get_hk_stock_history.return_value = _fake_daily(431.0, 432.0)
            ok = job_mod.job_fix_ohlc_last('00005')

            mock_db.get_hk_stock_history.assert_called_once()
            mock_db.get_realtime.assert_not_called()
            self.assertEqual(
                mock_db.get_hk_stock_history.call_args.args[0], '00005')
            self.assertTrue(ok)

            ohlc = mock_upsert.call_args[0][0]['ohlc_last']
            self.assertEqual(ohlc['lastPrice'], 431.0)
            self.assertAlmostEqual(ohlc['lastClose'], 432.0)

    def test_cn_still_uses_realtime(self):
        tick = _fake_tick(10.0, 9.5)
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'cn'}), \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_realtime.return_value = tick
            ok = job_mod.job_fix_ohlc_last('600519')

            mock_db.get_realtime.assert_called_once()
            mock_db.get_us_stock_history.assert_not_called()
            mock_db.get_hk_stock_history.assert_not_called()
            self.assertEqual(mock_db.get_realtime.call_args.kwargs.get('market'), 'cn')
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
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'cn'}) as mock_get, \
                patch.object(job_mod.StockService, 'upsert_stock'):
            mock_db.get_us_stock_history.return_value = _fake_daily(333.02, 329.40)
            ok = job_mod.job_fix_ohlc_last('AAPL', market='us')

            # 显式传入时不查库
            mock_get.assert_not_called()
            mock_db.get_us_stock_history.assert_called_once()
            self.assertTrue(ok)

    def test_empty_daily_returns_false(self):
        with patch.object(job_mod, 'databull') as mock_db, \
                patch.object(job_mod.StockService, 'get_stock_by_symbol',
                             return_value={'market': 'us'}), \
                patch.object(job_mod.StockService, 'upsert_stock') as mock_upsert:
            mock_db.get_us_stock_history.return_value = None  # 无数据
            ok = job_mod.job_fix_ohlc_last('AAPL')

            self.assertFalse(ok)
            mock_upsert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
