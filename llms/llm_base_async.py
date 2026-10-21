"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
import aiohttp
from openai import AsyncOpenAI
from typing import Optional, Dict, List, Any
from config import mcp_host
from utils.logger import logger


class LLMBaseAsync:
    """LLM 异步基类，封装通用的 OpenAI 兼容接口异步调用逻辑"""

    # 默认系统提示词
    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '分析问题的时候尽量使用系统提供的 mcp 服务，这些是比较准确的数据。'
    )

    # 默认模型
    model: str = 'deepseek-v4-flash'

    # 是否启用搜索
    enable_search: bool = True

    # 响应格式
    response_format: str = 'text'

    # MCP 服务配置
    # ⚠️ 允许为 None：MCP_HOST 未配置时表示「本部署不启用 MCP」，此时整体短路降级为纯文本
    mcp_base_url: Optional[str] = mcp_host

    def __init__(self, client: AsyncOpenAI):
        """
        初始化异步 LLM 基类
        :param client: AsyncOpenAI 客户端实例
        """
        self.client = client
        self.session: Optional[aiohttp.ClientSession] = None
        # 实例级缓存
        self._cached_tools: Optional[List[Dict[str, Any]]] = None
        # token 使用量记录上下文（与 LLMBase 对齐）
        self.scene = None
        self.platform = None

    # ==================== 生命周期管理 ====================

    async def ensure_session(self):
        """确保异步 HTTP 会话已创建（延迟初始化）"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close_session(self):
        """关闭异步 HTTP 会话"""
        if self.session and not self.session.closed:
            await self.session.close()

    # ==================== 配置方法 ====================

    def set_response_json(self):
        """设置响应格式为 JSON"""
        self.response_format = 'json_object'

    def set_response_text(self):
        """设置响应格式为纯文本"""
        self.response_format = 'text'

    def set_model(self, model: str):
        """设置模型名称"""
        self.model = model

    def set_mcp_url(self, url: str):
        """设置 MCP 服务地址（传空/None 视为关闭 MCP）"""
        self.mcp_base_url = (url or '').strip() or None

    # ==================== MCP 开关判定 ====================

    @property
    def mcp_enabled(self) -> bool:
        """本实例是否可用 MCP（MCP_HOST 未配置时为 False，工具链路整体短路）"""
        url = self.mcp_base_url
        if url is None:
            return False
        if not isinstance(url, str):
            return True
        return bool(url.strip())

    # ==================== MCP 工具调用 ====================

    async def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """异步获取 MCP 工具元数据（带实例级缓存）"""
        if not self.mcp_enabled:
            # 未配置 MCP：不缓存空列表，避免调用方误判为「已加载过、只是暂时为空」
            return []
        await self.ensure_session()
        if self._cached_tools is None:
            try:
                async with self.session.get(f"{self.mcp_base_url}/tools", timeout=5) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    self._cached_tools = result.get('data', [])
                    tool_names = [tool['function']['name'] for tool in self._cached_tools]
                    logger.debug(f"成功加载 MCP 工具：{tool_names}")
            except Exception as e:
                logger.warning(f"获取 MCP 工具元数据失败：{e}")
                self._cached_tools = []
        return self._cached_tools

    async def _call_mcp_tool(self, function_name: str, parameters: dict) -> dict:
        """异步调用 MCP 工具接口"""
        if not self.mcp_enabled:
            return {"code": 503, "msg": "MCP 服务未配置（MCP_HOST 为空），无法调用工具", "data": None}
        await self.ensure_session()
        logger.debug(f"调用 MCP 工具：{function_name}, {parameters}")
        try:
            async with self.session.post(
                f"{self.mcp_base_url}/call",
                json={"function_name": function_name, "parameters": parameters},
                timeout=10
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"MCP 工具调用失败：{e}")
            return {"code": 500, "msg": f"MCP 服务异常：{e}", "data": None}

    # ==================== 核心调用方法 ====================

    async def create_completion_with_tools(self, messages: list) -> dict:
        """
        异步带工具调用的对话生成：兼容 Qwen/OpenAI 标准格式 + DeepSeek 自定义格式
        :param messages: 对话历史列表（格式同 OpenAI）
        :return: 包含最终回答、工具调用记录的字典
        """
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请传入有效的 AsyncOpenAI 实例")

        tool_call_history = []
        current_messages = list(messages)  # 避免修改原列表
        mcp_tools = await self._get_mcp_tools()
        valid_function_names = {tool["function"]["name"] for tool in mcp_tools} if mcp_tools else set()

        if not mcp_tools:
            # 调用点的 system prompt 常硬编码「请主动调用 MCP 工具取数」。工具一个都没有时
            # 这句指令会让模型要么反复调用不存在的函数、要么编造实时数据 —— 补一条说明。
            current_messages.insert(0, {
                'role': 'system',
                'content': '当前环境未挂载任何工具，无法获取实时行情/财务/新闻数据。'
                           '请仅基于用户消息中已提供的上下文作答，'
                           '并明确说明你无法获取实时数据，不要编造具体价格与财务数字。',
            })
            logger.info('MCP 未配置或不可用，本次以纯文本模式调用（无工具）')

        while True:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=current_messages,
                response_format={"type": self.response_format},
                # ⚠️ 空列表不能传给 tools：部分 OpenAI 兼容网关会直接报参数错误
                tools=mcp_tools if mcp_tools else None,
                tool_choice="auto" if mcp_tools else None,
                extra_body={"enable_search": self.enable_search},
                stream=False
            )

            assistant_message = completion.choices[0].message
            self._print_token_usage(completion.usage, input_text=self._messages_to_text(current_messages),
                                    output_text=assistant_message.content or '')

            # 解析工具调用（兼容标准格式 + DeepSeek 格式）
            tool_calls = self._parse_tool_calls(assistant_message, valid_function_names)

            if tool_calls:
                # 处理工具调用
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        logger.warning(f"工具参数解析失败：{e}")
                        tool_result = {"code": 400, "msg": "参数格式错误", "data": None}
                        function_args = {}
                    else:
                        tool_result = await self._call_mcp_tool(function_name, function_args)

                    tool_call_history.append({
                        "function_name": function_name,
                        "parameters": function_args,
                        "result": tool_result
                    })

                    # 将工具结果添加到对话历史
                    current_messages.extend([
                        {
                            "role": "assistant",
                            "content": assistant_message.content or "",
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "function": {
                                        "name": tool_call.function.name,
                                        "arguments": tool_call.function.arguments
                                    }
                                }
                            ] if tool_calls else []
                        },
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(
                                tool_result.get('data') if tool_result.get('code') == 0 else tool_result.get('msg'),
                                ensure_ascii=False
                            )
                        }
                    ])
            else:
                # 无工具调用，返回结果
                return {
                    "final_answer": assistant_message.content,
                    "tool_calls": tool_call_history,
                    "raw_response": completion
                }

    def _parse_tool_calls(self, assistant_message, valid_function_names: set) -> list:
        """
        解析工具调用，兼容标准 OpenAI 格式和 DeepSeek 自定义格式
        :param assistant_message: 模型返回的 message 对象
        :param valid_function_names: 有效的函数名集合
        :return: 工具调用列表
        """
        # 优先处理标准 OpenAI 格式
        if assistant_message.tool_calls:
            return assistant_message.tool_calls

        # 尝试解析 DeepSeek 格式
        if assistant_message.content:
            try:
                content_json = json.loads(assistant_message.content.strip())
                if isinstance(content_json, dict) and len(content_json) == 1:
                    function_name = next(iter(content_json.keys()))
                    if function_name in valid_function_names:
                        mock_tool_call = type('MockToolCall', (), {
                            'id': f'call_{hash(function_name + str(content_json))}',
                            'function': type('MockFunction', (), {
                                'name': function_name,
                                'arguments': json.dumps(content_json[function_name])
                            })()
                        })()
                        logger.debug(f"检测到 DeepSeek 格式工具调用：{function_name}")
                        return [mock_tool_call]
            except json.JSONDecodeError:
                pass

        return []

    # ==================== 辅助方法 ====================

    def _print_token_usage(self, usage, input_text='', output_text='') -> dict:
        """打印并记录 Token 消耗统计（落库见 llms.usage_recorder）。"""
        if not usage:
            return {}
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)
        total_tokens = getattr(usage, 'total_tokens', 0)
        logger.info(f"📊 Token 统计：输入 {prompt_tokens} | 输出 {completion_tokens} | 总计 {total_tokens}，模型：{self.model}")
        try:
            from utils.auth import request_user_id_var
            from llms.usage_recorder import record_llm_usage
            record_llm_usage(
                user_id=request_user_id_var.get(),
                scene=self.scene,
                platform=self.platform,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                input_text=input_text,
                output_text=output_text,
            )
        except Exception as e:
            logger.warning(f"token 使用记录异常（已忽略）：{e}")
        return {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens
        }

    def _messages_to_text(self, messages) -> str:
        """把 messages 列表拼成可读文本（多模态 content 提取文本段），用于 usage 记录。"""
        if not messages:
            return ''
        parts = []
        for m in messages:
            if not isinstance(m, dict):
                parts.append(str(m))
                continue
            role = m.get('role', 'user')
            content = m.get('content', '')
            if isinstance(content, list):
                segs = []
                for seg in content:
                    if isinstance(seg, dict) and seg.get('type') == 'text':
                        segs.append(seg.get('text', ''))
                    elif isinstance(seg, str):
                        segs.append(seg)
                content = '\n'.join(segs)
            parts.append(f"[{role}]\n{content}")
        return '\n\n'.join(parts)
