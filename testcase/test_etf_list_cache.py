"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ETF 列表接口（GET /etfs）的缓存与「增删后立即失效」回归测试。

要钉住的是一类**静默**缺陷：列表挂上缓存之后，增删接口如果忘了清缓存，
用户加完 ETF 在页面上看不到（ETFInsight.vue 加完会立刻重新拉一次 /etfs，
期望这一条就在列表里），而服务端不报任何错 —— 只能等 TTL 过期才恢复。

所以这里测的不是「能不能缓存」，而是「缓存与失效两处的命名空间必须一致」：
装饰器上的 `namespace` 与写路径 `FastAPICache.clear(namespace=...)` 只要有一处
写错，用例 1（HIT）照样过，用例 2/3（增删后应变 MISS）必挂。

全部用例不碰网络也不碰数据库：EtfService / databull / 因子查询一律打桩，
缓存用 InMemoryBackend，不依赖本机 Redis 是否在跑。
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

import routes.etf as etf_routes
from service.etf_service import EtfService
from utils.api_cache import init_api_cache


class _FakeEtf:
    """替掉 EtfWatchlist：只需要 symbol / name 与 to_dict()。"""

    def __init__(self, symbol, name=None):
        self.symbol = symbol
        self.name = name

    def to_dict(self):
        return {'symbol': self.symbol, 'name': self.name}


class _StubDatabull:
    """让 /etfs 里的实时行情与取名调用不真的打上游。"""

    def get_realtime(self, symbol=None, tick_type=None):
        return {'lastPrice': 1.0, 'lastClose': 1.0}

    def get_etf_info(self, symbol):
        return {'name': f'stub-{symbol}'}


class TestEtfListCache(unittest.TestCase):
    def setUp(self):
        self.calls = {'list': 0, 'add': [], 'delete': []}

        def fake_list():
            self.calls['list'] += 1
            return [_FakeEtf('510500', '中证500ETF'), _FakeEtf('515220', '煤炭ETF')]

        def fake_add(symbol, name=None):
            self.calls['add'].append(symbol)
            return _FakeEtf(symbol, name or symbol)

        def fake_delete(symbol):
            self.calls['delete'].append(symbol)
            return symbol == '510500'

        self._patches = [
            patch.object(EtfService, 'list_watchlist', staticmethod(fake_list)),
            patch.object(EtfService, 'add_watchlist', staticmethod(fake_add)),
            patch.object(EtfService, 'delete_watchlist', staticmethod(fake_delete)),
            patch.object(etf_routes, 'databull', _StubDatabull()),
            patch.object(
                etf_routes.FactorValueService,
                'get_latest_factor_value',
                staticmethod(lambda ticker, factor_name: None),
            ),
        ]
        for p in self._patches:
            p.start()

        # 每个用例一份干净的缓存：InMemoryBackend._store 是类变量，
        # 不清的话上一个用例留下的同 key 数据会让「首次请求」变成假 HIT。
        InMemoryBackend._store.clear()
        FastAPICache.reset()
        FastAPICache.init(InMemoryBackend(), prefix='test')

        app = FastAPI()
        app.include_router(etf_routes.etf_router)
        self.client = TestClient(app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        # 还原成真实的 Redis 后端，别影响同进程里的其它测试
        FastAPICache.reset()
        init_api_cache()

    # ================= 用例 =================

    def test_01_list_is_cached(self):
        """第二次请求必须命中缓存 —— 即 Service 只被调用一次。"""
        first = self.client.get('/api/v1/etfs')
        second = self.client.get('/api/v1/etfs')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.headers.get('X-FastAPI-Cache'), 'MISS')
        self.assertEqual(second.headers.get('X-FastAPI-Cache'), 'HIT')
        self.assertEqual(self.calls['list'], 1)
        # 缓存里存的是 JSON，命中时不能丢字段 / 变形
        self.assertEqual(first.json(), second.json())

    def test_02_add_invalidates_cache(self):
        """添加 ETF 后，列表缓存必须立刻失效（前端加完要马上看到这一条）。"""
        self.client.get('/api/v1/etfs')
        self.assertEqual(self.calls['list'], 1)

        resp = self.client.post('/api/v1/etf', json={'symbol': '159915'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.calls['add'], ['159915'])

        after = self.client.get('/api/v1/etfs')
        self.assertEqual(self.calls['list'], 2, '添加后列表仍读缓存 → 加完看不到自己的改动')
        self.assertEqual(after.headers.get('X-FastAPI-Cache'), 'MISS')

    def test_03_delete_invalidates_cache(self):
        """删除 ETF 后，列表缓存必须立刻失效（否则刷新一下它又回来了）。"""
        self.client.get('/api/v1/etfs')
        self.assertEqual(self.calls['list'], 1)

        resp = self.client.delete('/api/v1/etf/510500')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.calls['delete'], ['510500'])

        self.client.get('/api/v1/etfs')
        self.assertEqual(self.calls['list'], 2, '删除后列表仍读缓存 → 删掉的 ETF 还在')

    def test_04_delete_missing_returns_404(self):
        """删除不在清单里的代码 → 404，且不该白白清一次缓存以外的副作用。"""
        resp = self.client.delete('/api/v1/etf/000000')
        self.assertEqual(resp.status_code, 404)

    def test_05_add_empty_symbol_returns_400(self):
        """空代码：Service 抛 ValueError，路由应转成 400（不是 500）。"""
        def reject(symbol, name=None):
            raise ValueError('ETF 代码不能为空')

        with patch.object(EtfService, 'add_watchlist', staticmethod(reject)):
            resp = self.client.post('/api/v1/etf', json={'symbol': '  '})
        self.assertEqual(resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
