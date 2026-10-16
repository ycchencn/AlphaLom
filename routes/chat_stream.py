"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

智能体对话路由（FastAPI 版）。

替代旧 Flask Blueprint（chat_bp.py），支持按 agent_id 查 DB 取 platform/model/system_prompt，
以及直接传参模式（向后兼容）。流式输出复用 _PLATFORM_REGISTRY 基础设施。

注册前缀 /api/v1/chat → 完整路径：/api/v1/chat/stream, /api/v1/chat/session_ids
"""

import json
from typing import Any, Dict, List, Optional

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from llms import _PLATFORM_REGISTRY, get_llm_from_agent
from app.fastapi_app import api_prefix
from service.agent_service import AgentService
from utils.auth import get_current_user
from utils.logger import logger
from utils.redis_obj import redis_obj

chat_router = APIRouter(prefix=f'{api_prefix}/chat', tags=['智能体聊天'])


# ---------- 请求模型 ----------

class ChatStreamRequest(BaseModel):
    """流式对话入参。两种调用方式：

    - **agent_id=N**：去 DB 拿 agent 的 platform/model/system_prompt
    - **platform + model + messages**：直接传参（向后兼容）
    """
    message: str
    session_id: Optional[str] = None
    # agent_id 模式
    agent_id: Optional[int] = None
    # 直接传参模式
    platform: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    messages: Optional[List[Dict[str, str]]] = None


# ---------- Redis 工具 ----------

def load_session(session_id: Optional[str]) -> Optional[List[Dict[str, str]]]:
    """从 Redis 加载会话历史。失败返回 None。"""
    if not session_id:
        return None
    try:
        val = redis_obj.get(f'session:{session_id}')
        if val:
            return json.loads(val) if isinstance(val, bytes) else json.loads(val)
        return None
    except Exception as e:
        logger.warning(f"Redis load session {session_id} failed: {e}")
        return None


def save_session(session_id: Optional[str], history: List[Dict[str, str]]) -> bool:
    """保存会话历史到 Redis（TTL=86400）。"""
    if not session_id:
        return False
    try:
        redis_obj.setex(f'session:{session_id}', 86400, json.dumps(history))
        return True
    except Exception as e:
        logger.warning(f"Redis save session {session_id} failed: {e}")
        return False


def resolve_session_key(user: dict, agent_id: Optional[int] = None, fallback_session_id: Optional[str] = None, stock_code: Optional[str] = None) -> Optional[str]:
    """生成**用户隔离**的会话 Redis key。

    ⚠️ 必须用登录用户的 id 参与 key 拼接，绝不能信任前端传来的 session_id 直接当 key，
    否则不同用户只要拥有相同 agent_id 就会互相读写同一份对话（多租户数据泄露）。
    - 个股对话：session:{user_id}:{agent_id}:stock:{stock_code}（每只股票独立命名空间）
    - agent_id 模式：session:{user_id}:{agent_id}
    - 直接传参模式（无 agent_id）：session:{user_id}:{fallback 或 'default'}
    """
    uid = user.get('id')
    if not uid:
        return None
    if stock_code:
        return f'session:{uid}:{agent_id}:stock:{stock_code}'
    if agent_id:
        return f'session:{uid}:{agent_id}'
    return f'session:{uid}:{fallback_session_id or "default"}'


# ---------- 端点 ----------

@chat_router.post('/stream')
async def chat_stream(req: ChatStreamRequest, user: dict = Depends(get_current_user)):
    """流式对话接口。

    - agent_id 模式：查 DB → 取 platform/model/system_prompt → 调下游 LLM
    - 直接传参模式：用 req.platform/req.model/req.system_prompt → 调下游 LLM
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail='消息内容不能为空')

    # 1. 决定 platform / model / system_prompt
    platform = ''
    model_name = ''
    system_prompt = ''

    if req.agent_id:
        agent = AgentService.get_agent(req.agent_id, user['id'])
        if agent:
            platform = agent.get('platform', '')
            model_name = agent.get('model', '')
            system_prompt = agent.get('system_prompt', '')

    if not platform or not model_name:
        platform = (req.platform or '').strip()
        model_name = (req.model or '').strip()
        system_prompt = (req.system_prompt or '').strip()

    if not platform or not model_name:
        raise HTTPException(status_code=400, detail='缺少平台或模型配置')

    # 2. 构建 messages
    # ⚠️ 用登录用户的 id 拼 key（多租户隔离），不直接用前端传来的 session_id 当 key
    key = resolve_session_key(user, req.agent_id, req.session_id)
    conversation_history = load_session(key) or []
    msgs = []
    if system_prompt and system_prompt.strip():
        msgs.append({'role': 'system', 'content': system_prompt})
    msgs.extend(conversation_history)
    msgs.append({'role': 'user', 'content': req.message})

    # 3. 选择客户端
    llm_cls = _PLATFORM_REGISTRY.get(platform)
    if not llm_cls:
        supported = ', '.join(sorted(_PLATFORM_REGISTRY.keys()))
        raise HTTPException(status_code=400, detail=f'不支持的平台：{platform}，支持：{supported}')

    # 在事件循环外创建同步的 LLM 客户端（避免阻塞）
    # ⚠️ 必须是同步函数：anyio.to_thread.run_sync 会在线程里直接调用它，
    # 传协程函数只会拿到一个未执行的 coroutine 对象（表现为 staff.client 报错）。
    def _create_staff():
        staff = llm_cls()
        staff.set_model(model_name)
        return staff

    staff = await anyio.to_thread.run_sync(_create_staff)

    # 4. 流式生成器
    async def response_generator():
        assistant_reply = ''
        try:
            # OpenAI SDK 的 stream 是同步迭代器，必须放在线程池执行
            def _stream_call():
                # 尽量请求流式 usage（部分平台/SDK 不支持会报错，回退到不带该参数）
                try:
                    return staff.client.chat.completions.create(
                        model=model_name,
                        messages=msgs,
                        stream=True,
                        stream_options={'include_usage': True},
                    )
                except Exception:
                    return staff.client.chat.completions.create(
                        model=model_name,
                        messages=msgs,
                        stream=True,
                    )

            stream = await anyio.to_thread.run_sync(_stream_call)

            _usage = None
            for chunk in stream:
                # 流式 usage 通常挂在最后一个 chunk 上
                if getattr(chunk, 'usage', None) is not None:
                    _usage = chunk.usage
                content = chunk.choices[0].delta.content or ''
                if content:
                    assistant_reply += content
                    yield content.encode('utf-8')

            # 更新会话历史
            if assistant_reply:
                # ⚠️ 必须把本轮「用户提问 + 助手回答」都写回，否则下次只读回半句（缺 user）
                conversation_history.append({'role': 'user', 'content': req.message})
                conversation_history.append({'role': 'assistant', 'content': assistant_reply})
                save_session(key, conversation_history)

                # 记录本次流式 LLM 调用的 token 与对话详情（失败不影响主链路）。
                # scene 统一记为 chat_stream；user_id 优先取请求级 ContextVar，
                # 兜底用当前登录用户 id。
                try:
                    from llms.usage_recorder import record_llm_usage
                    from utils.auth import request_user_id_var
                    input_text = '\n'.join(
                        f"{m.get('role', '')}: {m.get('content', '')}" for m in msgs
                    )
                    record_llm_usage(
                        user_id=request_user_id_var.get() or user.get('id'),
                        scene='chat_stream',
                        platform=platform,
                        model=model_name,
                        prompt_tokens=getattr(_usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(_usage, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(_usage, 'total_tokens', 0) or 0,
                        input_text=input_text,
                        output_text=assistant_reply,
                    )
                except Exception as e:
                    logger.warning(f"chat token 使用记录失败（已忽略）：{e}")

        except Exception as e:
            error_msg = f'出错了：{str(e)}'
            logger.error(f"chat stream failed: platform={platform}, err={e}")
            yield error_msg.encode('utf-8')

    return StreamingResponse(response_generator(), media_type='text/plain')


@chat_router.get('/session')
def get_session(agent_id: Optional[int] = None, stock_code: Optional[str] = None, user: dict = Depends(get_current_user)):
    """拉取指定智能体的会话历史（供刷新页面 / 切换智能体后恢复界面）。

    返回 `{'code': 0, 'data': [{'role', 'content}, ...]}`，无历史返回空数组。
    个股对话传 stock_code 时，读取该股票独立的会话命名空间。
    """
    key = resolve_session_key(user, agent_id, None, stock_code)
    if not key:
        return {'code': 0, 'data': []}
    history = load_session(key) or []
    return {'code': 0, 'data': history}


@chat_router.post('/clear_session')
def clear_session(req: Dict[str, Any], user: dict = Depends(get_current_user)):
    """清空指定智能体的会话历史。"""
    agent_id = req.get('agent_id')
    fallback = (req.get('session_id') or '').strip()
    stock_code = req.get('stock_code') or None
    if not agent_id and not fallback and not stock_code:
        raise HTTPException(status_code=400, detail='agent_id / session_id / stock_code 至少提供一项')
    # ⚠️ 用户隔离：用登录用户 id 拼 key，不信任前端直接给的 session_id
    key = resolve_session_key(user, agent_id, fallback, stock_code)
    if not key:
        raise HTTPException(status_code=400, detail='无法解析会话标识')
    try:
        # ⚠️ 与 load/save 保持一致：load_session/save_session 内部会对 key 再拼一层 'session:' 前缀，
        # 这里也必须拼，否则删的是另一个 key（数据删不掉）。
        redis_obj.delete(f'session:{key}')
        return {'code': 0, 'message': '会话历史已清空'}
    except Exception as e:
        logger.warning(f"Redis delete session {key} failed: {e}")
        return {'code': 0, 'message': '操作完成（Redis 不可用已降级）'}


# ---------- 个股内嵌智能体对话（agent 模式，支持调用本系统 MCP 工具） ----------

def _ndjson(obj: dict) -> str:
    """把一行事件序列化为 NDJSON（每行一个完整 JSON，前端按 \\n 切分）。"""
    return json.dumps(obj, ensure_ascii=False) + '\n'


def _summarize_tool_result(tool_result: dict) -> str:
    """给前端工具卡片用的简短摘要（不把完整大文本塞进界面）。"""
    if not isinstance(tool_result, dict):
        return str(tool_result)[:200]
    code = tool_result.get('code')
    msg = tool_result.get('msg') or ''
    data = tool_result.get('data')
    if code == 0 and data is not None:
        text = json.dumps(data, ensure_ascii=False)
        return text[:300] + ('…' if len(text) > 300 else '')
    return f'调用失败：{msg}'[:300]


class ChatAgentStreamRequest(BaseModel):
    """个股内嵌智能体对话入参。

    - agent_id 模式：去 DB 取 platform/model/system_prompt（带用户隔离）
    - 直接传参模式（向后兼容）：platform + model + system_prompt
    - stock_code / stock_name：把「当前浏览的个股」注入 system 上下文，让智能体聚焦该股
    - use_tools：是否开启 agent 模式（调用本系统 MCP 工具获取个股行情/财务/新闻等）
    """
    message: str
    session_id: Optional[str] = None
    agent_id: Optional[int] = None
    platform: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    use_tools: bool = True
    messages: Optional[List[Dict[str, str]]] = None


@chat_router.post('/agent_stream')
async def chat_agent_stream(req: ChatAgentStreamRequest, user: dict = Depends(get_current_user)):
    """个股内嵌智能体对话（流式，NDJSON 协议）。

    返回 `application/x-ndjson`，每行一个事件：
    - {"type":"text","data":"...片段"}            —— 助手文本增量
    - {"type":"tool","name":...,"args":...,"summary":...}  —— 工具调用步骤（可折叠展示）
    - {"type":"error","data":"..."}               —— 出错
    普通对话（use_tools=false）只会产生 text 事件；agent 模式会产生 tool + text 交替。
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail='消息内容不能为空')

    # 1. 解析 platform / model / system_prompt（在后台线程构建同步 LLM 客户端）
    def _resolve_staff():
        if req.agent_id:
            agent = AgentService.get_agent(req.agent_id, user['id'])
            if agent and agent.get('platform') and agent.get('model'):
                s = get_llm_from_agent(agent, scene='chat_agent')
                return s, agent.get('platform', ''), agent.get('model', ''), agent.get('system_prompt', '')
        if req.platform and req.model:
            cls = _PLATFORM_REGISTRY.get(req.platform.strip())
            if cls:
                s = cls()
                s.set_model(req.model.strip())
                s.scene = 'chat_agent'
                s.platform = req.platform.strip()
                return s, req.platform.strip(), req.model.strip(), req.system_prompt or ''
        return None, '', '', ''

    staff, platform, model_name, system_prompt = await anyio.to_thread.run_sync(_resolve_staff)
    if staff is None:
        supported = ', '.join(sorted(_PLATFORM_REGISTRY.keys()))
        raise HTTPException(
            status_code=400,
            detail=f'缺少平台或模型配置（请指定 agent_id 或直接传 platform/model，支持：{supported}）'
        )

    # 2. 拼 system + 历史 + 用户消息
    key = resolve_session_key(user, req.agent_id, req.session_id, req.stock_code)
    history = load_session(key) or []
    msgs = []
    sys_parts = []
    if req.stock_code:
        sys_parts.append(f'你正在与用户讨论 A股标的 {req.stock_code} {req.stock_name or ""}。'.strip())
        if req.use_tools:
            sys_parts.append(
                '请优先使用系统提供的 MCP 工具获取该股票的最新行情、财务、新闻等数据来辅助回答，'
                '不要编造未获取的数据。'
            )
    if system_prompt and system_prompt.strip():
        sys_parts.append(system_prompt)
    if sys_parts:
        msgs.append({'role': 'system', 'content': '\n\n'.join(sys_parts)})
    msgs.extend(history)
    msgs.append({'role': 'user', 'content': req.message})

    # 3. 加载 MCP 工具（agent 模式）
    mcp_tools = []
    if req.use_tools:
        try:
            mcp_tools = await anyio.to_thread.run_sync(staff._get_mcp_tools)
        except Exception as e:
            logger.warning(f'获取 MCP 工具失败（降级为纯文本）：{e}')
            mcp_tools = []
    valid_names = {t['function']['name'] for t in mcp_tools} if mcp_tools else set()

    async def response_generator():
        assistant_reply = ''
        messages = list(msgs)
        try:
            rounds = 0
            while True:
                def _stream_call():
                    try:
                        return staff.client.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            stream=True,
                            stream_options={'include_usage': True},
                            tools=mcp_tools if mcp_tools else None,
                            tool_choice='auto' if mcp_tools else None,
                        )
                    except Exception:
                        return staff.client.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            stream=True,
                            tools=mcp_tools if mcp_tools else None,
                        )

                stream = await anyio.to_thread.run_sync(_stream_call)
                tool_calls_buf = {}
                text_buf = ''
                usage = None
                # ⚠️ 同步迭代（沿用 /stream 的模式，事件循环已通过 to_thread 让出）
                for chunk in stream:
                    if getattr(chunk, 'usage', None) is not None:
                        usage = chunk.usage
                    delta = chunk.choices[0].delta
                    if getattr(delta, 'content', None):
                        text_buf += delta.content
                        yield _ndjson({'type': 'text', 'data': delta.content}).encode('utf-8')
                    tcs = getattr(delta, 'tool_calls', None)
                    if tcs:
                        for tc in tcs:
                            idx = tc.index
                            buf = tool_calls_buf.setdefault(idx, {'name': '', 'args': ''})
                            if tc.function.name:
                                buf['name'] += tc.function.name
                            if tc.function.arguments:
                                buf['args'] += tc.function.arguments

                if tool_calls_buf:
                    rounds += 1
                    if rounds > getattr(staff, 'max_tool_rounds', 5):
                        yield _ndjson({'type': 'text', 'data': '\n\n（工具调用次数过多，已停止自动取数。）'}).encode('utf-8')
                        assistant_reply = text_buf
                        break
                    # 把带 tool_calls 的助手消息回灌，供下一轮基于结果续写
                    assistant_tool_msg = {
                        'role': 'assistant',
                        'content': text_buf or None,
                        'tool_calls': [
                            {'id': f'call_{i}', 'type': 'function',
                             'function': {'name': b['name'], 'arguments': b['args']}}
                            for i, b in sorted(tool_calls_buf.items())
                        ],
                    }
                    messages.append(assistant_tool_msg)
                    for i, b in sorted(tool_calls_buf.items()):
                        try:
                            args = json.loads(b['args'] or '{}')
                        except Exception:
                            args = {}
                        # 自动注入当前个股代码（若工具需要且模型没传），让 agent 默认聚焦该股
                        if req.stock_code and not any(k in args for k in ('stock_code', 'symbol', 'code')):
                            args['stock_code'] = req.stock_code
                        result = await anyio.to_thread.run_sync(staff._call_mcp_tool, b['name'], args)
                        yield _ndjson({
                            'type': 'tool', 'name': b['name'], 'args': args,
                            'summary': _summarize_tool_result(result)
                        }).encode('utf-8')
                        messages.append({
                            'role': 'tool',
                            'tool_call_id': f'call_{i}',
                            'content': staff._serialize_tool_result(result),
                        })
                    continue
                else:
                    assistant_reply = text_buf
                    break

            # 4. 保存会话历史 + 记录 token 用量
            if assistant_reply:
                history.append({'role': 'user', 'content': req.message})
                history.append({'role': 'assistant', 'content': assistant_reply})
                save_session(key, history)
                try:
                    from llms.usage_recorder import record_llm_usage
                    from utils.auth import request_user_id_var
                    input_text = '\n'.join(
                        f"{m.get('role', '')}: {m.get('content', '')}" for m in messages
                    )
                    record_llm_usage(
                        user_id=request_user_id_var.get() or user.get('id'),
                        scene='chat_agent',
                        platform=platform,
                        model=model_name,
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                        input_text=input_text,
                        output_text=assistant_reply,
                    )
                except Exception as e:
                    logger.warning(f'chat agent token 记录失败（已忽略）：{e}')
        except Exception as e:
            logger.error(f'chat agent stream failed: {e}')
            yield _ndjson({'type': 'error', 'data': f'出错了：{str(e)}'}).encode('utf-8')

    return StreamingResponse(response_generator(), media_type='application/x-ndjson')
