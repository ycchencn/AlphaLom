"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

智能体（Agent）模块单测：CRUD + 越权隔离。

全部用例不碰网络：AgentService / UserService / chat_stream 一律打桩，
缓存用 InMemoryBackend，不依赖本机 Redis 是否在跑。

鉴权走 `app.dependency_overrides` 覆盖 get_current_user → 固定返回当前用户 dict，
免造令牌、免连 Redis。
"""

import sys, os, unittest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routes.agent as agent_routes


class FakeAgent:
    """替掉 AgentService 的返回值（字段直接存为属性，便于路由用 .id/.name 访问）。"""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', 1)
        self.user_id = kwargs.get('user_id', 10)
        self.name = kwargs.get('name', '测试')
        self.emoji = kwargs.get('emoji', '🤖')
        self.platform = kwargs.get('platform', '')
        self.model = kwargs.get('model', '')
        self.system_prompt = kwargs.get('system_prompt', '')
        self.created_at = None
        self.updated_at = None

    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id, 'name': self.name,
            'emoji': self.emoji, 'platform': self.platform, 'model': self.model,
            'system_prompt': self.system_prompt,
            'created_at': self.created_at, 'updated_at': self.updated_at,
        }


def _mock_get_current_user(request: Request):
    """Fake auth that always returns user id=10."""
    return {'id': 10, 'role': 'admin', 'username': 'admin'}


class TestAgentCRUD(unittest.TestCase):
    """智能体 CRUD 基础测试。"""

    def setUp(self):
        # 伪造当前登录用户（避免真实鉴权）。⚠️ 覆盖函数不要声明 request 参数，
        # 否则 FastAPI 会把 request 当 query 参数校验 → 全部请求 422。
        self.app = FastAPI()
        self.app.dependency_overrides[agent_routes.get_current_user] = lambda: {
            'id': 10, 'role': 'admin', 'username': 'admin'
        }

        # 打桩 AgentService
        self.agents_db = []  # 手动维护一份"数据库"
        self.counter = 0

        def fake_list(user_id):
            return [a.to_dict() for a in self.agents_db if a.user_id == user_id]

        def fake_get(agent_id, user_id):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    return a.to_dict()
            return None

        def fake_create(user_id, name, emoji, platform, model, system_prompt):
            # 模拟 DB 唯一约束：同用户重名返回 None（路由据此回 409）
            if any(a.user_id == user_id and a.name == name for a in self.agents_db):
                return None
            self.counter += 1
            agent = FakeAgent(id=self.counter, user_id=user_id, name=name, emoji=emoji,
                            platform=platform, model=model, system_prompt=system_prompt)
            self.agents_db.append(agent)
            return agent.id

        def fake_update(agent_id, user_id, payload):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    for k, v in payload.items():
                        setattr(a, k, v)
                    return True
            return False

        def fake_delete(agent_id, user_id):
            for i, a in enumerate(self.agents_db):
                if a.id == agent_id and a.user_id == user_id:
                    del self.agents_db[i]
                    return True
            return False

        self._patches = [
            patch.object(agent_routes.AgentService, 'list_agents', staticmethod(fake_list)),
            patch.object(agent_routes.AgentService, 'get_agent', staticmethod(fake_get)),
            patch.object(agent_routes.AgentService, 'create_agent', staticmethod(fake_create)),
            patch.object(agent_routes.AgentService, 'update_agent', staticmethod(fake_update)),
            patch.object(agent_routes.AgentService, 'delete_agent', staticmethod(fake_delete)),
        ]
        for p in self._patches:
            p.start()

        self.app.include_router(agent_routes.agent_router)
        self.client = TestClient(self.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _auth_header(self, token='x'):
        return {'Authorization': f'Bearer {token}'}

    def test_01_create_agent(self):
        resp = self.client.post('/api/v1/agents', json={
            'name': '测试量化助手', 'emoji': '📈', 'platform': 'deepseek',
            'model': 'deepseek-v4-flash', 'system_prompt': '你是专家。'
        }, headers=self._auth_header())
        self.assertEqual(resp.status_code, 200, f'创建失败: {resp.text}')
        data = resp.json()['data']
        self.assertEqual(data['name'], '测试量化助手')
        self.assertEqual(data['emoji'], '📈')
        self.assertEqual(data['id'], 1)

    def test_02_list_agents(self):
        # 先创建一条
        self.client.post('/api/v1/agents', json={'name': '列表测试', 'emoji': '', 'platform': '', 'model': ''},
                         headers=self._auth_header())
        resp = self.client.get('/api/v1/agents', headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        names = [a['name'] for a in resp.json()['data']]
        self.assertIn('列表测试', names)

    def test_03_get_agent_by_id(self):
        self.client.post('/api/v1/agents', json={'name': 'ID查询', 'emoji': '', 'platform': '', 'model': ''},
                         headers=self._auth_header())
        resp = self.client.get('/api/v1/agents/1', headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['name'], 'ID查询')

    def test_04_update_agent(self):
        self.client.post('/api/v1/agents', json={'name': '更新前', 'emoji': '', 'platform': '', 'model': ''},
                         headers=self._auth_header())
        resp = self.client.put('/api/v1/agents/1', json={'name': '更新后', 'emoji': '🔄'},
                               headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['name'], '更新后')

    def test_05_delete_agent(self):
        self.client.post('/api/v1/agents', json={'name': '待删除', 'emoji': '', 'platform': '', 'model': ''},
                         headers=self._auth_header())
        resp = self.client.delete('/api/v1/agents/1', headers=self._auth_header())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['deleted'])
        # 幂等安全
        resp2 = self.client.delete('/api/v1/agents/1', headers=self._auth_header())
        self.assertEqual(resp2.status_code, 404)

    def test_06_duplicate_name_rejected(self):
        self.client.post('/api/v1/agents', json={'name': '重复', 'emoji': '', 'platform': '', 'model': ''},
                         headers=self._auth_header())
        resp = self.client.post('/api/v1/agents', json={'name': '重复', 'emoji': '', 'platform': '', 'model': ''},
                                headers=self._auth_header())
        self.assertEqual(resp.status_code, 409)


class TestAgentCrossUserIsolation(unittest.TestCase):
    """跨用户隔离：两个用户各有一套智能体，互不可见。"""

    def setUp(self):
        # Admin app
        self.app_admin = FastAPI()
        self.app_admin.dependency_overrides[agent_routes.get_current_user] = lambda: {
            'id': 10, 'role': 'admin', 'username': 'admin'
        }
        self.app_normal = FastAPI()
        self.app_normal.dependency_overrides[agent_routes.get_current_user] = lambda: {
            'id': 20, 'role': 'user', 'username': 'normal'
        }

        # Shared "database"
        self.agents_db = []
        self.counter = 0

        def fake_list(user_id):
            return [a.to_dict() for a in self.agents_db if a.user_id == user_id]

        def fake_get(agent_id, user_id):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    return a.to_dict()
            return None

        def fake_create(user_id, name, emoji, platform, model, system_prompt):
            self.counter += 1
            agent = FakeAgent(id=self.counter, user_id=user_id, name=name, emoji=emoji,
                            platform=platform, model=model, system_prompt=system_prompt)
            self.agents_db.append(agent)
            return agent.id

        def fake_update(agent_id, user_id, payload):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    for k, v in payload.items():
                        setattr(a, k, v)
                    return True
            return False

        def fake_delete(agent_id, user_id):
            for i, a in enumerate(self.agents_db):
                if a.id == agent_id and a.user_id == user_id:
                    del self.agents_db[i]
                    return True
            return False

        self._patches = [
            patch.object(agent_routes.AgentService, 'list_agents', staticmethod(fake_list)),
            patch.object(agent_routes.AgentService, 'get_agent', staticmethod(fake_get)),
            patch.object(agent_routes.AgentService, 'create_agent', staticmethod(fake_create)),
            patch.object(agent_routes.AgentService, 'update_agent', staticmethod(fake_update)),
            patch.object(agent_routes.AgentService, 'delete_agent', staticmethod(fake_delete)),
        ]
        for p in self._patches:
            p.start()

        self.app_admin.include_router(agent_routes.agent_router)
        self.app_normal.include_router(agent_routes.agent_router)
        self.client_admin = TestClient(self.app_admin)
        self.client_normal = TestClient(self.app_normal)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _auth(self):
        return {'Authorization': 'Bearer x'}

    def test_regular_user_isolated(self):
        """普通用户创建自己的智能体 → admin 看不到。"""
        self.client_normal.post('/api/v1/agents', json={'name': '普通的票', 'emoji': '', 'platform': '', 'model': ''},
                                headers=self._auth())
        admin_ids = set(a['id'] for a in self.client_admin.get('/api/v1/agents', headers=self._auth()).json()['data'])
        self.assertNotIn(1, admin_ids)

    def test_cross_update_blocked(self):
        """admin 尝试更新别人的智能体 → 404。"""
        self.client_normal.post('/api/v1/agents', json={'name': '别人家的', 'emoji': '', 'platform': '', 'model': ''},
                                headers=self._auth())
        resp = self.client_admin.put('/api/v1/agents/1', json={'name': '偷改'}, headers=self._auth())
        self.assertEqual(resp.status_code, 404)

    def test_cross_delete_blocked(self):
        """admin 尝试删除别人的智能体 → 404。"""
        self.client_normal.post('/api/v1/agents', json={'name': '删不了', 'emoji': '', 'platform': '', 'model': ''},
                                headers=self._auth())
        resp = self.client_admin.delete('/api/v1/agents/1', headers=self._auth())
        self.assertEqual(resp.status_code, 404)


class TestAgentValidation(unittest.TestCase):
    """参数校验。"""

    def setUp(self):
        self.app = FastAPI()
        # ⚠️ 覆盖函数不要声明 request 参数，否则 FastAPI 会把 request 当 query 参数校验 → 全部 422
        self.app.dependency_overrides[agent_routes.get_current_user] = lambda: {
            'id': 10, 'role': 'admin', 'username': 'admin'
        }
        self.agents_db = []
        self.counter = 0

        def fake_list(user_id):
            return [a.to_dict() for a in self.agents_db if a.user_id == user_id]

        def fake_get(agent_id, user_id):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    return a.to_dict()
            return None

        def fake_create(user_id, name, emoji, platform, model, system_prompt):
            self.counter += 1
            agent = FakeAgent(id=self.counter, user_id=user_id, name=name, emoji=emoji,
                            platform=platform, model=model, system_prompt=system_prompt)
            self.agents_db.append(agent)
            return agent.id

        def fake_update(agent_id, user_id, payload):
            for a in self.agents_db:
                if a.id == agent_id and a.user_id == user_id:
                    for k, v in payload.items():
                        setattr(a, k, v)
                    return True
            return False

        def fake_delete(agent_id, user_id):
            for i, a in enumerate(self.agents_db):
                if a.id == agent_id and a.user_id == user_id:
                    del self.agents_db[i]
                    return True
            return False

        self._patches = [
            patch.object(agent_routes.AgentService, 'list_agents', staticmethod(fake_list)),
            patch.object(agent_routes.AgentService, 'get_agent', staticmethod(fake_get)),
            patch.object(agent_routes.AgentService, 'create_agent', staticmethod(fake_create)),
            patch.object(agent_routes.AgentService, 'update_agent', staticmethod(fake_update)),
            patch.object(agent_routes.AgentService, 'delete_agent', staticmethod(fake_delete)),
        ]
        for p in self._patches:
            p.start()

        self.app.include_router(agent_routes.agent_router)
        self.client = TestClient(self.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _auth(self):
        return {'Authorization': 'Bearer x'}

    def test_empty_name_rejected(self):
        resp = self.client.post('/api/v1/agents', json={'name': '   ', 'emoji': '', 'platform': '', 'model': ''},
                                headers=self._auth())
        self.assertEqual(resp.status_code, 400)

    def test_nonexistent_returns_404(self):
        resp = self.client.get('/api/v1/agents/99999999', headers=self._auth())
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_is_401(self):
        app_no_auth = FastAPI()
        app_no_auth.include_router(agent_routes.agent_router)
        client_no_auth = TestClient(app_no_auth)
        self.assertEqual(client_no_auth.get('/api/v1/agents').status_code, 401)
        self.assertEqual(client_no_auth.post('/api/v1/agents', json={}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
