"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from openai import OpenAI
from config import siliconflow_apikey
from llms.llm_base import LLMBase


class LLMBaseSiliconflow(LLMBase):
    """SiliconFlow LLM 实现"""

    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    model = "MiniMaxAI/MiniMax-M2.5"
    enable_search = True
    response_format = 'text'

    def __init__(self):
        client = OpenAI(
            api_key=siliconflow_apikey,
            base_url="https://api.siliconflow.cn",
        )
        super().__init__(client)

    def _build_extra_body(self):
        """SiliconFlow 使用 thinking 参数控制深度思考"""
        return {
            "thinking": {
                "type": "disabled"  # 不使用深度思考能力
            }
        }
