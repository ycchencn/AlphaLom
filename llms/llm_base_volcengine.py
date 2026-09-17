"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from openai import OpenAI
from config import ark_apikey
from llms.llm_base import LLMBase


class LLMBaseVolcEngine(LLMBase):
    """火山引擎 LLM 实现"""

    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    model = "doubao-seed-1-6-flash-250828"
    enable_search = True
    response_format = 'text'

    def __init__(self):
        client = OpenAI(
            api_key=ark_apikey,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        super().__init__(client)

    def _build_extra_body(self):
        """火山引擎使用 thinking 参数控制深度思考"""
        return {
            "thinking": {
                "type": "disabled"  # 不使用深度思考能力
            }
        }
