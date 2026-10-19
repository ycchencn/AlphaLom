"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 大模型「平台凭据」配置：启用开关 + API Key + Base URL 的运行时解析。

 背景：原先各平台实现（llms/llm_base_*.py）在 __init__ 里直接读 `config.<x>_apikey`
 （来自 .env），换 key / 加平台都要改环境变量并重启。现在改成：
 **凭据只从 system_setting 表取**（后台设置页「下拉添加平台」时写入）。

 存储约定（每行的 setting_value 是一个对象）：
   setting_group = 'llm_platform_setting'
   setting_key   = 'llm_platform_setting.<平台标识>'
   setting_value = {"enabled": true, "api_key": "v1:...", "base_url": "https://..."}
     - api_key 是 utils.secret_box 加密后的密文，**永不回传明文**；
     - 三个字段都可缺省，缺省即沿用代码默认值（仅 base_url 有代码默认值）。

 「平台已添加」的判定（**不是**代码注册，而是库里有没有那一行）：
   - 表里有 `llm_platform_setting.<平台>` 这一行 = 该平台已被管理员添加，可用；
   - 表里没有 = **未添加**，视作不可用（enabled=False、api_key=None）。
   设置页的表格只列已添加的，候选清单（下拉「添加平台」）只列未添加的。
   接入新平台仍需在 `llms/` 下实现 LLMBase 子类并注册 —— 代码提供「能力」，
   数据库决定「是否启用」，两者缺一不可。

 ⚠️ 禁用（enabled=false）语义：路由到该平台时**明确报错**，不静默回退到别的平台 ——
 静默回退会让人以为改的模型生效了，实际跑的是另一个平台的另一个模型，排障极难。
"""

from typing import Any, Dict, List, Optional

from utils.logger import logger

# system_setting 表里的分组名（同时也是配置键前缀）
PLATFORM_SETTING_GROUP = 'llm_platform_setting'

# 平台静态元数据：展示名 + 文档链接 + 默认 base_url。
# 这是「代码侧能支持哪些平台」的唯一出处 —— 决定下拉里能添加哪些平台，
# 但**平台是否启用、key 是什么一律以数据库为准**（见 _resolve 的 added 语义）。
PLATFORM_META: Dict[str, Dict[str, str]] = {
    'deepseek': {
        'label': 'DeepSeek',
        'default_base_url': 'https://api.deepseek.com',
        'docs': 'https://api-docs.deepseek.com',
    },
    'volcengine': {
        'label': '火山方舟',
        'default_base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'docs': 'https://www.volcengine.com/docs/82379',
    },
    'siliconflow': {
        'label': '硅基流动',
        'default_base_url': 'https://api.siliconflow.cn',
        'docs': 'https://docs.siliconflow.cn',
    },
    'aliyun': {
        'label': '阿里云百炼',
        'default_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'docs': 'https://help.aliyun.com/zh/model-studio',
    },
    'zhipu': {
        'label': '智谱 AI',
        'default_base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'docs': 'https://docs.bigmodel.cn',
    },
    'tencent': {
        'label': '腾讯云混元',
        'default_base_url': 'https://api.hunyuan.cloud.tencent.com/v1',
        'docs': 'https://cloud.tencent.com/document/product/1729',
    },
    'baidu': {
        'label': '百度云千帆',
        'default_base_url': 'https://qianfan.baidubce.com/v2',
        'docs': 'https://cloud.baidu.com/doc/WENXINWORKSHOP',
    },
}


def platform_label(platform: str) -> str:
    """平台展示名；未登记的平台回退显示它的 key，不阻塞新平台接入。"""
    return (PLATFORM_META.get(platform) or {}).get('label') or platform


def _env_default_api_key(platform: str) -> Optional[str]:
    """
    ⚠️ 已废弃：不再从 .env 读平台 key。

    保留函数只为让历史调用点不炸，且**恒返回 None** —— 凭据只认数据库。
    新增平台请在「系统设置 → 大模型配置」里下拉添加并填写 API Key。
    """
    return None


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

    返回 {platform, label, enabled, api_key, base_url, added, customized}，其中：
      - added = 表里有没有该平台那一行。**没添加 = 不可用**（enabled=False、api_key=None）：
        凭据只认数据库，未添加就没有任何可用 key，与其「看起来 enabled 却调不通」不如明确不可用；
      - api_key 为 None 表示「已添加但没填 key」；
      - customized 与 added 同义（保留该字段名是为了设置页文案不用改口径）。
    """
    raw = overrides.get(platform)
    normalized = _normalize(raw, platform) if raw is not None else {}
    added = platform in overrides

    if not added:
        # 未添加：明确不可用。base_url 仍给代码默认值，仅供设置页「添加平台」时预填。
        return {
            'platform': platform,
            'label': platform_label(platform),
            'enabled': False,
            'api_key': None,
            'base_url': _default_base_url(platform),
            'added': False,
            'customized': False,
        }

    # enabled：表里有显式值就用它，缺省视为 True（刚添加即默认可用）
    enabled = normalized.get('enabled', True)

    # api_key：只认表里配的密文
    api_key: Optional[str] = None
    if normalized.get('api_key'):
        from utils.secret_box import decrypt
        api_key = decrypt(normalized['api_key'])
        if api_key is None:
            logger.warning(
                f'平台 {platform} 的 api_key 解密失败（主密钥换过或数据损坏），视为未配置'
            )

    base_url = normalized.get('base_url') or _default_base_url(platform)

    return {
        'platform': platform,
        'label': platform_label(platform),
        'enabled': bool(enabled),
        'api_key': api_key,
        'base_url': base_url,
        'added': True,
        'customized': True,
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
    单个平台生效配置。未登记的平台也返回一份「无线索」结构（added=False、
    enabled=False、api_key=None），由调用方判断 —— 便于外部 register_platform 扩展时不至于崩。
    """
    if platform not in PLATFORM_META:
        return {
            'platform': platform,
            'label': platform,
            'enabled': False,
            'api_key': None,
            'base_url': None,
            'added': False,
            'customized': False,
        }
    return _resolve(platform, _load_overrides())


def get_api_key(platform: str, required: bool = True) -> Optional[str]:
    """
    取平台明文 key（给各 LLMBase 实现调用）。
    :param required: True 时，未添加 / 被禁用 / 没填 key 都直接抛 ValueError
        （明确报错，不静默回退）；False 时返回 None 交调用方处理（如「列出模型」这类可降级场景）。
    """
    setting = get_platform_setting(platform)
    label = setting['label']
    if not setting.get('added'):
        if required:
            raise ValueError(
                f"大模型平台「{label}」尚未添加，"
                f"请先在「系统管理 → 系统设置 → 大模型配置」中通过「添加平台」下拉添加并填写 API Key。"
            )
        return None
    if not setting.get('enabled'):
        if required:
            raise ValueError(
                f"大模型平台「{label}」已在系统设置中被禁用，"
                f"请在「系统管理 → 大模型配置」中启用，或把使用它的场景换到其它平台。"
            )
        return None
    key = setting.get('api_key')
    if not key and required:
        raise ValueError(
            f"大模型平台「{label}」未配置 API Key，"
            f"请在「系统管理 → 大模型配置」中点击该平台的「设置 Key」填写。"
        )
    return key


def get_base_url(platform: str) -> Optional[str]:
    """取平台 base_url 的生效值（表里配了用表里的，否则代码默认）。"""
    return get_platform_setting(platform).get('base_url')


def _platform_view_row(platform: str, meta: Dict[str, str], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """单个平台的设置页视图行（key 只给掩码，绝不给明文）。"""
    from utils.secret_box import mask

    setting = _resolve(platform, overrides)
    plain = setting.get('api_key')
    stored = overrides.get(platform)
    has_stored_key = bool(isinstance(stored, dict) and stored.get('api_key'))
    return {
        'platform': platform,
        'label': meta['label'],
        'docs': meta.get('docs'),
        'enabled': setting['enabled'],
        'base_url': setting['base_url'],
        'default_base_url': meta.get('default_base_url'),
        # ⚠️ 恒为 'database' / None：凭据只认数据库，不再有 env 兜底。
        # 保留该字段是为了前端 Tag 的渲染分支不用改。
        'key_source': 'database' if has_stored_key else None,
        'api_key_masked': mask(plain) if plain else '',
        'has_api_key': bool(plain),
        'added': setting['added'],
        'customized': setting['customized'],
    }


def list_platforms_view() -> List[Dict[str, Any]]:
    """
    设置页表格视图：**只列已添加的平台**（表里有配置行的那些）。

    ⚠️ 语义已变：以前这里列的是全部代码注册平台。现在未添加的平台不出现在表格里 ——
    凭据只认数据库，一个没添加的平台在设置页占一行、却永远调不通，不如不显示。
    未添加的平台请用 `list_addable_platforms()`（下拉「添加平台」的数据源）。
    """
    overrides = _load_overrides()
    return [
        _platform_view_row(p, meta, overrides)
        for p, meta in PLATFORM_META.items()
        if p in overrides
    ]


def list_addable_platforms() -> List[Dict[str, Any]]:
    """
    下拉「添加平台」的候选：**已添加的排除在外**，避免重复添加同一平台。
    返回 {platform, label, docs, default_base_url}，不含任何凭据字段。
    """
    overrides = _load_overrides()
    return [
        {
            'platform': p,
            'label': meta['label'],
            'docs': meta.get('docs'),
            'default_base_url': meta.get('default_base_url'),
        }
        for p, meta in PLATFORM_META.items()
        if p not in overrides
    ]
