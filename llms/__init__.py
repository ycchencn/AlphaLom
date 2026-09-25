"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import random
from typing import Optional, Dict, Any, List

from openai import OpenAI

# llm_model_setting 仍然从 config 导入并在此 re-export（历史调用方可能直接取它）；
# 但运行时**生效值**以 llms.llm_setting 的解析结果为准 = config 默认值 ← system_setting 表覆盖
from config import llm_model_setting, zhipu_api
from llms.llm_setting import (LLM_SETTING_GROUP, LLM_SETTING_SCENES, get_llm_model_settings,
                              get_llm_setting, list_scenes, setting_key)
from llms.llm_base_aliyun import LLMBaseAliyun
from llms.llm_base_deepseek import LLMBaseDeepSeek
from llms.llm_base_siliconflow import LLMBaseSiliconflow
from llms.llm_base_volcengine import LLMBaseVolcEngine
from llms.llm_base_zhipu import LLMBaseZhipu
from utils.logger import logger

# 平台 → LLM 实现类映射
_PLATFORM_REGISTRY: Dict[str, type] = {
    'deepseek': LLMBaseDeepSeek,
    'volcengine': LLMBaseVolcEngine,
    'siliconflow': LLMBaseSiliconflow,
    'aliyun': LLMBaseAliyun,
    'zhipu': LLMBaseZhipu,
}

# 拉模型列表时需要改用其它端点的平台（key 仍取平台自己的）：
# - zhipu：zai.ZhipuAiClient 未暴露 models.list，走智谱官方 OpenAI 兼容 /v4 接口
# - siliconflow：chat 可用根路径，但 GET /models 只挂在 /v1 下（根路径 404）
_MODELS_CLIENT_OVERRIDES: Dict[str, Dict[str, str]] = {
    'zhipu': {'base_url': 'https://open.bigmodel.cn/api/paas/v4'},
    'siliconflow': {'base_url': 'https://api.siliconflow.cn/v1'},
}


def register_platform(platform: str, cls: type):
    """
    注册新的 LLM 平台实现（供外部扩展使用）
    :param platform: 平台标识
    :param cls: LLM 实现类（需继承 LLMBase）
    """
    _PLATFORM_REGISTRY[platform] = cls


def get_model_by_setting(_setting_name: str = 'stock_dcf_analysis', _setting: Optional[Dict[str, Any]] = None):
    """
    根据配置获取 LLM 实例
    :param _setting_name: 配置名称（场景名）。取值 = config.llm_model_setting 的默认值
        被 system_setting 表覆盖后的结果，见 llms.llm_setting.get_llm_model_settings()
    :param _setting: 直接传入配置字典（优先级高于 _setting_name）
    :return: LLM 实例（已设置好模型名称）
    """
    if _setting is None:
        _setting = get_llm_setting(_setting_name)

    if not _setting:
        raise ValueError(
            f"未找到 LLM 配置：{_setting_name}"
            f"（可用场景：{', '.join(s['name'] for s in LLM_SETTING_SCENES)}）"
        )

    platform = _setting.get('platform')
    if not platform:
        raise ValueError("LLM 配置缺少 'platform' 字段")

    llm_cls = _PLATFORM_REGISTRY.get(platform)
    if not llm_cls:
        supported = ', '.join(sorted(_PLATFORM_REGISTRY.keys()))
        raise ValueError(f"不支持的平台：{platform}，支持的平台：{supported}")

    staff = llm_cls()

    # 支持单模型（字符串）或多模型随机选择（列表）
    model = _setting.get('model')
    if isinstance(model, str):
        staff.set_model(model)
    elif isinstance(model, list) and model:
        staff.set_model(random.choice(model))
    else:
        raise ValueError(f"LLM 配置 'model' 字段无效：{model}")

    # ⚠️ 把场景名与平台写进实例，供 token 使用量统计（llms.usage_recorder）按
    # 「哪个场景 / 哪个平台」归集。scene 优先用 _setting 自己的 name（直接传 dict 时），
    # 否则回退到配置名 _setting_name。
    staff.scene = _setting.get('name') or _setting_name
    staff.platform = platform

    logger.debug(f"创建 LLM 实例：platform={platform}, model={staff.model}")
    return staff


def list_platform_models(platform: str, timeout: float = 15.0) -> List[str]:
    """
    实时拉取指定平台可用的模型列表（调用各平台 OpenAI 兼容的 GET /models）
    :param platform: 平台标识（_PLATFORM_REGISTRY 中的 key）
    :param timeout: 上游请求超时（秒）
    :return: 模型 ID 列表（去重、升序）
    :raises ValueError: 平台不支持
    :raises Exception: 上游接口失败（由调用方决定如何降级）
    """
    if platform not in _PLATFORM_REGISTRY:
        raise ValueError(f"不支持的平台：{platform}，支持的平台：{', '.join(sorted(_PLATFORM_REGISTRY))}")

    override = _MODELS_CLIENT_OVERRIDES.get(platform)
    if override:
        # 非 OpenAI SDK 客户端（如智谱 zai）：改用其 OpenAI 兼容端点 + 平台自己的 key
        staff = _PLATFORM_REGISTRY[platform]()
        api_key = getattr(staff.client, 'api_key', None) or zhipu_api
        client = OpenAI(api_key=api_key, base_url=override['base_url'])
    else:
        # 直接复用生产用的 OpenAI 兼容客户端（同 base_url、同 key，保证列表与实际可调用一致）
        client = _PLATFORM_REGISTRY[platform]().client

    resp = client.models.list(timeout=timeout)
    models = sorted({m.id for m in resp.data if getattr(m, 'id', None)})
    logger.debug(f"拉取平台模型列表成功：platform={platform}, count={len(models)}")
    return models
