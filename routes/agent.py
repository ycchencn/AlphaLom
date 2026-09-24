"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

智能体（LlmAgent）CRUD 路由。

- GET    /api/v1/agents              列出当前用户的全部智能体
- POST   /api/v1/agents              新建（同用户下 name 唯一）
- PUT    /api/v1/agents/{id}         更新（user_id 由 auth 注入，不可伪造）
- DELETE /api/v1/agents/{id}         删除（幂等安全，越权返回 404）

⚠️ 全部端点无需管理员：用户管理自己的智能体，不暴露 ID 是否存在于别人的空间。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from service.agent_service import AgentService
from utils.auth import get_current_user


agent_router = APIRouter(prefix=f'{api_prefix}/agents', tags=['智能体'])


# ---------- 列表 ----------

# 同时挂 '' 与 '/'：前端（及任何调用方）用 /api/v1/agents（无尾斜杠）也能命中，
# 否则会被 SPA 兜底 /{full_path:path} 抢走返回 HTML。
@agent_router.get('')
@agent_router.get('/')
def list_agents(user: dict = Depends(get_current_user)):
    """获取当前登录用户的全部智能体列表。"""
    return {'code': 0, 'data': AgentService.list_agents(user['id'])}


# ---------- 详情 ----------

@agent_router.get('/{agent_id}')
def get_agent(agent_id: int, user: dict = Depends(get_current_user)):
    """按 id 获取单个智能体（带 user_id 隔离，越权 404）。"""
    agent = AgentService.get_agent(agent_id, user['id'])
    if agent is None:
        raise HTTPException(status_code=404, detail='智能体不存在')
    return {'code': 0, 'data': agent}


# ---------- 新建 ----------

class CreateAgentRequest(BaseModel):
    name: str
    emoji: str = '🤖'
    platform: str = ''
    model: str = ''
    system_prompt: str = ''


@agent_router.post('')
@agent_router.post('/')
def create_agent(req: CreateAgentRequest, user: dict = Depends(get_current_user)):
    """新建一个智能体。name 在同用户下必须唯一。"""
    req_name = (req.name or '').strip()
    if not req_name:
        raise HTTPException(status_code=400, detail='名称不能为空')

    new_id = AgentService.create_agent(
        user_id=user['id'],
        name=req_name,
        emoji=(req.emoji or '🤖'),
        platform=(req.platform or '').strip(),
        model=(req.model or '').strip(),
        system_prompt=(req.system_prompt or ''),
    )
    if new_id is None:
        raise HTTPException(status_code=409, detail=f"该名称已存在：{req_name}")
    # 返回新创建的 agent 完整信息
    agent = AgentService.get_agent(new_id, user['id'])
    return {'code': 0, 'message': 'ok', 'data': agent}


# ---------- 更新 ----------

class UpdateAgentRequest(BaseModel):
    name: str = None
    emoji: str = None
    platform: str = None
    model: str = None
    system_prompt: str = None


@agent_router.put('/{agent_id}')
def update_agent(agent_id: int, req: UpdateAgentRequest, user: dict = Depends(get_current_user)):
    """更新智能体字段（user_id 由 auth 拦截器保障，不可伪造）。"""
    ok = AgentService.update_agent(agent_id, user['id'], req.model_dump(exclude_unset=True))
    if not ok:
        raise HTTPException(status_code=404, detail='智能体不存在或无权修改')
    agent = AgentService.get_agent(agent_id, user['id'])
    return {'code': 0, 'message': 'ok', 'data': agent}


# ---------- 删除 ----------

@agent_router.delete('/{agent_id}')
def delete_agent(agent_id: int, user: dict = Depends(get_current_user)):
    """删除智能体（幂等安全）。"""
    deleted = AgentService.delete_agent(agent_id, user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail='智能体不存在')
    return {'code': 0, 'message': 'deleted', 'deleted': True}
