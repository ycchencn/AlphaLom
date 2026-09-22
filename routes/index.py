"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter
from app.fastapi_app import api_prefix
from utils.data_loader import databull
from utils.logger import logger
from fastapi_cache.decorator import cache

index_router = APIRouter(prefix=api_prefix, tags=['指数'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；写成 `async def`
# 会让下面循环里的同步 databull HTTP 调用直接占死事件循环 → 全站一起卡。

# 沪深大盘监控页顶部卡片固定的指数清单。前端 MarketOverview.vue 的 indices_name
# 映射必须与此保持一致 —— 曾经前端映射里有 000300、这里却漏了它，沪深300 卡片
# 永远拿不到数据（不是渲染空值，是整个卡不出现），排障时很隐蔽。
INDEX_CODES = ['000001', '399001', '399006', '000688', '000692', '000300']

# 指数 tick 是盘中盯盘数据，缓存放 1h 等于「打开页面看到的是上一小时的点位」。
# 这里与前端 MarketOverview 的自动刷新节奏对齐：前端 30s 轮询，后端 20s 缓存，
# 保证每次前端刷新都真的可能拿到新值，同时又不会被多标签页放大成上游压力。
INDEX_TICK_CACHE_SECONDS = 20


@index_router.get('/index/last_tick')
@cache(expire=INDEX_TICK_CACHE_SECONDS)
def get_index_last():
    """
    获取指数最新行情（沪深大盘监控页顶部卡片）

    返回数组，元素为上游 tick 原始字段 + 补写的 `index_code`。
    某个指数取不到数据（上游偶发返回 None / 空 dict）时**跳过该指数而不是整体失败**：
    原实现直接 `res['index_code'] = code`，一旦上游对某个指数返回 None 就 TypeError
    → 整个接口 500 → 六张卡片全部空白。ETF 侧早已对同一问题做了 `or {}` 兜底。
    """
    index_ticks = []
    for code in INDEX_CODES:
        res = databull.get_last_tick(code, tick_type='index', market='cn')
        if not res or not isinstance(res, dict):
            logger.warning(f"指数 {code} 最新行情为空，已跳过")
            continue
        res['index_code'] = code
        index_ticks.append(res)
    return index_ticks