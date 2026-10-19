"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from openai import OpenAI

# ⚠️ 阿里云百炼的 key 已不再从 .env 读取（config.aliyun_bailian_apikey 已废弃），
#    统一由 llms.llm_platform 从 system_setting 表解析 —— 需要先在
#    「系统设置 → 大模型配置」里添加「阿里云百炼」平台并填 Key。
#
# ⚠️ 客户端**故意做成懒加载**（原来在模块导入时就 new OpenAI）：
#    模块导入期就取 key 的话，管理员还没添加平台时整个 job 模块直接 ImportError，
#    报错还指向 import 语句，排障方向完全错。改成调用时解析，未配置就在真正
#    用到它的那一步报错。
_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_MODEL = "text-embedding-v4" # 阿里最新的 Embedding 模型

_client = None


def _get_client():
    """懒加载 + 进程内缓存 OpenAI 客户端（key 换了需重启进程，与各 LLM 平台实现一致）。"""
    global _client
    if _client is None:
        from llms.llm_platform import get_api_key, get_base_url
        _client = OpenAI(
            api_key=get_api_key('aliyun'),
            base_url=get_base_url('aliyun') or _BASE_URL,
        )
    return _client


def get_embedding(text: str):
    """
    调用阿里 DashScope API 获取文本向量
    Args:
        text: 输入文本
    Returns:
        向量列表 (List[float])
    """
    client = _get_client()
    # DashScope 的 text-embedding-v4 支持 dimensions 参数
    # 这里我们使用默认维度（通常为 1024），你也可以显式指定 dimensions=1024
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        # dimensions=1024, # 如果需要指定维度可以取消注释
    )
    # 返回 embedding 向量
    return response.data[0].embedding
