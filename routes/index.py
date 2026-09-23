"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter
from app.fastapi_app import api_prefix
from databull import DataBullError
from utils.data_loader import databull
from utils.logger import logger
from fastapi_cache.decorator import cache

index_router = APIRouter(prefix=api_prefix, tags=['指数'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；写成 `async def`
# 会让下面循环里的同步 databull HTTP 调用直接占死事件循环 → 全站一起卡。


@index_router.get('/index/last_tick')
@cache(expire=3600)
def get_index_last():
    """
    获取指数最新行情
    """
    index_codes = ['000001', '399001', '399006', '000688', '000692']
    index_ticks = []
    for code in index_codes:
        try:
            res = databull.get_realtime(code, tick_type='index', market='cn')
        except DataBullError as e:
            # 新 SDK 失败即抛异常（旧本地客户端是 print 后返回 None）。原先 None 会在下面
            # 下标赋值时 TypeError，把整个接口打成 500、六张卡一起白；这里改为跳过该指数，
            # 保住其余卡片。
            logger.warning(f'index tick failed for {code}: {e}')
            continue
        if not isinstance(res, dict):
            continue
        res['index_code'] = code
        index_ticks.append(res)
    return index_ticks