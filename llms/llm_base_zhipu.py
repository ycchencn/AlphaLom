"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from zai import ZhipuAiClient
from llms.llm_base import LLMBase
from llms.llm_platform import get_api_key


class LLMBaseZhipu(LLMBase):
    """智谱 LLM 实现"""

    # 平台标识：供 llms.llm_platform 解析运行时凭据（key / 启用开关）
    platform_name = 'zhipu'

    role_base = (
        '你是一个量化交易金融机构的专家，擅长解答股票、基金、金融市场相关问题。'
        '当需要获取实时数据时，请严格调用提供的工具，不要编造信息。'
        '请根据工具返回的结果，用自然语言整理成清晰易懂的回答。'
    )

    model = "glm-5"
    enable_search = True
    response_format = 'text'
    thinking = "disabled"

    def __init__(self):
        # ZhipuAiClient 的 base_url 是 SDK 内置的，不支持覆盖，故只解析 key。
        client = ZhipuAiClient(api_key=get_api_key(self.platform_name))
        super().__init__(client)

    def ask(self, question: str) -> str:
        """智谱 API 使用不同的参数结构"""
        if not self.client:
            raise ValueError("LLM 客户端未初始化，请传入有效的 ZhipuAiClient 实例")

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': self.role_base},
                {'role': 'user', 'content': question}
            ],
            thinking={
                "type": self.thinking,
            },
            max_tokens=self.max_tokens,
            temperature=1.0
        )
        self._print_token_usage(completion.usage, input_text=question,
                                output_text=completion.choices[0].message.content)
        return completion.choices[0].message.content


if __name__ == '__main__':
    staff = LLMBaseZhipu()
    staff.set_model(model='GLM-4.7-Flash')
    resp = staff.ask('你是谁, 支持最大多少上下文')
    print(resp)
