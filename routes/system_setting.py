"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 系统设置接口。配置持久化在 system_setting 表（通用 KV，见 service/system_setting_service.py），
 当前开放两组：
   - 「大模型路由配置」llm_model_setting：每个业务场景一个平台 + 一个（或几个）模型；
   - 「图表显示配置」chart_display：详情页各图表区块的开关（目前是 K 线）。
"""

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from llms import _PLATFORM_REGISTRY, list_scenes as _list_llm_scenes, setting_key
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
#   chart_display.kline_enabled —— K 线（klinecharts 走势图）是否显示，**默认关闭**。
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
        'default': False,
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
