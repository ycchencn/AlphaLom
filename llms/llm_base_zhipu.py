"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from zai import ZhipuAiClient
from config import zhipu_api
from llms.llm_base import LLMBase

# 定义系统提示词
system_prompt = """
你是一个量化交易金融机构的专家，负责解答用户的各种问题。
"""

class LLMBaseZhipu(LLMBase):

    role_base = system_prompt

    client = ZhipuAiClient(api_key=zhipu_api)

    model = "glm-5"

    enable_search = True

    response_format = 'text'

    thinking = "disabled"

    def set_model(self, model):
        self.model = model

    def set_response_json(self):
        self.response_format = 'json_object'

    def set_response_text(self):
        self.response_format = 'text'

    def __init__(self):
        super().__init__(self.client)

    def ask(self, question):
        """
        ask ai
        :param question:
        :return:
        """
        # 调用方舟模型生成响应
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': self.role_base},
                {'role': 'user', 'content': question}
            ],
            thinking={
                "type": self.thinking,  # 启用深度思考模式
            },
            max_tokens=self.max_tokens,
            temperature=1.0  # 控制输出的随机性
        )
        return completion.choices[0].message.content

if __name__ == '__main__':

    staff = LLMBaseZhipu()
    staff.set_model(model='GLM-4.7-Flash')

    resp = staff.ask('你是谁, 支持最大多少上下文')

    print(resp)
