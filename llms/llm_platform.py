"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 大模型「平台凭据」配置：启用开关 + API Key + Base URL 的运行时解析。

 背景：原先各平台实现（llms/llm_base_*.py）在 __init__ 里直接读 `config.<x>_apikey`
 （来自 .env），换 key / 加平台都要改环境变量并重启。现在改成：

   env / config 默认值  ←  system_setting 表覆盖（后台设置页可改，立即生效）

 存储约定（每行的 setting_value 是一个对象）：
   setting_group = 'llm_platform_setting'
   setting_key   = 'llm_platform_setting.<平台标识>'
   setting_value = {"enabled": true, "api_key": "v1:...", "base_url": "https://..."}
     - api_key 是 utils.secret_box 加密后的密文，**永不回传明文**；
     - 三个字段都可缺省，缺省即沿用 env 默认值；
     - **库里没有该行 = 该平台完全用 env 默认值**（含「没配 key 也能跑」的历史状态）。
       注意这与 chart_display 的「删行 = 恢复默认」语义一致。

 ⚠️ 禁用（enabled=false）语义：路由到该平台时**明确报错**，不静默回退到别的平台 ——
 静默回退会让人以为改的模型生效了，实际跑的是另一个平台的另一个模型，排障极难。
"""

from typing import Any, Dict, List, Optional

from utils.logger import logger

# system_setting 表里的分组名（同时也是配置键前缀）
PLATFORM_SETTING_GROUP = 'llm_platform_setting'

# 平台静态元数据：展示名 + env 里的默认凭据变量名 + 默认 base_url。
# 这是「平台的代码默认值」的唯一出处（env 只覆盖 key，不覆盖 base_url）。
PLATFORM_META: Dict[str, Dict[str, str]] = {
    'deepseek': {
        'label': 'DeepSeek',
        'env_key': 'DEEPSEEK_APIKEY',
        'default_base_url': 'https://api.deepseek.com',
        'docs': 'https://api-docs.deepseek.com',
    },
    'volcengine': {
        'label': '火山方舟',
        'env_key': 'DOUBAO_APIKEY',
        'default_base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'docs': 'https://www.volcengine.com/docs/82379',
    },
    'siliconflow': {
        'label': '硅基流动',
        'env_key': 'SILICONFLOW_APIKEY',
        'default_base_url': 'https://api.siliconflow.cn',
        'docs': 'https://docs.siliconflow.cn',
    },
    'aliyun': {
        'label': '阿里云百炼',
        'env_key': 'ALIYUN_BAILIAN_APIKEY',
        'default_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'docs': 'https://help.aliyun.com/zh/model-studio',
    },
    'zhipu': {
        'label': '智谱 AI',
        'env_key': 'ZHIPU_APIKEY',
        'default_base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'docs': 'https://docs.bigmodel.cn',
    },
}


def platform_label(platform: str) -> str:
    """平台展示名；未登记的平台回退显示它的 key，不阻塞新平台接入。"""
    return (PLATFORM_META.get(platform) or {}).get('label') or platform


def _env_default_api_key(platform: str) -> Optional[str]:
    """env 里的默认 key（仅作兜底；库里配了就以库里为准）。"""
    import os
    env_name = (PLATFORM_META.get(platform) or {}).get('env_key')
    if not env_name:
        return None
    return (os.getenv(env_name) or '').strip() or None


def _default_base_url(platform: str) -> Optional[str]:
    return (PLATFORM_META.get(platform) or {}).get('default_base_url')


def _load_overrides() -> Dict[str, Any]:
    """
    从 system_setting 表读取平台配置覆盖，返回 {平台标识: 原始 dict}。

    延迟导入 service：避免 llms 包与 service 包在模块加载期互相牵扯；
    读失败一律走 env 默认值（配置表坏了不该让 LLM 调用跟着挂）。
    """
    try:
        from service.system_setting_service import SystemSettingService
        return SystemSettingService.get_group_values(PLATFORM_SETTING_GROUP) or {}
    except Exception as e:
        logger.warning(f'读取 system_setting[{PLATFORM_SETTING_GROUP}] 失败，改用 env 默认值：{e}')
        return {}


def _normalize(value: Any, platform: str) -> Dict[str, Any]:
    """
    把表里一行归一化成 {enabled, api_key, base_url}；无法识别的字段忽略。

    - enabled 缺省视为 True（老行为：只要 env 有 key 就能用）；
    - api_key 允许是已加密密文；解密交给 secret_box，这里只搬值。
    """
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}

    enabled = value.get('enabled')
    if isinstance(enabled, bool):
        out['enabled'] = enabled
    elif isinstance(enabled, str) and enabled.strip().lower() in ('true', 'false'):
        out['enabled'] = enabled.strip().lower() == 'true'
    elif isinstance(enabled, (int, float)):
        out['enabled'] = bool(enabled)

    api_key = value.get('api_key')
    if isinstance(api_key, str) and api_key.strip():
        out['api_key'] = api_key.strip()

    base_url = value.get('base_url')
    if isinstance(base_url, str) and base_url.strip():
        out['base_url'] = base_url.strip()

    return out


def _resolve(platform: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    单个平台的生效配置（key 已解密为明文；解密失败则为 None）。

    返回 {platform, label, enabled, api_key, base_url, customized}，其中：
      - api_key 为 None 表示「没有任何可用 key」；
      - customized 表示表里是否有该行（设置页据此显示「已自定义」）。
    """
    raw = overrides.get(platform)
    normalized = _normalize(raw, platform) if raw is not None else {}
    customized = platform in overrides

    # enabled：表里有显式值就用它，否则默认 True
    enabled = normalized.get('enabled', True)

    # api_key：表里配了（密文）优先；否则取 env 默认值
    api_key: Optional[str] = None
    if normalized.get('api_key'):
        from utils.secret_box import decrypt
        api_key = decrypt(normalized['api_key'])
        if api_key is None:
            logger.warning(
                f'平台 {platform} 的 api_key 解密失败（主密钥换过或数据损坏），视为未配置'
            )
    if not api_key:
        api_key = _env_default_api_key(platform)

    base_url = normalized.get('base_url') or _default_base_url(platform)

    return {
        'platform': platform,
        'label': platform_label(platform),
        'enabled': bool(enabled),
        'api_key': api_key,
        'base_url': base_url,
        'customized': customized,
    }


def get_platform_settings() -> Dict[str, Dict[str, Any]]:
    """
    全部平台的生效配置（key 已解密）。⚠️ 不缓存，改完立即生效。
    返回值含明文 key，**只允许内部调用方使用，不要直接塞进 HTTP 响应**。
    """
    overrides = _load_overrides()
    return {p: _resolve(p, overrides) for p in PLATFORM_META}


def get_platform_setting(platform: str) -> Dict[str, Any]:
    """
    单个平台生效配置。未登记的平台也返回一份「无线索」结构（enabled=True、
    api_key=None），由调用方判断 —— 便于外部 register_platform 扩展时不至于崩。
    """
    if platform not in PLATFORM_META:
        return {
            'platform': platform,
            'label': platform,
            'enabled': True,
            'api_key': None,
            'base_url': None,
            'customized': False,
        }
    return _resolve(platform, _load_overrides())


def get_api_key(platform: str, required: bool = True) -> Optional[str]:
    """
    取平台明文 key（给各 LLMBase 实现调用）。
    :param required: True 时，平台被禁用 / 没配 key 直接抛 ValueError（明确报错，
        不静默回退）；False 时返回 None 交调用方处理（如「列出模型」这类可降级场景）。
    """
    setting = get_platform_setting(platform)
    if not setting.get('enabled'):
        if required:
            raise ValueError(
                f"大模型平台「{setting['label']}」已在系统设置中被禁用，"
                f"请在「系统管理 → 大模型配置 → 平台管理」中启用，或把使用它的场景换到其它平台。"
            )
        return None
    key = setting.get('api_key')
    if not key and required:
        raise ValueError(
            f"大模型平台「{setting['label']}」未配置 API Key，"
            f"请在「系统管理 → 大模型配置 → 平台管理」中填写，或在 .env 中设置 "
            f"{(PLATFORM_META.get(platform) or {}).get('env_key', '对应变量')}。"
        )
    return key


def get_base_url(platform: str) -> Optional[str]:
    """取平台 base_url 的生效值（表里配了用表里的，否则代码默认）。"""
    return get_platform_setting(platform).get('base_url')


def list_platforms_view() -> List[Dict[str, Any]]:
    """
    设置页视图：每个平台一行，**key 只回掩码，绝不回明文**。

    额外返回 has_env_key：env 里是否已有兜底 key（前端提示「未配置，将使用 .env 中的 key」）。
    """
    from utils.secret_box import mask

    overrides = _load_overrides()
    result: List[Dict[str, Any]] = []
    for platform, meta in PLATFORM_META.items():
        setting = _resolve(platform, overrides)
        env_key = _env_default_api_key(platform)
        plain = setting.get('api_key')
        # 来源：表里覆盖的密文 / env 兜底 / 都没有
        if overrides.get(platform, {}).get('api_key') if isinstance(overrides.get(platform), dict) else False:
            source = 'database'
        elif env_key:
            source = 'env'
        else:
            source = None
        result.append({
            'platform': platform,
            'label': meta['label'],
            'docs': meta.get('docs'),
            'enabled': setting['enabled'],
            'base_url': setting['base_url'],
            'default_base_url': meta.get('default_base_url'),
            'env_key_name': meta.get('env_key'),
            'has_env_key': bool(env_key),
            'api_key_masked': mask(plain) if plain else '',
            'has_api_key': bool(plain),
            'key_source': source,
            'customized': setting['customized'],
        })
    return result
