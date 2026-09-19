"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Query
from fastapi_cache.decorator import cache

from llms import _PLATFORM_REGISTRY, list_platform_models
from app.fastapi_app import json_resp
from utils.logger import logger

llm_router = APIRouter(prefix='/api/v1', tags=['LLM'])

# 模型列表变化低频（上游新上/下线模型），缓存 30 分钟；带 platform 参数各自独立 key
_MODELS_CACHE_TTL = 1800
_MODELS_CACHE_NS = 'llm_models'


def _fetch_platform_models(platform: str) -> dict:
    """拉单个平台的模型列表，失败不抛出（返回 error 文本），保证批量模式部分可用"""
    try:
        return {'platform': platform, 'models': list_platform_models(platform), 'error': None}
    except Exception as e:
        logger.warning(f"拉取平台模型列表失败：platform={platform}, err={e}")
        return {'platform': platform, 'models': [], 'error': str(e)}


# 同步 `def` 路由（上游 HTTP 调用，同步 requests/openai SDK），由 Starlette 丢线程池执行，
# 见并发模型约定：默认写 def，不要写 async def。
@llm_router.get('/llm/models')
@cache(expire=_MODELS_CACHE_TTL, namespace=_MODELS_CACHE_NS)
def get_llm_models(platform: str = Query(default=None, description='平台标识，缺省则返回全部平台')):
    """
    实时调用各大模型平台 OpenAI 兼容的 GET /models 接口，返回可用模型列表。

    - 带 platform 参数：只拉该平台（前端切换「大模型平台」下拉时联动调用）
    - 不带 platform：并发拉取全部支持的平台，供一次性展示

    响应统一为 {platform: {platform, models: [...], error: str|null}}；error 非空表示
    该平台上游调用失败（key 缺失/接口异常），models 为空列表。结果缓存 30 分钟。
    """
    if platform:
        platform = platform.strip()
        if platform not in _PLATFORM_REGISTRY:
            return json_resp({
                platform: {'platform': platform, 'models': [],
                           'error': f"不支持的平台，支持：{', '.join(sorted(_PLATFORM_REGISTRY))}"}
            })
        return json_resp({platform: _fetch_platform_models(platform)})

    # 并发拉全部平台，任一平台失败不影响其它平台
    result = {}
    with ThreadPoolExecutor(max_workers=len(_PLATFORM_REGISTRY)) as pool:
        futures = {pool.submit(_fetch_platform_models, p): p for p in _PLATFORM_REGISTRY}
        for fut in as_completed(futures):
            r = fut.result()
            result[r['platform']] = r
    return json_resp(result)
