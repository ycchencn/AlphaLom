"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 系统设置接口。配置持久化在 system_setting 表（通用 KV，见 service/system_setting_service.py），
 当前开放的是「大模型路由配置」一组：每个业务场景一个平台 + 一个（或几个）模型。
"""

from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from llms import _PLATFORM_REGISTRY, list_scenes as _list_llm_scenes, setting_key
from service.system_setting_service import SystemSettingService
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
