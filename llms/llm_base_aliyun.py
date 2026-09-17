"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from openai import OpenAI
from config import aliyun_bailian_apikey
from llms.llm_base import LLMBase


class LLMBaseAliyun(LLMBase):
    """阿里云百炼 LLM 实现"""

    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    model = 'qwen3.6-plus'
    enable_search = True
    response_format = 'text'

    def __init__(self):
        client = OpenAI(
            api_key=aliyun_bailian_apikey,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        super().__init__(client)
