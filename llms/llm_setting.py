"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 大模型路由配置：场景注册表 + 运行时解析。

 默认值仍然写在 config.llm_model_setting 里（代码级兜底），但可以被 system_setting 表里的
 行覆盖 —— 这样换模型不用改代码、不用重启。

 存储约定（每行一个场景）：
   setting_group = 'llm_model_setting'
   setting_key   = 'llm_model_setting.<场景名>'
   setting_value = {"platform": "...", "model": "..."}
 库里没有该行 → 用 config 里的默认值；删除该行 → 恢复默认值。
"""

from typing import Any, Dict, List, Optional

from config import llm_model_setting
from utils.logger import logger

# system_setting 表里的分组名（同时也是配置键前缀）
LLM_SETTING_GROUP = 'llm_model_setting'

# 场景注册表。name 必须与 config.llm_model_setting 的 key、以及各调用方传进
# get_model_by_setting('<name>') 的字符串完全一致；label / description 只用于设置页展示。
LLM_SETTING_SCENES: List[Dict[str, Any]] = [
    {
        'name': 'stock_dcf_analysis',
        'label': '个股深度研报',
        'description': '深度研报与 DCF 估值分析（job_deep_research、job_stock_dcf_model_analysis）',
        'in_use': True,
    },
    {
        'name': 'stock_dcf_analysis_extra',
        'label': '研报补充分析',
        'description': '深度研报的补充段落（job_stock_dcf_model_analysis）',
        'in_use': True,
    },
    {
        'name': 'stock_tech_analysis',
        'label': '技术分析',
        'description': '技术面解读（job_check_signal、大盘整体分析）',
        'in_use': True,
    },
    {
        'name': 'news_analysis',
        'label': '新闻分析',
        'description': '新闻情绪与关联标的抽取（job_news_feed_analysis）',
        'in_use': True,
    },
]

_SCENE_NAMES = [s['name'] for s in LLM_SETTING_SCENES]


def setting_key(scene: str) -> str:
    """场景名 → system_setting 表里的完整配置键。"""
    return f'{LLM_SETTING_GROUP}.{scene}'


def _normalize(value: Any) -> Optional[Dict[str, Any]]:
    """
    校验并归一化一条场景配置；返回 None 表示这行不可用（调用方沿用默认值）。

    model 既接受字符串（单模型），也接受非空列表（多候选，get_model_by_setting 会随机取一个）。
    设置页目前是单选下拉，写进去的就是字符串；列表形式保留给直接用 SQL 配置的场景。
    """
    if not isinstance(value, dict):
        return None

    platform = value.get('platform')
    if not isinstance(platform, str) or not platform.strip():
        return None
    platform = platform.strip()

    model = value.get('model')
    if isinstance(model, str):
        model = model.strip()
        if not model:
            return None
    elif isinstance(model, list):
        models = [m.strip() for m in model if isinstance(m, str) and m.strip()]
        if not models:
            return None
        model = models
    else:
        return None

    return {'platform': platform, 'model': model}


def get_default_settings() -> Dict[str, Dict[str, Any]]:
    """config.py 里的默认配置（浅拷贝一层，避免调用方改到模块级字典）。"""
    result: Dict[str, Dict[str, Any]] = {}
    for name, setting in (llm_model_setting or {}).items():
        if not isinstance(setting, dict):
            continue
        copied = dict(setting)
        if isinstance(copied.get('model'), list):
            copied['model'] = list(copied['model'])
        result[name] = copied
    return result


def _load_overrides() -> Dict[str, Any]:
    """
    从 system_setting 表读取覆盖配置，返回 {场景名: 原始值}。

    这里才做 service 的延迟导入：避免 llms 包与 service 包在模块加载期互相牵扯；
    同时把「表不存在 / 库不可用」这类问题收敛成一次告警 + 走默认值。
    """
    try:
        from service.system_setting_service import SystemSettingService
        return SystemSettingService.get_group_values(LLM_SETTING_GROUP) or {}
    except Exception as e:
        logger.warning(f"读取 system_setting[{LLM_SETTING_GROUP}] 失败，改用 config 默认值：{e}")
        return {}


def _merge(overrides: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """默认值 ← 表内覆盖，并丢弃格式非法的行（记一条告警，不让脏数据把调用打断）。"""
    result = get_default_settings()
    for name, value in (overrides or {}).items():
        normalized = _normalize(value)
        if normalized is None:
            logger.warning(
                f"system_setting 中的 {setting_key(name)} 格式非法，已忽略并沿用默认值：{value!r}"
            )
            continue
        result[name] = normalized
    return result


def get_llm_model_settings() -> Dict[str, Dict[str, Any]]:
    """
    最终生效的「场景 → {platform, model}」映射 = config 默认值 ← system_setting 覆盖。

    ⚠️ 不缓存，改完立即生效；取配置失败绝不上抛（配置表坏掉不该让 LLM 调用跟着挂）。
    """
    return _merge(_load_overrides())


def get_llm_setting(scene: str) -> Optional[Dict[str, Any]]:
    """取单个场景生效的配置，没有该场景返回 None。"""
    return get_llm_model_settings().get(scene)


def list_scenes() -> List[Dict[str, Any]]:
    """
    设置页用：每个场景的当前生效值、代码默认值、以及是否被表内配置覆盖。
    注册表之外的行（有人直接往表里插）也会列出来，避免「配了却在页面上看不到」。
    """
    overrides = _load_overrides()
    current = _merge(overrides)
    defaults = get_default_settings()

    scenes: List[Dict[str, Any]] = []
    for meta in LLM_SETTING_SCENES:
        name = meta['name']
        cur = current.get(name) or {}
        dft = defaults.get(name) or {}
        scenes.append({
            **meta,
            'platform': cur.get('platform'),
            'model': cur.get('model'),
            'default_platform': dft.get('platform'),
            'default_model': dft.get('model'),
            # 以「表里是否有这一行」判断，而不是「值是否与默认值相同」：
            # 用户显式把值设成和默认一样，也应当能看到「已自定义」并能一键恢复默认。
            'customized': name in overrides,
        })

    for name, value in overrides.items():
        if name in _SCENE_NAMES:
            continue
        cur = _normalize(value) or {}
        scenes.append({
            'name': name,
            'label': name,
            'description': '未在场景注册表中登记（可能由表内手工插入），当前没有代码会读取它',
            'in_use': False,
            'platform': cur.get('platform'),
            'model': cur.get('model'),
            'default_platform': None,
            'default_model': None,
            'customized': True,
        })
    return scenes
