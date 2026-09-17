"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
import requests
from openai import OpenAI
from typing import Optional, Dict, List, Any
from config import mcp_host
from utils.logger import logger


class LLMBase:
    """LLM 基类，封装通用的 OpenAI 兼容接口调用逻辑"""

    # 默认系统提示词（子类可覆盖）
    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    # 默认模型（子类可覆盖）
    model: str = 'qwen3.6-plus'

    # 是否启用搜索（子类可覆盖）
    enable_search: bool = True

    # 响应格式：json_object / text / markdown
    response_format: str = 'text'

    # 单次回答最大输出 token 数
    # 注意：不显式设置时，部分 OpenAI 兼容接口（如火山方舟）会默认一个很小的上限（约 1024），
    # 导致长输出（如深度研究 HTML 研报）被截断。这里给一个较宽松的默认上限。
    max_tokens: int = 32768

    # MCP 服务配置
    mcp_base_url: str = mcp_host

    def __init__(self, client: OpenAI):
        """
        初始化 LLM 基类
        :param client: OpenAI 兼容客户端实例
        """
        self.client = client
        # 实例级缓存，避免类属性共享导致的缓存污染
        self._cached_tools: Optional[List[Dict[str, Any]]] = None

    # ==================== 配置方法 ====================

    def set_response_json(self):
        """设置响应格式为 JSON"""
        self.response_format = 'json_object'

    def set_response_text(self):
        """设置响应格式为纯文本"""
        self.response_format = 'text'

    def set_response_markdown(self):
        """设置响应格式为 Markdown"""
        self.response_format = 'markdown'

    def set_model(self, model: str):
        """设置模型名称"""
        self.model = model

    def set_max_tokens(self, max_tokens: int):
        """设置单次回答最大输出 token 数，用于避免长输出被截断"""
        self.max_tokens = max_tokens

    def set_mcp_url(self, url: str):
        """设置 MCP 服务地址"""
        self.mcp_base_url = url

    # ==================== 核心调用方法 ====================

    def _build_extra_body(self) -> Dict[str, Any]:
        """
        构建 extra_body 参数（子类可覆盖以定制）
        默认启用搜索，火山引擎/智谱等需要覆盖此方法
        """
        return {"enable_search": self.enable_search}

    def ask(self, question: str) -> str:
        """
        简单问答接口
        :param question: 用户问题
        :return: 模型回答文本
        """
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请传入有效的 OpenAI 实例")

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': self.role_base},
                {'role': 'user', 'content': question}
            ],
            response_format={"type": self.response_format},
            max_tokens=self.max_tokens,
            extra_body=self._build_extra_body()
        )
        self._print_token_usage(completion.usage)
        return completion.choices[0].message.content

    def create_completion(self, messages: list) -> object:
        """
        原始对话生成接口（不带工具调用自动处理）
        :param messages: 对话历史
        :return: OpenAI 格式的原始响应
        """
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请传入有效的 OpenAI 实例")

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": self.response_format},
            max_tokens=self.max_tokens,
            extra_body=self._build_extra_body()
        )

        self._print_token_usage(completion.usage)
        return completion

    # ==================== MCP 工具调用 ====================

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """获取 MCP 工具元数据（带实例级缓存）"""
        if self._cached_tools is None:
            try:
                resp = requests.get(f"{self.mcp_base_url}/tools", timeout=5)
                resp.raise_for_status()
                self._cached_tools = resp.json().get('data', [])
            except Exception as e:
                logger.warning(f"获取 MCP 工具元数据失败：{e}")
                self._cached_tools = []
        return self._cached_tools

    def _call_mcp_tool(self, function_name: str, parameters: dict) -> dict:
        """调用 MCP 工具接口"""
        try:
            resp = requests.post(
                f"{self.mcp_base_url}/call",
                json={"function_name": function_name, "parameters": parameters},
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"MCP 工具调用失败：{e}")
            return {"code": 500, "msg": f"MCP 服务异常：{e}", "data": None}

    def create_completion_with_tools(self, messages: list) -> dict:
        """
        带工具调用的对话生成：兼容 Qwen/OpenAI 标准格式 + DeepSeek 自定义格式
        :param messages: 对话历史列表（格式同 OpenAI）
        :return: 包含最终回答、工具调用记录的字典
        """
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请传入有效的 OpenAI 实例")

        tool_call_history = []
        current_messages = list(messages)  # 避免修改原列表
        mcp_tools = self._get_mcp_tools()
        valid_function_names = {tool["function"]["name"] for tool in mcp_tools} if mcp_tools else set()

        while True:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=current_messages,
                response_format={"type": self.response_format},
                tools=mcp_tools,
                tool_choice="auto" if mcp_tools else "none",
                max_tokens=self.max_tokens,
                extra_body=self._build_extra_body(),
                stream=False
            )

            assistant_message = completion.choices[0].message
            self._print_token_usage(completion.usage)

            # 解析工具调用（兼容标准格式 + DeepSeek 格式）
            tool_calls = self._parse_tool_calls(assistant_message, valid_function_names)

            if tool_calls:
                # 处理工具调用
                tool_call_results = []
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        logger.warning(f"工具参数解析失败：{e}")
                        tool_result = {"code": 400, "msg": "参数格式错误", "data": None}
                        function_args = {}
                    else:
                        tool_result = self._call_mcp_tool(function_name, function_args)

                    tool_call_history.append({
                        "function_name": function_name,
                        "parameters": function_args,
                        "result": tool_result
                    })
                    tool_call_results.append((tool_call, tool_result))

                # 构建消息扩展
                new_messages = [assistant_message]
                for tool_call, tool_result in tool_call_results:
                    new_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            tool_result.get('data') if tool_result.get('code') == 0 else tool_result.get('msg'),
                            ensure_ascii=False
                        )
                    })
                current_messages.extend(new_messages)
            else:
                # 无工具调用，返回最终回答
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

        # 尝试解析 DeepSeek 格式：content 为 JSON 字符串，键为函数名
        if assistant_message.content:
            try:
                content_json = json.loads(assistant_message.content.strip())
                if isinstance(content_json, dict) and len(content_json) == 1:
                    function_name = next(iter(content_json.keys()))
                    if function_name in valid_function_names:
                        # 构造模拟的 tool_call 对象
                        mock_function = type('MockFunction', (), {
                            'name': function_name,
                            'arguments': json.dumps(content_json[function_name])
                        })()
                        mock_tool_call = type('MockToolCall', (), {
                            'id': f'call_{hash(function_name + str(content_json))}',
                            'function': mock_function
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
