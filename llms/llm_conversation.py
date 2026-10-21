import os
import json
import datetime
from dotenv import load_dotenv
from openai import OpenAI

# ⚠️ 阿里云百炼的 key 已不再从 .env 读取（config.aliyun_bailian_apikey 已废弃），
#    改由 llms.llm_platform 从 system_setting 表解析 —— 需要先在
#    「系统设置 → 大模型配置」里添加「阿里云百炼」平台并填 Key。
#    客户端懒加载：模块导入期就取 key 会让「还没添加平台」直接变成 ImportError。
_ALIYUN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_client_aliyun = None


def _get_aliyun_client():
    """懒加载 + 进程内缓存阿里云百炼客户端。"""
    global _client_aliyun
    if _client_aliyun is None:
        from llms.llm_platform import get_api_key, get_base_url
        _client_aliyun = OpenAI(
            api_key=get_api_key('aliyun'),
            base_url=get_base_url('aliyun') or _ALIYUN_BASE_URL,
        )
    return _client_aliyun

# DCF分析专属系统提示词，固化分析规则
DCF_ANALYST_PROMPT = """
你是专业的个股DCF估值分析师，严格遵循以下规则完成分析：
1. 所有分析优先沿用本会话历史中用户确认过的DCF参数（无风险利率、市场风险溢价、Beta值、高速增长期年限、永续增长率、各科目预测假设等），除非用户明确要求修改参数
2. 每周五的个股分析需和同一会话下上周的分析结果做同比差异说明，明确标注参数变动、业绩变动导致的估值变化
3. 输出结构统一：核心假设说明、当前DCF估值区间、较上期变化原因、风险提示
"""


class LLMFConversation:
    """个股DCF分析多轮会话管理类"""

    def __init__(self, stock_code: str, history_dir: str = "./dcf_conversation_history"):
        """
        @brief 初始化DCF分析会话，自动加载对应个股的历史对话

        @param stock_code: 个股代码，如600519.SH、AAPL.O，作为会话唯一标识
        @type stock_id: str
        @param history_dir: 历史会话存储目录，默认存在当前目录的dcf_conversation_history文件夹
        @type history_dir: str

        @throws ValueError: 个股代码为空时抛出
        @throws IOError: 历史目录创建失败时抛出
        """
        if not stock_code.strip():
            raise ValueError("个股代码不能为空")

        self.stock_code = stock_code
        self.history_dir = history_dir
        self.history_file = os.path.join(history_dir, f"{stock_code}.json")

        # 初始化存储目录
        os.makedirs(history_dir, exist_ok=True)

        # 加载历史上下文
        self.context = self.load_history()

    def load_history(self) -> list:
        """
        @brief 加载对应个股的历史会话

        @return: 历史对话上下文列表，首次会话返回包含系统提示词的初始上下文
        @rtype: list
        """
        if os.path.exists(self.history_file):
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        # 首次会话初始化
        return [{"role": "system", "content": DCF_ANALYST_PROMPT}]

    def save_history(self) -> None:
        """
        @brief 保存当前会话到本地文件，持久化存储

        @throws IOError: 文件写入失败时抛出
        """
        # 裁剪上下文，避免token超限（最多保留最近10轮对话+系统提示词）
        self._trim_context(max_turns=10)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.context, f, ensure_ascii=False, indent=2)

    def _trim_context(self, max_turns: int = 10) -> None:
        """
        @brief 裁剪上下文长度，避免超过大模型token限制

        @param max_turns: 保留的最大对话轮数（一问一答算1轮）
        @type max_turns: int
        """
        # 永远保留第一条系统提示词
        if len(self.context) > 1 + max_turns * 2:
            self.context = [self.context[0]] + self.context[-(max_turns * 2):]

    def chat(self, user_query: str, save_history: bool = True) -> str:
        """
        @brief 发送查询请求给大模型，返回DCF分析结果

        @param user_query: 用户的查询问题，如"帮我分析贵州茅台2024Q1财报后的DCF估值"
        @type user_query: str
        @param save_history: 是否保存本次对话到历史记录，默认True
        @type save_history: bool

        @return: 大模型返回的DCF分析结果
        @rtype: str

        @throws ValueError: 用户查询为空时抛出
        @throws openai.error.OpenAIError: 大模型接口调用失败时抛出
        """
        if not user_query.strip():
            raise ValueError("查询内容不能为空")

        # 添加用户问题到上下文
        self.context.append({"role": "user", "content": user_query})

        # 调用大模型
        response = _get_aliyun_client().chat.completions.create(
            model='deepseek-v4-flash',
            messages=self.context,
            temperature=0.1,  # 调低温度，保证分析结果一致性
            timeout=60
        )

        answer = response.choices[0].message.content.strip()

        # 添加大模型回复到上下文
        self.context.append({"role": "assistant", "content": answer})

        # 保存历史
        if save_history:
            self.save_history()

        return answer


# ------------------------------
# 示例用法
# ------------------------------
if __name__ == "__main__":
    # 初始化贵州茅台的DCF分析会话，自动加载历史记录
    maotai_conv = LLMFConversation(stock_code="600519.SH")

    # 2024-05-24 第一次分析（周五）
    query1 = "帮我分析贵州茅台2024年Q1财报后的DCF估值，无风险利率设为3%，市场风险溢价5%"
    result1 = maotai_conv.chat(query1)
    print("第一次分析结果：\n", result1)

    # 2024-05-31 第二次分析（下周五），不需要重复输入参数，大模型自动沿用之前的假设
    query2 = "帮我分析贵州茅台2024年5月最新批发价变动后的DCF估值，和上周结果对比差异"
    result2 = maotai_conv.chat(query2)
    print("\n第二次分析结果（自动沿用上周参数）：\n", result2)
