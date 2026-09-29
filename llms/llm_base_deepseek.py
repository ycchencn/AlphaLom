"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from openai import OpenAI
from llms.llm_base import LLMBase
from llms.llm_platform import get_api_key, get_base_url


class LLMBaseDeepSeek(LLMBase):
    """DeepSeek LLM 实现"""

    # 平台标识：供 llms.llm_platform 解析运行时凭据（key / base_url / 启用开关）
    platform_name = 'deepseek'

    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    model = 'deepseek-v4-flash'
    enable_search = True
    response_format = 'text'

    def __init__(self):
        # key / base_url 改为运行时解析：system_setting 表覆盖 ← env 默认值。
        # 平台被禁用或未配 key 时 get_api_key 抛 ValueError（明确报错，不静默回退）。
        client = OpenAI(
            api_key=get_api_key(self.platform_name),
            base_url=get_base_url(self.platform_name),
        )
        super().__init__(client)
