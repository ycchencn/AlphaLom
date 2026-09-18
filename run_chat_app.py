"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from utils.logger import logger
from utils.common import get_today
from typing import Optional, Dict, List
# from config import aliyun_bailian_apikey
from llms.llm_base_async import LLMBaseAsync
from contextlib import asynccontextmanager  # 新增导入
from utils.redis_obj import redis_obj
from routes.syslog import syslog_router

init_prompt = f"今天是：{get_today()}\n"

# -------------------------- 最大上下文消息数限制 --------------------------
MAX_CONTEXT_MESSAGES = 20  # 保留的系统提示 + 最近19条对话消息


# -------------------------- FastAPI生命周期事件（替换on_event） --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时释放资源"""
    # 启动事件：初始化异步HTTP会话
    await llm_base.ensure_session()
    logger.info("✅ 服务启动成功，异步HTTP会话已初始化")

    yield  # 应用运行期间

    # 关闭事件：释放异步HTTP会话
    await llm_base.close_session()
    logger.info("✅ 服务已关闭，异步HTTP会话已释放")


# 创建FastAPI实例时传入lifespan
app = FastAPI(
    title="量化金融AI对话服务（兼容MCP工具调用）",
    lifespan=lifespan  # 替换原来的on_event
)


# -------------------------- 请求模型 --------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., description="用户文本消息")
    session_id: str = Field(..., description="会话ID")
    response_format: Optional[str] = Field("text", description="返回格式：json_object/text")
    model: Optional[str] = Field("qwen3.6-plus", description="模型名称")


# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册系统日志路由
app.include_router(syslog_router)

# 全局LLM客户端实例（仅初始化OpenAI，不创建aiohttp会话）
llm_client = AsyncOpenAI(
    api_key=os.environ.get('DEEPSEEK_APIKEY'),
    base_url="https://api.deepseek.com"
)
llm_base = LLMBaseAsync(llm_client)


# 获取会话历史
def get_session_history(session_id: str) -> List[Dict]:
    history = redis_obj.get(f"chat_session:{session_id}")
    if not history:
        return [{
            "role": "system",
            "content": init_prompt + llm_base.role_base
        }]
    try:
        return json.loads(history)
    except:
        return [{
            "role": "system",
            "content": init_prompt + llm_base.role_base
        }]


# 保存会话历史（增加最大上下文限制）
def save_session_history(session_id: str, history: List[Dict]):
    # 上下文长度限制：保留第一条 system 消息 + 最近的 (MAX_CONTEXT_MESSAGES-1) 条消息
    if len(history) > MAX_CONTEXT_MESSAGES:
        # 查找 system 消息
        system_msg = None
        for msg in history:
            if msg.get("role") == "system":
                system_msg = msg
                break

        trimmed = []
        if system_msg:
            trimmed.append(system_msg)
            # 排除所有 system 消息，保留最近的 N-1 条
            non_system = [msg for msg in history if msg.get("role") != "system"]
            trimmed.extend(non_system[-(MAX_CONTEXT_MESSAGES - 1):])
        else:
            # 如果没有 system 消息，直接保留最近 N 条
            trimmed = history[-MAX_CONTEXT_MESSAGES:]
        history = trimmed

    redis_obj.setex(f"chat_session:{session_id}", 86400, json.dumps(history))


# -------------------------- 流式对话接口 --------------------------
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    try:
        # 配置LLM参数
        if request.response_format == "text":
            llm_base.set_response_text()
        else:
            llm_base.set_response_json()

        # 设置大模型版本
        llm_base.set_model(request.model)

        # 获取会话历史
        history = get_session_history(request.session_id)
        history.append({"role": "user", "content": request.message.strip()})

        # 第一步：处理工具调用（非流式）
        tool_result = await llm_base.create_completion_with_tools(history)
        final_answer = tool_result["final_answer"]
        tool_calls = tool_result["tool_calls"]

        # 更新会话历史（添加工具调用记录和最终回答）
        if tool_calls:
            # 工具调用记录已在create_completion_with_tools中添加到history
            pass
        history.append({"role": "assistant", "content": final_answer})
        save_session_history(request.session_id, history)

        # 第二步：流式返回最终回答（模拟打字机效果）
        async def generate_response():
            for char in final_answer:
                yield char.encode("utf-8")
                await asyncio.sleep(0.02)  # 打字速度控制

        return StreamingResponse(generate_response(), media_type="text/plain")

    except Exception as e:
        logger.error(f"对话处理失败：{str(e)}")
        raise HTTPException(status_code=500, detail=f"服务异常：{str(e)}")


# -------------------------- 工具调用历史查询接口 --------------------------
@app.get("/chat/tool-history/{session_id}")
async def get_tool_history(session_id: str):
    try:
        history = get_session_history(session_id)
        tool_calls = [msg for msg in history if msg.get("role") == "tool"]
        return {"code": 200, "data": tool_calls}
    except Exception as e:
        logger.error(f"查询工具历史失败：{str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
