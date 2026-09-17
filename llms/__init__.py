"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import random
from typing import Optional, Dict, Any

from config import llm_model_setting
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
    :param _setting_name: 配置名称（从 config.llm_model_setting 中查找）
    :param _setting: 直接传入配置字典（优先级高于 _setting_name）
    :return: LLM 实例（已设置好模型名称）
    """
    if _setting is None:
        _setting = llm_model_setting.get(_setting_name)

    if not _setting:
        raise ValueError(f"未找到 LLM 配置：{_setting_name}")

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

    logger.debug(f"创建 LLM 实例：platform={platform}, model={staff.model}")
    return staff
