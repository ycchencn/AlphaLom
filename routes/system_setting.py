"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 系统设置接口。配置持久化在 system_setting 表（通用 KV，见 service/system_setting_service.py），
 当前开放三组：
   - 「大模型路由配置」llm_model_setting：每个业务场景一个平台 + 一个（或几个）模型；
   - 「大模型平台配置」llm_platform_setting：各平台的启用开关 / API Key（加密存储）/ Base URL；
   - 「图表显示配置」chart_display：详情页各图表区块的开关（目前是 K 线）。
"""

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from llms import (_PLATFORM_REGISTRY, list_platform_models,
                  list_scenes as _list_llm_scenes, setting_key)
from llms.llm_platform import (PLATFORM_META, get_platform_setting, list_platforms_view,
                               platform_label)
from service.system_setting_service import SystemSettingService
from utils.auth import require_admin
from utils.logger import logger

settings_router = APIRouter(prefix=f'{api_prefix}/settings', tags=['系统设置'])

# 同步 `def` 路由：由 Starlette 丢进 anyio 线程池执行（读写库是阻塞调用），
# 不要写成 async def —— 那会占死唯一事件循环、拖垮全站并发。

# 平台展示名。没有登记的平台直接回退显示它的 key，不阻塞新平台接入。
_PLATFORM_LABELS = {
    'deepseek': 'DeepSeek',
    'volcengine': '火山方舟',
    'siliconflow': '硅基流动',
    'aliyun': '阿里云百炼',
    'zhipu': '智谱 AI',
}


def _platform_options() -> List[dict]:
    """平台下拉选项，value 即 _PLATFORM_REGISTRY 的 key（前端原样回传）。"""
    return [
        {'label': _PLATFORM_LABELS.get(p, p), 'value': p}
        for p in sorted(_PLATFORM_REGISTRY)
    ]


def _scene_view(scene: str) -> Optional[dict]:
    """取单个场景的当前视图（含生效值与默认值），场景未登记返回 None。"""
    for item in _list_llm_scenes():
        if item.get('name') == scene:
            return item
    return None


class LlmSceneSettingRequest(BaseModel):
    """大模型场景配置入参。

    model 允许字符串（单模型，设置页下拉写入的就是它）或非空字符串列表
    （多候选，get_model_by_setting 会随机取一个 —— config 里 news_analysis 的默认值就是列表）。
    """
    platform: str
    model: Union[str, List[str]]


@settings_router.get('/llm_models')
def get_llm_models_setting():
    """
    读取大模型路由配置：可选平台 + 各业务场景当前生效的平台与模型。

    每个场景同时返回代码里的默认值（default_platform / default_model）与是否已被表内配置覆盖
    （customized），前端据此显示「已自定义」并能一键恢复默认。

    不挂 @cache：设置页改完必须立刻看到新值。
    """
    return {
        'platforms': _platform_options(),
        'scenes': _list_llm_scenes(),
    }


@settings_router.put('/llm_models/{scene}')
def update_llm_models_setting(scene: str, req: LlmSceneSettingRequest):
    """
    写入某个场景的模型配置（存在则更新）。写完立即生效，无需重启。

    - scene 必须是已登记的场景（拼错的场景名写进去也不会有任何代码读它，故直接拒绝）；
    - platform 必须是 llms 已注册的平台；
    - model 不能为空。
    """
    scene = (scene or '').strip()
    if _scene_view(scene) is None:
        valid = ', '.join(s['name'] for s in _list_llm_scenes())
        raise HTTPException(status_code=400, detail=f'未知的场景：{scene}，可用场景：{valid}')

    platform = (req.platform or '').strip()
    if platform not in _PLATFORM_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台：{platform}，支持：{', '.join(sorted(_PLATFORM_REGISTRY))}",
        )

    if isinstance(req.model, str):
        model = req.model.strip()
        if not model:
            raise HTTPException(status_code=400, detail='模型名称不能为空')
    else:
        model = [m.strip() for m in (req.model or []) if isinstance(m, str) and m.strip()]
        if not model:
            raise HTTPException(status_code=400, detail='模型名称列表不能为空')

    try:
        SystemSettingService.upsert(
            key=setting_key(scene),
            value={'platform': platform, 'model': model},
            value_type='json',
            description=f'大模型路由配置（场景 {scene}）',
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f'保存大模型配置失败 scene={scene}: {e}')
        raise HTTPException(status_code=500, detail=f'保存失败：{e}')

    return {'code': 0, 'message': 'ok', 'data': _scene_view(scene)}


@settings_router.delete('/llm_models/{scene}')
def reset_llm_models_setting(scene: str):
    """
    删除某个场景的表内配置 = 恢复代码默认值（config.llm_model_setting）。

    幂等：本来就没有配置行时也返回成功，只是 deleted=False。
    """
    scene = (scene or '').strip()
    if _scene_view(scene) is None:
        valid = ', '.join(s['name'] for s in _list_llm_scenes())
        raise HTTPException(status_code=400, detail=f'未知的场景：{scene}，可用场景：{valid}')

    deleted = SystemSettingService.delete(setting_key(scene))
    return {'code': 0, 'message': 'ok', 'deleted': deleted, 'data': _scene_view(scene)}


# ==========================================================================
# 图表显示配置（chart_display）
#
# 详情页（个股 / ETF）的图表区块开关，目前只一项：
#   chart_display.kline_enabled —— K 线（klinecharts 走势图）是否显示，**默认开启**。
#
# 设计取舍：
# - **默认值写在代码里**（下面 _CHART_DISPLAY_DEFAULTS），表里没有行 = 用默认值。
#   所以「恢复默认」= 删行（见 SystemSettingService 的约定），不是写一行默认值回去。
# - 读接口**不加管理员门禁**：详情页是普通用户页面，每个用户都要读它决定渲不渲染；
#   写接口必须管理员 —— 改的是全站行为。
# - 不挂 @cache：设置页改完必须立刻生效（详情页每次进页面读一次，开销可忽略）。
# ==========================================================================

CHART_DISPLAY_GROUP = 'chart_display'

# 配置项定义：{名称: (默认值, 说明, 展示名)}
# 前端据此渲染表单，加新项只需往这里补一行 + 前端按 key 渲染。
_CHART_DISPLAY_SPEC: Dict[str, Dict[str, Any]] = {
    'kline_enabled': {
        'default': True,
        'label': '显示 K 线图',
        'description': '个股 / ETF 详情页的「走势图表」区块。关闭后该区块整块隐藏。',
        'value_type': 'bool',
    },
}


def _chart_display_key(name: str) -> str:
    return f'{CHART_DISPLAY_GROUP}.{name}'


def _chart_display_view() -> Dict[str, Any]:
    """当前生效值 + 默认值 + 是否被表内配置覆盖，供设置页与详情页共用。

    整组走一次查询（get_group_values），避免逐项查库。
    """
    stored = SystemSettingService.get_group_values(CHART_DISPLAY_GROUP)
    items = []
    values: Dict[str, Any] = {}
    for name, spec in _CHART_DISPLAY_SPEC.items():
        customized = name in stored
        # 表里存的是 JSON，布尔可能以 True/'true' 等形式出现 → 统一归一成 bool
        raw = stored.get(name) if customized else spec['default']
        value = _as_bool(raw, spec['default'])
        values[name] = value
        items.append({
            'name': name,
            'label': spec['label'],
            'description': spec['description'],
            'value_type': spec['value_type'],
            'value': value,
            'default': spec['default'],
            'customized': customized,
        })
    return {'values': values, 'items': items}


def _as_bool(value: Any, default: bool) -> bool:
    """把 JSON 里可能出现的 True/'true'/1/'1' 等统一成 bool；无法识别则回默认值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ('true', '1', 'yes', 'on'):
            return True
        if low in ('false', '0', 'no', 'off'):
            return False
    return default


@settings_router.get('/chart_display')
def get_chart_display_setting():
    """读取图表显示配置（**无需管理员**：详情页普通用户也要据此决定渲染）。"""
    view = _chart_display_view()
    return {'code': 0, 'data': view, **view}


class ChartDisplayUpdateRequest(BaseModel):
    """单项配置写入入参。布尔开关固定用 value。"""
    value: Union[bool, str, int]


@settings_router.put('/chart_display/{name}')
def update_chart_display_setting(
        name: str,
        req: ChartDisplayUpdateRequest,
        _admin: dict = Depends(require_admin),
):
    """写入某一项图表显示配置（存在则更新）。改完立即生效，无需重启/发版。"""
    name = (name or '').strip()
    if name not in _CHART_DISPLAY_SPEC:
        valid = ', '.join(_CHART_DISPLAY_SPEC)
        raise HTTPException(status_code=400, detail=f'未知的配置项：{name}，可用项：{valid}')

    spec = _CHART_DISPLAY_SPEC[name]
    value = _as_bool(req.value, spec['default'])

    try:
        SystemSettingService.upsert(
            key=_chart_display_key(name),
            value=value,
            group=CHART_DISPLAY_GROUP,
            value_type=spec['value_type'],
            description=spec['description'],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f'保存图表显示配置失败 name={name}: {e}')
        raise HTTPException(status_code=500, detail=f'保存失败：{e}')

    return {'code': 0, 'message': 'ok', 'data': _chart_display_view()}


@settings_router.delete('/chart_display/{name}')
def reset_chart_display_setting(
        name: str,
        _admin: dict = Depends(require_admin),
):
    """删除某一项配置 = 恢复代码默认值。幂等：本来没有行也返回成功（deleted=False）。"""
    name = (name or '').strip()
    if name not in _CHART_DISPLAY_SPEC:
        valid = ', '.join(_CHART_DISPLAY_SPEC)
        raise HTTPException(status_code=400, detail=f'未知的配置项：{name}，可用项：{valid}')

    deleted = SystemSettingService.delete(_chart_display_key(name))
    return {'code': 0, 'message': 'ok', 'deleted': deleted, 'data': _chart_display_view()}


# ==========================================================================
# 大模型平台配置（llm_platform_setting）
#
# 平台级的「启用开关 + API Key + Base URL」。原先这些只在 .env 里配（config.<x>_apikey），
# 改一次要重启服务；现在迁到后台设置页管理。
#
# 存储（每平台一行，setting_value 是对象）：
#   llm_platform_setting.<平台> = {"enabled": bool, "api_key": "v1:<密文>", "base_url": str}
# - api_key **加密存储**（utils/secret_box，主密钥在 env: ALPHALOM_SECRET_KEY），
#   读接口只回掩码，永不回传明文；
# - 三个字段都可缺省 → 缺省即沿用 env / 代码默认值；
# - **删行 = 该平台完全回到 env 默认值**（与 chart_display 的「恢复默认」语义一致）；
# - 平台被禁用时，路由到它的场景会**明确报错**（llms.llm_platform.get_api_key），
#   不静默回退到别的平台。
#
# 读接口需要管理员门禁：返回体里虽然只有掩码，但列表本身暴露了「哪些平台配了 key」，
# 且这是纯后台页面。写接口同样要求管理员。
# ==========================================================================

LLM_PLATFORM_GROUP = 'llm_platform_setting'


def _platform_setting_key(platform: str) -> str:
    return f'{LLM_PLATFORM_GROUP}.{platform}'


def _get_stored_platform_row(platform: str) -> Optional[dict]:
    """取表里该平台那一行的原始 dict（不存在返回 None）。"""
    raw = SystemSettingService.get_value(_platform_setting_key(platform), default=None)
    return raw if isinstance(raw, dict) else None


def _platform_view() -> Dict[str, Any]:
    """整组视图：平台列表（key 掩码） + 密钥是否已配置（前端据此提示）。"""
    from utils.secret_box import is_configured as _secret_configured
    return {
        'platforms': list_platforms_view(),
        'secret_key_configured': _secret_configured(),
        'secret_key_env': 'ALPHALOM_SECRET_KEY',
    }


@settings_router.get('/llm_platforms')
def get_llm_platforms_setting(_admin: dict = Depends(require_admin)):
    """
    读取大模型平台配置（仅管理员）。

    每个平台返回：启用状态、生效 base_url、key 掩码与来源（database / env / 无）、
    代码默认 base_url、env 里对应的变量名。**不返回任何明文 key**。

    ⚠️ 平台清单来自代码里的 PLATFORM_META（5 个已注册平台），**不是数据库记录** ——
    页面上的「启用/关闭、key、base_url」是**改**已有平台，没有「新增平台」这回事
    （新增平台要在 `llms/` 里写一个 LLMBase 子类并注册，属于代码改动）。
    这里额外兜一层兜底：万一解析层返回空（数据源异常），回退成最少标签列表，
    避免前端显示「共 0 个平台」这种毫无线索的空态。
    """
    import os
    rows = list_platforms_view()
    if not rows:
        # 兜底：至少把已注册的平台按 key 列出来，并标注没有可用 key 来源
        logger.warning('list_platforms_view() 返回空，回退为最小平台清单（检查 PLATFORM_META 是否可导入）')
        rows = [{
            'platform': p,
            'label': _PLATFORM_LABELS.get(p, p),
            'docs': None,
            'enabled': True,
            'base_url': None,
            'default_base_url': None,
            'env_key_name': (PLATFORM_META.get(p) or {}).get('env_key'),
            'has_env_key': bool((os.getenv((PLATFORM_META.get(p) or {}).get('env_key') or '')) if (PLATFORM_META.get(p) or {}).get('env_key') else False),
            'api_key_masked': '',
            'has_api_key': False,
            'key_source': None,
            'customized': False,
        } for p in sorted(_PLATFORM_REGISTRY)]

    from utils.secret_box import is_configured as _secret_configured
    view = {
        'platforms': rows,
        'secret_key_configured': _secret_configured(),
        'secret_key_env': 'ALPHALOM_SECRET_KEY',
        # 前端据此说明「平台清单是代码注册的，不可增删」
        'platforms_are_code_defined': True,
    }
    return {'code': 0, 'data': view, **view}


class LlmPlatformSettingRequest(BaseModel):
    """
    平台配置写入入参（三项都可选，只传要改的）：

    - enabled：启用/禁用开关；
    - api_key：**明文** key。传空串或 null 表示「不改动现有 key」（前端掩码回显时不会
      回传明文，所以不能把「没传」当成「清空」）；
    - base_url：留空则回落代码默认地址。
    """
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@settings_router.put('/llm_platforms/{platform}')
def update_llm_platform_setting(
        platform: str,
        req: LlmPlatformSettingRequest,
        _admin: dict = Depends(require_admin),
):
    """
    写入某个平台的配置（存在则更新；未传的字段沿用当前值）。改完立即生效，无需重启。

    校验：
    - platform 必须是 llms 已登记的平台；
    - base_url 非空时必须是 http(s) 开头（防手滑写成裸域名导致 SDK 报难以定位的错）；
    - api_key 非空时才覆盖，并在覆盖前做一次加密（密钥未配置则 400，不静默存明文）。
    """
    platform = (platform or '').strip()
    if platform not in PLATFORM_META:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台：{platform}，支持：{', '.join(sorted(PLATFORM_META))}",
        )

    # 以当前生效值 + 表内原始行为基础合并（表里没有行时 stored 为 None）
    stored = _get_stored_platform_row(platform) or {}
    merged: Dict[str, Any] = {
        'enabled': stored.get('enabled', True) if isinstance(stored.get('enabled'), bool)
        else bool(get_platform_setting(platform).get('enabled', True)),
        'api_key': stored.get('api_key'),
        'base_url': stored.get('base_url'),
    }

    if req.enabled is not None:
        merged['enabled'] = bool(req.enabled)

    if req.base_url is not None:
        base_url = (req.base_url or '').strip()
        if not base_url:
            merged['base_url'] = None            # 留空 = 回落代码默认地址
        elif not base_url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail='base_url 必须以 http:// 或 https:// 开头')
        else:
            merged['base_url'] = base_url.rstrip('/')

    # ---- key：只在显式传了非空明文时覆盖 ----
    new_key = (req.api_key or '').strip()
    if new_key:
        from utils.secret_box import encrypt, is_configured as _secret_configured
        if not _secret_configured():
            raise HTTPException(
                status_code=400,
                detail=f'未配置加解密主密钥（ALPHALOM_SECRET_KEY），无法安全保存 API Key。'
                       f'请在 .env 中设置一段随机口令并重启服务。',
            )
        try:
            merged['api_key'] = encrypt(new_key)
        except Exception as e:
            logger.error(f'加密平台 key 失败 platform={platform}: {e}')
            raise HTTPException(status_code=500, detail='API Key 加密失败，请检查 SECRET_KEY 配置')

    # 若三项都为空且表里本来没行，就不必建行（避免「建了行但内容等同默认」）
    if not merged.get('api_key') and not merged.get('base_url') and merged.get('enabled') is True \
            and stored == {}:
        return {'code': 0, 'message': 'ok', 'data': _platform_view()}

    try:
        SystemSettingService.upsert(
            key=_platform_setting_key(platform),
            value=merged,
            group=LLM_PLATFORM_GROUP,
            value_type='json',
            description=f'大模型平台配置（{platform_label(platform)}）：启用开关 / API Key / Base URL',
            updated_by=_admin.get('username'),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f'保存平台配置失败 platform={platform}: {e}')
        raise HTTPException(status_code=500, detail=f'保存失败：{e}')

    return {'code': 0, 'message': 'ok', 'data': _platform_view()}


@settings_router.delete('/llm_platforms/{platform}')
def reset_llm_platform_setting(
        platform: str,
        _admin: dict = Depends(require_admin),
):
    """
    删除某个平台的表内配置 = 完全恢复 env / 代码默认值（key、base_url、启用状态一起回退）。

    幂等：本来就没有配置行时也返回成功，只是 deleted=False。
    """
    platform = (platform or '').strip()
    if platform not in PLATFORM_META:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台：{platform}，支持：{', '.join(sorted(PLATFORM_META))}",
        )

    deleted = SystemSettingService.delete(_platform_setting_key(platform))
    return {'code': 0, 'message': 'ok', 'deleted': deleted, 'data': _platform_view()}


@settings_router.post('/llm_platforms/{platform}/test')
def test_llm_platform_setting(
        platform: str,
        _admin: dict = Depends(require_admin),
):
    """
    连通性自测：用当前生效配置调一次上游 GET /models，确认 key / base_url 可用。

    失败也返回 200（把错误放进 body），前端好统一展示 —— 这不是「接口本身出错」，
    而是「被测对象不可用」。异常在服务端已收敛成文本，不会把 traceback 暴露给前端。
    """
    platform = (platform or '').strip()
    if platform not in PLATFORM_META:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台：{platform}，支持：{', '.join(sorted(PLATFORM_META))}",
        )
    try:
        models = list_platform_models(platform)
        return {'code': 0, 'ok': True, 'platform': platform,
                'message': f'连接成功，可用模型 {len(models)} 个', 'models_count': len(models)}
    except Exception as e:
        return {'code': 0, 'ok': False, 'platform': platform, 'message': f'连接失败：{e}',
                'models_count': 0}
