"""
对外股票数据接口（/api/ext/stocks/*）测试。

覆盖：
- 鉴权：无 Key / 错误 Key → 401（真实依赖，不覆盖）。
- 股票池：/stocks/pools（分组列表）、/stocks/pools/{group}（成员）、/stocks/watchlist（扁平）。
- 个股分析：/stocks/{symbol}/fundamentals、/factors、/fear-greed（DB 驱动，无网络）。
- /stocks/{symbol}/financials、/analysis：打桩 databull，避免依赖外网。

约定：用 dev 运行栈（DATABULL_KEY 来自 .env.dev），数据依赖 ycchen(user_id=21) 的池子。
"""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

# 测试默认不加载 .env.dev，但本模块导入链会构造 databull 客户端（需 DATABULL_KEY）。
# 若环境变量里没有，则显式加载 .env.dev 兜底，保证导入可行。
if not os.environ.get('DATABULL_KEY'):
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path='.env.dev', override=False)
    except Exception:
        pass

from app.external_api import create_external_app
from utils.api_auth import require_api_user
import routes.external_stock as ext_stock


# ycchen 的 user_id（见 .workbuddy/memory 约定）
YC_USER_ID = 21


def _fake_profile(symbol, *args, **kwargs):
    return {'code': 0, 'data': {'stock_code': symbol, 'company_name': '测试公司'}}


def _fake_financial(*args, **kwargs):
    return {
        'code': 0,
        'data': [
            {'report_table': {'report_date': '20260630', 'eps': 1.23}, 'report_type': 'PershareIndex'},
            {'report_table': {'report_date': '20260331', 'eps': 1.10}, 'report_type': 'PershareIndex'},
        ],
    }


class ExternalStockTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_external_app()
        # 数据端点统一用 ycchen 的身份（模拟已通过 API Key 鉴权）
        cls.app.dependency_overrides[require_api_user] = lambda: YC_USER_ID
        cls.client = TestClient(cls.app)

    # ---------------- 鉴权 ----------------
    def test_no_auth_returns_401(self):
        # 新建一个不带 dependency override 的 client，走真实鉴权链路
        raw_app = create_external_app()
        raw_client = TestClient(raw_app)
        r = raw_client.get('/stocks/pools')
        self.assertEqual(r.status_code, 401)

    def test_bad_key_returns_401(self):
        raw_app = create_external_api_clean()
        raw_client = TestClient(raw_app)
        r = raw_client.get('/stocks/pools', headers={'X-API-Key': 'flp_bogus'})
        self.assertEqual(r.status_code, 401)

    # ---------------- 股票池 ----------------
    def test_list_pools(self):
        r = self.client.get('/stocks/pools')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, list)
        # 至少应有一个分组，且每组含 group_name / count
        self.assertTrue(any(d.get('group_name') for d in data))
        for d in data:
            self.assertIn('count', d)

    def test_pool_members_by_group(self):
        # 取一个真实存在的分组名，验证成员列表
        pools = self.client.get('/stocks/pools').json()
        target = pools[0]['group_name']
        r = self.client.get(f'/stocks/pools/{target}')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        self.assertIn('symbol', data[0])

    def test_pool_members_ungrouped(self):
        r = self.client.get('/stocks/pools/__ungrouped__')
        self.assertEqual(r.status_code, 200)
        # 未分组桶返回的是列表（可能为空，但不应报错）
        self.assertIsInstance(r.json(), list)

    def test_watchlist(self):
        r = self.client.get('/stocks/watchlist')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        first = data[0]
        # 扁平列表应包含的核心字段
        for key in ('symbol', 'name', 'market', 'group_name', 'ohlc_last'):
            self.assertIn(key, first)
        # 批量注入的分析字段
        self.assertIn('fear_greed', first)
        self.assertIn('main_force_behavior_phase', first)

    # ---------------- 个股分析（DB 驱动，无网络） ----------------
    def test_fundamentals(self):
        r = self.client.get('/stocks/600519/fundamentals')
        self.assertEqual(r.status_code, 200)
        # 不存在的票返回 null，不应 500
        r2 = self.client.get('/stocks/000000/fundamentals')
        self.assertEqual(r2.status_code, 200)

    def test_factors(self):
        r = self.client.get('/stocks/600519/factors')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('symbol', data)
        self.assertIn('dashboard', data)
        self.assertIn('board', data)

    def test_fear_greed(self):
        r = self.client.get('/stocks/600519/fear-greed')
        self.assertEqual(r.status_code, 200)
        # 返回记录或 null
        self.assertIn('trade_date', r.json() or {})

    # ---------------- 个股分析（打桩 databull，避免外网） ----------------
    def test_financials_stubbed(self):
        with patch.object(ext_stock.databull, 'get_stock_financial_data',
                          side_effect=_fake_financial):
            r = self.client.get('/stocks/600519/financials',
                                params={'report_type': 'PershareIndex', 'periods': 4})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['symbol'], '600519')
        self.assertEqual(data['report_type'], 'PershareIndex')
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['items'][0]['report_date'], '2026-06-30')

    def test_financials_invalid_report_type(self):
        r = self.client.get('/stocks/600519/financials',
                            params={'report_type': 'Bogus'})
        self.assertEqual(r.status_code, 400)

    def test_analysis_stubbed(self):
        with patch.object(ext_stock.databull, 'get_company_profile', side_effect=_fake_profile), \
             patch.object(ext_stock.databull, 'get_stock_financial_data', side_effect=_fake_financial):
            r = self.client.get('/stocks/600519/analysis')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ('symbol', 'profile', 'fundamentals', 'factors', 'fear_greed', 'financials'):
            self.assertIn(key, data)
        self.assertEqual(data['profile']['company_name'], '测试公司')

    # ---------------- 批量分析 / 信号扫描 ----------------
    def test_batch_analysis_with_symbols(self):
        r = self.client.get('/stocks/batch/analysis', params={'symbols': '600519,000001'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # 必须是列表（若被误路由到 per-symbol analysis 会返回 dict）——防路由顺序回归
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        first = data[0]
        self.assertEqual(first['symbol'], '600519')
        for key in ('symbol', 'name', 'group_name', 'ohlc_last', 'fear_greed', 'composite_score', 'factors'):
            self.assertIn(key, first)
        # 默认核心因子集应被填充（值可能为 None，但键存在）
        self.assertIn('rsi_14', first['factors'])
        self.assertIn('main_force_behavior_phase', first['factors'])

    def test_batch_analysis_whole_pool(self):
        r = self.client.get('/stocks/batch/analysis')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        self.assertIn('factors', data[0])

    def test_batch_analysis_custom_factors(self):
        r = self.client.get('/stocks/batch/analysis',
                            params={'symbols': '600519', 'factors': 'rsi_14,mom_20'})
        self.assertEqual(r.status_code, 200)
        f = r.json()[0]['factors']
        self.assertEqual(set(f.keys()), {'rsi_14', 'mom_20'})

    def test_batch_analysis_invalid_symbol(self):
        r = self.client.get('/stocks/batch/analysis', params={'symbols': '600519,!!bad!!'})
        self.assertEqual(r.status_code, 400)

    def test_signals(self):
        r = self.client.get('/stocks/signals', params={'signal': 'ma_bullish', 'limit': 5})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['signal'], 'ma_bullish')
        self.assertIn('count', data)
        self.assertIsInstance(data['rows'], list)

    def test_signals_invalid(self):
        r = self.client.get('/stocks/signals', params={'signal': 'no_such_signal'})
        self.assertEqual(r.status_code, 400)


def create_external_api_clean():
    """不注入任何依赖覆盖的外部子应用（鉴权链路保持真实）。"""
    return create_external_app()


if __name__ == '__main__':
    unittest.main()
