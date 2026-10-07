"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.fastapi_app import api_prefix
from utils.auth import get_current_user
from databull import DataBullError
from service.us_index_service import UsIndexError, UsIndexService
from utils.data_loader import databull
from utils.logger import logger
from fastapi_cache.decorator import cache

# 全站登录制：整个 router 加登录鉴权（见 etf.py 顶部说明）。
index_router = APIRouter(prefix=api_prefix, tags=['指数'],
                         dependencies=[Depends(get_current_user)])

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


@index_router.get('/index/us_cards')
@cache(expire=1800)
def get_us_index_cards(
    bust: Optional[str] = Query(None, description='绕缓存用的透传参数，传任意变化值即可强制回源'),
):
    """获取美股大盘指数卡片（标普500 / 纳斯达克 / 道指等）。

    支撑「市场监控 → 美股大盘」页。返回**扁平列表**（不分组，与沪深页一致），
    每张带：最新收盘、当日涨跌、近 5 日、年初至今、近 60 日迷你走势。

    ⚠️ **没有实时数据**：上游美股指数只提供日线（`get_realtime(market='us')`
    实测 404），所以是「最近一个交易日的收盘」。缓存 30 分钟：日线数据收盘后
    不变，盘中重取也只是拿同一根 → 前端点「刷新」时传 `bust=<时间戳>` 强制回源。

    ⚠️ **`bust` 必须声明成形参才有效**（下面这个 `Query(None)` 不是装饰）：
    缓存 key 由 `default_key_builder` 生成 = md5(module:qualname:args:kwargs)，
    **只有声明过的 query 参数才会作为 kwargs 参与 key**。未声明的多余参数
    （如 `?_=123`）被 FastAPI 直接忽略 → key 不变 → 照样命中旧缓存。
    所以「加个时间戳参数绕缓存」这种写法**必须先把参数声明出来**。
    """
    try:
        return UsIndexService.get_cards()
    except UsIndexError as e:
        # 上游全挂才是真故障；单个指数失败已在service 内跳过并记入 meta.failed。
        logger.error(f'us index cards failed: {e}')
        raise HTTPException(status_code=502, detail=str(e))