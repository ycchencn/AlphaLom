"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股监控列表「移除监控」接口（DELETE /stocks/{symbol}）的回归测试。

要钉住的是列进行操作删除时走通的链路：
  - 在池中的票 → 200 且调用 remove_from_user_pool(当前用户, symbol)；
  - 不在池中的票 → 404（路由据此提示「不在你的股票池中」）；
  - 非法代码 → 400（validate_stock_code 拦在入库前）。

前端 StockMonitor.vue 的行菜单「移除监控」正是调这个接口。
全部用例不碰网络也不碰数据库：StockService 打桩，缓存用 InMemoryBackend，
不依赖本机 Redis 是否在跑。
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

import routes.stock as stock_routes
from service import StockService
from utils.api_cache import init_api_cache
from utils.auth import get_current_user, get_current_user_id

TEST_USER_ID = 7
# 前端 StockMonitor.vue 调的就是这个相对路径，前缀由 api_prefix 注入
DELETE_URL = '/api/v1/stocks/{symbol}'


class TestStockMonitorDelete(unittest.TestCase):
    def setUp(self):
        self.calls = {'removed': []}

        # 与真实签名一致：第一个参数是 user_id，把收到的 user_id 记下来断言
        def fake_remove(user_id, symbol):
            self.calls['removed'].append((user_id, symbol))
            # 只有 '600519' 视为「在池中」，其余视为「不在池中」→ 404
            return symbol == '600519'

        self._patches = [
            patch.object(StockService, 'remove_from_user_pool', staticmethod(fake_remove)),
        ]
        for p in self._patches:
            p.start()

        # 每个用例一份干净的缓存
        InMemoryBackend._store.clear()
        FastAPICache.reset()
        FastAPICache.init(InMemoryBackend(), prefix='test')

        app = FastAPI()
        app.include_router(stock_routes.stock_router)
        # 路由级 dependencies=[Depends(get_current_user)] 也要覆盖，否则走真实鉴权 401
        app.dependency_overrides[get_current_user] = lambda: {'id': TEST_USER_ID, 'role': 'user'}
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        self.client = TestClient(app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        FastAPICache.reset()
        init_api_cache()

    def test_01_delete_in_pool_returns_200(self):
        resp = self.client.delete(DELETE_URL.format(symbol='600519'))
        self.assertEqual(resp.status_code, 200, f'删除失败: {resp.text}')
        self.assertEqual(resp.json().get('code'), 0)
        # 确实带着「当前用户」调到了删除逻辑
        self.assertIn((TEST_USER_ID, '600519'), self.calls['removed'])

    def test_02_delete_not_in_pool_returns_404(self):
        resp = self.client.delete(DELETE_URL.format(symbol='000001'))
        self.assertEqual(resp.status_code, 404, f'未在池中应 404，实际: {resp.text}')
        self.assertIn((TEST_USER_ID, '000001'), self.calls['removed'])

    def test_03_delete_invalid_symbol_returns_400(self):
        resp = self.client.delete(DELETE_URL.format(symbol='abc!'))
        self.assertEqual(resp.status_code, 400, f'非法代码应 400，实际: {resp.text}')
        # 非法代码在 validate 阶段就被拦，根本没到 remove_from_user_pool
        self.assertEqual(self.calls['removed'], [])


if __name__ == '__main__':
    unittest.main()
