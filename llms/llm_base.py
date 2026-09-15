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


class LLMBase:
    role_base = (
        '你是一个量化交易金融机构的专家'
        '请以JSON格式输出'
    )

    client: Optional[OpenAI] = None

    model: str = 'qwen3.6-plus'

    enable_search = True

    response_format = 'json_object'

    # 单次回答最大输出 token 数。
    # 注意：不显式设置时，部分 OpenAI 兼容接口（如火山方舟）会默认一个很小的上限（约 1024），
    # 导致长输出（如深度研究 HTML 研报）被截断。这里给一个较宽松的默认上限。
    max_tokens = 8192

    # MCP服务配置（可根据环境修改）
    mcp_base_url = mcp_host

    # 缓存工具元数据，避免重复请求MCP
    _cached_tools: Optional[List[Dict[str, Any]]] = None

    def __init__(self, client):
        self.client = client

    def set_response_json(self):
        self.response_format = 'json_object'

    def set_response_text(self):
        self.response_format = 'text'

    def set_response_markdown(self):
        self.response_format = 'markdown'

    def set_model(self, model):
        self.model = model

    def set_max_tokens(self, max_tokens: int):
        """设置单次回答最大输出 token 数，用于避免长输出被截断"""
        self.max_tokens = max_tokens

    def ask(self, question):
        """
        ask ai
        :param question:
        :return:
        """

        if not self.client:
            raise ValueError("LLM客户端未初始化，请传入有效的OpenAI实例")

        # 模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': self.role_base},
                {'role': 'user', 'content': question}
            ],
            response_format={"type": self.response_format},
            max_tokens=self.max_tokens,
            extra_body={"enable_search": self.enable_search}
        )
        self._print_token_usage(completion.usage)
        return completion.choices[0].message.content

    def create_completion(self, messages: list) -> object:
        """
        原始对话生成接口（不带工具调用自动处理）
        :param messages: 对话历史
        :return: OpenAI格式的原始响应
        """
        if not self.client:
            raise ValueError("LLM客户端未初始化，请传入有效的OpenAI实例")

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": self.response_format},
            max_tokens=self.max_tokens,
            extra_body={"enable_search": self.enable_search}
        )

        self._print_token_usage(completion.usage)

        return completion

    def set_mcp_url(self, url):
        """设置MCP服务地址"""
        self.mcp_base_url = url

    def _get_mcp_tools(self):
        """获取MCP工具元数据（带缓存）"""
        if self._cached_tools is None:
            try:
                resp = requests.get(f"{self.mcp_base_url}/tools", timeout=5)
                resp.raise_for_status()
                self._cached_tools = resp.json()['data']
            except Exception as e:
                print(f"获取MCP工具元数据失败：{str(e)}")
                self._cached_tools = []
        return self._cached_tools

    def _call_mcp_tool(self, function_name: str, parameters: dict) -> dict:
        """调用MCP工具接口"""
        try:
            resp = requests.post(
                f"{self.mcp_base_url}/call",
                json={
                    "function_name": function_name,
                    "parameters": parameters
                },
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"MCP工具调用失败：{str(e)}")
            return {"code": 500, "msg": f"MCP服务异常：{str(e)}", "data": None}

    def create_completion_with_tools(self, messages: list) -> dict:
        """
        带工具调用的对话生成：兼容Qwen/OpenAI标准格式+DeepSeek自定义格式
        :param messages: 对话历史列表（格式同OpenAI）
        :return: 包含最终回答、工具调用记录的字典
        """
        if not self.client:
            raise ValueError("LLM客户端未初始化，请传入有效的OpenAI实例")

        tool_call_history = []
        current_messages = messages.copy()
        # 预加载MCP工具列表，用于验证函数有效性
        mcp_tools = self._get_mcp_tools()
        valid_function_names = {tool["function"]["name"] for tool in mcp_tools} if mcp_tools else set()

        while True:
            # 调用大模型
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=current_messages,
                response_format={"type": self.response_format},
                tools=mcp_tools,
                tool_choice="auto" if mcp_tools else "none",
                max_tokens=self.max_tokens,
                extra_body={"enable_search": self.enable_search},
                stream=False
            )

            assistant_message = completion.choices[0].message
            # 3. 打印Token统计
            self._print_token_usage(completion.usage)

            # -------------------------- 新增：兼容DeepSeek格式 --------------------------
            # 初始化工具调用列表（兼容两种格式）
            tool_calls = None

            # 优先处理Qwen/OpenAI标准格式
            if assistant_message.tool_calls:
                tool_calls = assistant_message.tool_calls
                print("📌 检测到标准工具调用格式（Qwen/OpenAI）")
            elif assistant_message.content:
                # 尝试解析DeepSeek格式：content为JSON字符串，键为函数名，值为参数
                try:
                    content_json = json.loads(assistant_message.content.strip())
                    # 验证格式：单键值对，且键为有效的MCP函数名
                    if isinstance(content_json, dict) and len(content_json) == 1:
                        function_name = next(iter(content_json.keys()))
                        if function_name in valid_function_names:
                            # 模拟标准tool_call结构（动态创建对象兼容原有逻辑）
                            mock_function = type('MockFunction', (object,), {
                                'name': function_name,
                                'arguments': json.dumps(content_json[function_name])
                            })()
                            mock_tool_call = type('MockToolCall', (object,), {
                                'id': f'call_{hash(function_name + str(content_json))}',
                                'function': mock_function
                            })()
                            tool_calls = [mock_tool_call]
                            print(f"📌 检测到DeepSeek格式工具调用：{function_name}")
                except json.JSONDecodeError:
                    # content不是有效JSON，视为普通回答
                    pass

            # -------------------------- 统一处理工具调用 --------------------------
            if tool_calls:
                # 收集所有工具调用结果
                tool_call_results = []  # 保存 (tool_call, tool_result) 对
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        print(f"工具参数解析失败：{str(e)}")
                        tool_result = {"code": 400, "msg": "参数格式错误", "data": None}
                    else:
                        tool_result = self._call_mcp_tool(function_name, function_args)

                    # print(f"tool_call, {function_name}, {tool_result}")

                    tool_call_history.append({
                        "function_name": function_name,
                        "parameters": function_args,
                        "result": tool_result
                    })

                    tool_call_results.append((tool_call, tool_result))

                # 构建要追加的消息：先 assistant_message，再逐一添加 tool 消息
                new_messages = [assistant_message]
                for tool_call, tool_result in tool_call_results:
                    new_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            tool_result['data'] if tool_result['code'] == 0 else tool_result['msg'],
                            ensure_ascii=False
                        )
                    })

                # 一次性扩展消息列表
                current_messages.extend(new_messages)
                # 继续循环，让模型处理工具返回结果
            else:
                # 无工具调用，返回最终回答
                return {
                    "final_answer": assistant_message.content,
                    "tool_calls": tool_call_history,
                    "raw_response": completion
                }

    def _print_token_usage(self, usage):
        """打印Token消耗统计"""
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        total_tokens = usage.total_tokens
        print(f"📊 Token统计：输入{prompt_tokens} | 输出{completion_tokens} | 总计{total_tokens}，模型：{self.model}")
        return {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens
        }
