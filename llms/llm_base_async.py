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
    mcp_base_url: str = mcp_host

    def __init__(self, client: AsyncOpenAI):
        """
        初始化异步 LLM 基类
        :param client: AsyncOpenAI 客户端实例
        """
        self.client = client
        self.session: Optional[aiohttp.ClientSession] = None
        # 实例级缓存
        self._cached_tools: Optional[List[Dict[str, Any]]] = None

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
        """设置 MCP 服务地址"""
        self.mcp_base_url = url

    # ==================== MCP 工具调用 ====================

    async def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """异步获取 MCP 工具元数据（带实例级缓存）"""
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

        while True:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=current_messages,
                response_format={"type": self.response_format},
                tools=mcp_tools,
                tool_choice="auto" if mcp_tools else "none",
                extra_body={"enable_search": self.enable_search},
                stream=False
            )

            assistant_message = completion.choices[0].message
            self._print_token_usage(completion.usage)

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

    def _print_token_usage(self, usage) -> dict:
        """打印 Token 消耗统计"""
        if not usage:
            return {}
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)
        total_tokens = getattr(usage, 'total_tokens', 0)
        logger.info(f"📊 Token 统计：输入 {prompt_tokens} | 输出 {completion_tokens} | 总计 {total_tokens}，模型：{self.model}")
        return {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens
        }
