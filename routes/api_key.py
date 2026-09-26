"""
 * @author Yc
 * API Key 管理接口（需登录会话令牌，供用户在 Web 端自助管理自己的对外密钥）。
 *
 * 与对外数据接口（/api/ext）区分：这里是「管理面」，用现有会话 token 鉴权；
 * 那里是「数据面」，用 API Key 鉴权。明文密钥只在创建响应里返回这一次。
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from service import ApiKeyService
from utils.auth import get_current_user_id

api_key_router = APIRouter(prefix='/api/v1', tags=['API Key 管理'])


def make_response(data=None, msg='success', code=200):
    return {'code': code, 'msg': msg, 'data': data}


def _parse_expires_at(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '').replace(' ', 'T'))
    except Exception:
        return None


@api_key_router.post('/api-keys')
async def create_api_key(request: Request, user_id: int = Depends(get_current_user_id)):
    """创建一枚对外 API Key。明文密钥只在本次响应返回，请妥善保存。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return make_response(msg='Request must be JSON', code=400)

    name = body.get('name') or 'default'
    daily_quota = body.get('daily_quota')
    if daily_quota is not None:
        try:
            daily_quota = int(daily_quota)
        except (TypeError, ValueError):
            return make_response(msg='daily_quota must be an integer', code=400)
    expires_at = _parse_expires_at(body.get('expires_at'))

    raw, record = ApiKeyService.create(
        user_id=user_id, name=name, daily_quota=daily_quota, expires_at=expires_at
    )
    data = dict(record)
    data['key'] = raw  # ⚠️ 仅此处返回明文，后续接口调用都只认 key_hash
    return make_response(data=data)


@api_key_router.get('/api-keys')
def list_api_keys(user_id: int = Depends(get_current_user_id)):
    """列出当前用户的所有密钥（不含明文，含状态/配额/最近使用时间）。"""
    return make_response(data=ApiKeyService.list_by_user(user_id))


@api_key_router.get('/api-keys/{key_id}')
def get_api_key(key_id: int, user_id: int = Depends(get_current_user_id)):
    """获取单枚密钥详情（归属校验失败一律 404）。"""
    record = ApiKeyService.get_by_id(key_id, user_id)
    if not record:
        raise HTTPException(status_code=404, detail='API Key not found')
    return make_response(data=record.to_dict_masked())


@api_key_router.put('/api-keys/{key_id}')
async def update_api_key(key_id: int, request: Request, user_id: int = Depends(get_current_user_id)):
    """更新密钥：改名 / 启停（active|revoked）/ 改每日配额。支持部分字段。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return make_response(msg='Request must be JSON', code=400)

    kwargs = {}
    if 'name' in body:
        kwargs['name'] = body['name']
    if 'status' in body:
        kwargs['status'] = body['status']
    if 'daily_quota' in body:
        try:
            kwargs['daily_quota'] = int(body['daily_quota']) if body['daily_quota'] is not None else None
        except (TypeError, ValueError):
            return make_response(msg='daily_quota must be an integer or null', code=400)

    updated = ApiKeyService.update(key_id, user_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=404, detail='API Key not found')
    return make_response(data=updated)


@api_key_router.delete('/api-keys/{key_id}')
def revoke_api_key(key_id: int, user_id: int = Depends(get_current_user_id)):
    """吊销密钥：立即失效（删 Redis 索引），之后的对外请求都 401。"""
    ok = ApiKeyService.revoke(key_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail='API Key not found')
    return make_response(msg='revoked')
