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

    # 工具结果回灌给大模型时的单条字符上限。
    # ⚠️ MCP 的 get_stock_detail 会返回整段公司简介/经营范围（实测单只票几千字），
    # 不截断的话几轮工具调用就能把上下文撑爆（token 成本 + 触发截断丢历史）。
    tool_result_max_chars: int = 6000

    # 工具调用循环的硬上限。
    # ⚠️ 缺失这个上限时 `while True` 是**无界**的：模型反复要求查数据就能一直烧 token
    # （缓存未命中时每次调用都是真实计费），且失败重试型模型会陷入死循环。
    max_tool_rounds: int = 8

    def __init__(self, client: OpenAI):
        """
        初始化 LLM 基类
        :param client: OpenAI 兼容客户端实例
        """
        self.client = client
        # 实例级缓存，避免类属性共享导致的缓存污染
        self._cached_tools: Optional[List[Dict[str, Any]]] = None
        # token 使用量记录用的上下文字段：由 get_model_by_setting 写入 scene/platform，
        # user_id 来自请求级 ContextVar（见 llms.usage_recorder）。基类默认 None，
        # 未经由 get_model_by_setting 直接实例化的子类记录为 NULL。
        self.scene = None
        self.platform = None

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
        self._print_token_usage(completion.usage, input_text=question,
                                output_text=completion.choices[0].message.content)
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

        self._print_token_usage(completion.usage, input_text=self._messages_to_text(messages),
                                output_text=completion.choices[0].message.content)
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

    def _serialize_tool_result(self, tool_result: dict) -> str:
        """
        把工具返回值序列化成回灌给大模型的文本，并做长度截断。

        ⚠️ 截断而不是丢弃：MCP 的部分工具（get_stock_detail）返回体里
        `company_introduction` / `business_scope` 这类长文本占了绝大部分体积，
        而模型真正需要的是行情/财务数值。直接截断既控住 token，又保留前半段的数值字段。
        """
        payload = tool_result.get('data') if tool_result.get('code') == 0 else tool_result.get('msg')
        text = json.dumps(payload, ensure_ascii=False)
        limit = self.tool_result_max_chars
        if limit and len(text) > limit:
            # 明确告诉模型「被截断了」，否则它会以为数据就这么少，据此下错结论
            text = text[:limit] + f'\n...[工具结果过长已截断，原始长度 {len(text)} 字符]'
        return text

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

        rounds = 0
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
            self._print_token_usage(completion.usage, input_text=self._messages_to_text(current_messages),
                                    output_text=assistant_message.content or '')

            # 解析工具调用（兼容标准格式 + DeepSeek 格式）
            tool_calls = self._parse_tool_calls(assistant_message, valid_function_names)

            if tool_calls:
                rounds += 1
                # 用完配额：不再把 tool 结果回灌，而是让模型基于已有信息直接收尾。
                # 直接把最后一次的 content 当答案返回，比抛异常更稳（调用方多半只要一段文本）。
                if rounds > self.max_tool_rounds:
                    logger.warning(
                        f"工具调用达到上限 {self.max_tool_rounds} 轮，强制结束并返回当前内容"
                    )
                    return {
                        "final_answer": assistant_message.content or '',
                        "tool_calls": tool_call_history,
                        "raw_response": completion,
                        "truncated": True,
                    }

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
                        "content": self._serialize_tool_result(tool_result)
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

    def _print_token_usage(self, usage, input_text='', output_text='') -> dict:
        """打印并记录 Token 消耗统计（落库见 llms.usage_recorder）。"""
        if not usage:
            return {}
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)
        total_tokens = getattr(usage, 'total_tokens', 0)
        logger.info(f"📊 Token 统计：输入 {prompt_tokens} | 输出 {completion_tokens} | 总计 {total_tokens}，模型：{self.model}")
        # 落库（失败不影响主链路）；input_text/output_text 由调用点传入
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
