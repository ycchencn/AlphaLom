"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ALTCHA 人机校验「启用开关」单测：dev / 显式 ALTCHA_ENABLED=false 时跳过出题与校验、
非 dev 环境（或显式开启）仍 fail-closed。

不碰网络/Redis：altcha.create / altcha.verify / UserService.* 一律打桩。
"""

import sys, os, unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import altcha as altcha_util
import routes.auth as auth_routes
import routes.altcha as altcha_route
from service import UserService


class TestAltchaToggle(unittest.TestCase):
    """ALTCHA 启用开关行为。"""

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(auth_routes.auth_router)
        self.app.include_router(altcha_route.altcha_router)
        self.client = TestClient(self.app)

    # ---- is_enabled 开关本身 ----
    def test_is_enabled_reflects_patch(self):
        with patch.object(altcha_util, 'is_enabled', return_value=False):
            self.assertFalse(altcha_util.is_enabled())
        with patch.object(altcha_util, 'is_enabled', return_value=True):
            self.assertTrue(altcha_util.is_enabled())

    # ---- /altcha/challenge 出题接口 ----
    def test_challenge_disabled_returns_enabled_false(self):
        # 禁用时不应调用 create（用 side_effect 让任何调用直接炸）
        with patch.object(altcha_util, 'is_enabled', return_value=False), \
             patch.object(altcha_util, 'create', side_effect=AssertionError('不应调用 create')):
            resp = self.client.get('/api/v1/altcha/challenge')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('enabled'), False)

    def test_challenge_enabled_returns_challenge(self):
        fake = {'challenge': 'abc', 'signature': 'sig'}
        with patch.object(altcha_util, 'is_enabled', return_value=True), \
             patch.object(altcha_util, 'create', return_value=fake):
            resp = self.client.get('/api/v1/altcha/challenge')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('challenge'), 'abc')

    def test_challenge_enabled_but_unconfigured_returns_503(self):
        # 启用却配坏 → 必须 503（fail-closed），绝不静默放行
        with patch.object(altcha_util, 'is_enabled', return_value=True), \
             patch.object(altcha_util, 'create', side_effect=altcha_util.AltchaNotConfigured('no key')):
            resp = self.client.get('/api/v1/altcha/challenge')
        self.assertEqual(resp.status_code, 503)

    # ---- /auth/login 登录接口 ----
    def test_login_skips_altcha_when_disabled(self):
        # 禁用时即使空 payload 也应跳过人机校验，继续走账号密码校验
        user = {'id': 2, 'username': 'u', 'role': 'user'}
        with patch.object(altcha_util, 'is_enabled', return_value=False), \
             patch.object(UserService, 'authenticate', return_value=user), \
             patch.object(UserService, 'issue_token', return_value='tok'):
            resp = self.client.post('/api/v1/auth/login',
                                    json={'username': 'u', 'password': 'p', 'altcha': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 1)
        self.assertEqual(resp.json().get('token'), 'tok')

    def test_login_requires_altcha_when_enabled_and_empty(self):
        # 启用时空 payload → 400（前端文案已含"人机"）
        with patch.object(altcha_util, 'is_enabled', return_value=True), \
             patch.object(altcha_util, 'verify', return_value=(False, '请先完成人机验证')):
            resp = self.client.post('/api/v1/auth/login',
                                    json={'username': 'u', 'password': 'p', 'altcha': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('人机', resp.json().get('message', ''))

    def test_login_passes_altcha_when_enabled_and_valid(self):
        # 启用时合法 payload 通过 → 继续走账号密码校验
        user = {'id': 2, 'username': 'u', 'role': 'user'}
        with patch.object(altcha_util, 'is_enabled', return_value=True), \
             patch.object(altcha_util, 'verify', return_value=(True, '')), \
             patch.object(UserService, 'authenticate', return_value=user), \
             patch.object(UserService, 'issue_token', return_value='tok'):
            resp = self.client.post('/api/v1/auth/login',
                                    json={'username': 'u', 'password': 'p', 'altcha': 'payload'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 1)


if __name__ == '__main__':
    unittest.main()
