"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

用户管理（管理员）接口单测：列表 / 新建 / 编辑(含禁用与改密) / 删除。

不碰网络：UserService 全部打桩，不依赖本机 Redis / MySQL。
鉴权走 `app.dependency_overrides` 覆盖 `get_current_user` → 固定返回管理员 / 普通用户。
后端 `routes/auth.py` 已落地的业务规则都要在这里被守住：
  · 新建：用户名/密码必填、role 只能是 admin/user、用户名/邮箱不重复；
  · 编辑：邮箱不与别人重复、空 payload 拒、不能禁用/降级自己；
  · 改密或禁用 → 撤销该用户全部令牌（立即下线）；
  · 删除：不能删自己、不存在返回 404；
  · 非管理员访问 → 403。
"""

import sys, os, unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routes.auth as auth_routes
from service import UserService


ADMIN = {'id': 10, 'role': 'admin', 'username': 'admin'}
NORMAL = {'id': 20, 'role': 'user', 'username': 'normal'}


def _make_user(uid, username, role='user', email=None, nickname=None):
    return {
        'id': uid, 'username': username, 'role': role, 'email': email,
        'nickname': nickname, 'is_active': 1,
        'last_login_at': None, 'created_at': '2026-01-01T00:00:00',
        'updated_at': '2026-01-01T00:00:00',
    }


class TestUserAdmin(unittest.TestCase):

    def setUp(self):
        # 伪造当前登录用户（管理员），避免真实鉴权
        self.app = FastAPI()
        self.app.dependency_overrides[auth_routes.get_current_user] = lambda: dict(ADMIN)
        self.app.include_router(auth_routes.auth_router)
        self.client = TestClient(self.app)

        # 内存"数据库"
        self._all = [
            _make_user(10, 'admin', role='admin', email='admin@x.com'),
            _make_user(20, 'other', email='dup@x.com'),
            _make_user(999, 'victim', email='v@x.com'),
        ]
        self._by_user = {u['username']: u for u in self._all}
        self._by_id = {u['id']: u for u in self._all}
        self._revoked = {}
        self._next_id = 1000
        self.add_fail = False
        self.update_fail = False
        self.delete_fail = False

        def fake_get_all():
            return list(self._all)

        def fake_get_by_username(username):
            return self._by_user.get(username)

        def fake_get_by_id(uid):
            return self._by_id.get(int(uid))

        def fake_email_exists(email, exclude_user_id=None):
            ex = int(exclude_user_id) if exclude_user_id is not None else None
            return any(u.get('email') == email and u.get('id') != ex for u in self._all)

        def fake_add(data):
            if self.add_fail:
                return None
            uname = data.get('username')
            if uname in self._by_user:
                return None
            uid = self._next_id
            self._next_id += 1
            u = {
                'id': uid, 'username': uname,
                'nickname': data.get('nickname'), 'email': data.get('email'),
                'role': data.get('role', 'user'), 'is_active': data.get('is_active', 1),
                'last_login_at': None, 'created_at': '2026-01-01T00:00:00',
                'updated_at': '2026-01-01T00:00:00',
            }
            self._by_user[uname] = u
            self._by_id[uid] = u
            self._all.append(u)
            return u

        def fake_update(uid, payload):
            if self.update_fail:
                return False
            u = self._by_id.get(int(uid))
            if not u:
                return False
            payload = {k: v for k, v in payload.items() if k != 'password'}
            u.update(payload)
            return True

        def fake_delete(uid):
            if self.delete_fail:
                return False
            u = self._by_id.pop(int(uid), None)
            if not u:
                return False
            self._all.remove(u)
            self._by_user.pop(u['username'], None)
            return True

        def fake_revoke(uid):
            self._revoked[int(uid)] = self._revoked.get(int(uid), 0) + 1
            return self._revoked[int(uid)]

        self._patches = [
            patch.object(UserService, 'get_all', staticmethod(fake_get_all)),
            patch.object(UserService, 'get_by_username', staticmethod(fake_get_by_username)),
            patch.object(UserService, 'get_by_id', staticmethod(fake_get_by_id)),
            patch.object(UserService, 'email_exists', staticmethod(fake_email_exists)),
            patch.object(UserService, 'add', staticmethod(fake_add)),
            patch.object(UserService, 'update', staticmethod(fake_update)),
            patch.object(UserService, 'delete', staticmethod(fake_delete)),
            patch.object(UserService, 'revoke_all_tokens', staticmethod(fake_revoke)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _auth_header(self, token='x'):
        return {'Authorization': f'Bearer {token}'}

    # ---------------- 列表 ----------------
    def test_list_users(self):
        resp = self.client.get('/api/v1/users', headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

    # ---------------- 新建 ----------------
    def test_create_success(self):
        resp = self.client.post('/api/v1/users', json={
            'username': 'newbie', 'password': 'secret123', 'nickname': '新人',
            'email': 'new@x.com', 'role': 'user',
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'newbie')
        self.assertEqual(resp.json()['role'], 'user')

    def test_create_missing_username(self):
        resp = self.client.post('/api/v1/users', json={'password': 'x'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_password(self):
        resp = self.client.post('/api/v1/users', json={'username': 'x'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_create_bad_role(self):
        resp = self.client.post('/api/v1/users', json={
            'username': 'x', 'password': 'x', 'role': 'super',
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_create_dup_username(self):
        resp = self.client.post('/api/v1/users', json={
            'username': 'other', 'password': 'x',
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_create_dup_email(self):
        resp = self.client.post('/api/v1/users', json={
            'username': 'brandnew', 'password': 'x', 'email': 'dup@x.com',
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_create_add_fails(self):
        self.add_fail = True
        resp = self.client.post('/api/v1/users', json={
            'username': 'fail', 'password': 'x',
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 500)

    # ---------------- 编辑 ----------------
    def test_update_success(self):
        resp = self.client.put('/api/v1/users/999', json={'nickname': '改昵称'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['nickname'], '改昵称')

    def test_update_not_found(self):
        resp = self.client.put('/api/v1/users/12345', json={'nickname': 'x'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 404)

    def test_update_bad_role(self):
        resp = self.client.put('/api/v1/users/999', json={'role': 'evil'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_update_dup_email(self):
        # victim(999) 想用 other(20) 的邮箱 → 应被拒（排除自己后仍冲突）
        resp = self.client.put('/api/v1/users/999', json={'email': 'dup@x.com'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_update_email_no_conflict(self):
        # victim(999) 换成一个库里没人用的邮箱 → 应放行
        resp = self.client.put('/api/v1/users/999', json={'email': 'fresh@x.com'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)

    def test_update_empty_payload(self):
        resp = self.client.put('/api/v1/users/999', json={}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_update_disable_self_rejected(self):
        resp = self.client.put('/api/v1/users/10', json={'is_active': 0}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_update_demote_self_rejected(self):
        resp = self.client.put('/api/v1/users/10', json={'role': 'user'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_update_password_revokes_tokens(self):
        resp = self.client.put('/api/v1/users/999', json={'password': 'newpwd'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._revoked.get(999), 1)

    def test_update_disable_revokes_tokens(self):
        resp = self.client.put('/api/v1/users/999', json={'is_active': 0}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._revoked.get(999), 1)

    def test_update_fails(self):
        self.update_fail = True
        resp = self.client.put('/api/v1/users/999', json={'nickname': 'x'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 500)

    # ---------------- 删除 ----------------
    def test_delete_success(self):
        resp = self.client.delete('/api/v1/users/999', headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertIn('revoked_tokens', resp.json())
        self.assertEqual(self._revoked.get(999), 1)

    def test_delete_self_rejected(self):
        resp = self.client.delete('/api/v1/users/10', headers=self._auth_header())
        self.assertEqual(resp.status_code, 400)

    def test_delete_not_found(self):
        resp = self.client.delete('/api/v1/users/12345', headers=self._auth_header())
        self.assertEqual(resp.status_code, 404)

    def test_delete_fails(self):
        self.delete_fail = True
        resp = self.client.delete('/api/v1/users/999', headers=self._auth_header())
        self.assertEqual(resp.status_code, 500)

    # ---------------- 鉴权 ----------------
    def test_non_admin_forbidden(self):
        app2 = FastAPI()
        app2.dependency_overrides[auth_routes.get_current_user] = lambda: dict(NORMAL)
        app2.include_router(auth_routes.auth_router)
        client2 = TestClient(app2)
        # 列表
        resp = client2.get('/api/v1/users', headers=self._auth_header())
        self.assertEqual(resp.status_code, 403)
        # 新建
        resp = client2.post('/api/v1/users', json={'username': 'x', 'password': 'x'}, headers=self._auth_header())
        self.assertEqual(resp.status_code, 403)


if __name__ == '__main__':
    unittest.main()
