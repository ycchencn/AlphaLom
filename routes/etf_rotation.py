"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ETF 轮动接口：轮动池管理 + 轮动分析。

与 routes/etf.py 的关系：共用 `api_prefix` 与 `tags=['ETF']`（Swagger 里同一个分组），
但单独成模块 —— 轮动这条链路（池 + 现算信号 + 回测）和 ETF 行情/详情是两件事，
塞进 etf.py 只会让那个文件继续膨胀。

⚠️ 缓存的两条约定（与 routes/etf.py 一致，踩过坑）：
  1. `user_id` 一律用 `Depends(get_current_user_id)` 注入 —— FastAPI 会把它作为 kwargs
     传给 endpoint，从而自动进入 fastapi_cache 的缓存键，用户维度天然隔离，
     前端也无法通过传参看别人的轮动池；
  2. 增删池成员后必须 `await FastAPICache.clear()` 清**两个**命名空间：
     池列表缓存 + **分析结果缓存**（分析结果依赖池成员，不清的话加完标的结果还是旧的，
     表现就是「加了 ETF 但排名里没有」，极容易被误判成冷启动 bug）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from config import cache_setting
from service.etf_rotation_service import (
    COST_RANGE,
    LOOKBACK_RANGE,
    POOL_LIMIT,
    REBALANCE_RANGE,
    WINDOW_RANGE,
    EtfRotationError,
    EtfRotationService,
)
from utils.auth import get_current_user_id
from utils.logger import logger

etf_rotation_router = APIRouter(prefix=api_prefix, tags=['ETF'])

# 装饰器与「增删后失效」两处共用同一常量，避免字符串写得不一致导致失效静默落空。
ROTATION_POOL_NS = 'etf_rotation_pool'
ROTATION_NS = 'etf_rotation'


class RotationPoolAddRequest(BaseModel):
    symbol: str
    name: Optional[str] = None


@etf_rotation_router.get('/etf_rotation_pool')
@cache(expire=cache_setting['etf_rotation_pool'], namespace=ROTATION_POOL_NS)
def get_rotation_pool(user_id: int = Depends(get_current_user_id)):
    """当前用户的轮动池成员（按加入时间倒序）。

    返回对象而不是裸数组：前端要显示「已选 5 / 最多 30」的容量提示，
    把上限一起给出去，避免前端再写死一份（两处各写一份必然漂移）。
    """
    rows = EtfRotationService.list_pool(user_id)
    return {
        'items': [row.to_dict() for row in rows],
        'total': len(rows),
        'limit': POOL_LIMIT,
    }


@etf_rotation_router.post('/etf_rotation_pool')
async def add_rotation_pool(req: RotationPoolAddRequest, user_id: int = Depends(get_current_user_id)):
    """把一只 ETF 加入当前用户的轮动池。

    用 `async def` 是为了 `await FastAPICache.clear()`（同步 `def` 由 Starlette 丢线程池
    执行，里面没有事件循环，await 不了）；库操作本身是同步阻塞的（DB + 取名称可能请求
    databull），所以显式走 run_in_threadpool，别占死唯一的事件循环 —— 与 routes/etf.py
    的 add_etf 完全一致。
    """
    try:
        item = await run_in_threadpool(EtfRotationService.add_to_pool, user_id, req.symbol,
                                       name=req.name)
    except EtfRotationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await _clear_rotation_cache()
    return {'code': 0, 'message': 'ok', 'data': item.to_dict()}


@etf_rotation_router.delete('/etf_rotation_pool/{symbol}')
async def delete_rotation_pool(symbol: str, user_id: int = Depends(get_current_user_id)):
    """从当前用户的轮动池移除一只 ETF。只删自己那一行，别的用户不受影响。"""
    ok = await run_in_threadpool(EtfRotationService.delete_from_pool, user_id, symbol)
    if not ok:
        raise HTTPException(status_code=404, detail=f'ETF {symbol} 不在你的轮动池中')

    await _clear_rotation_cache()
    return {'code': 0, 'message': 'ok'}


async def _clear_rotation_cache():
    """池成员一变，**两个**缓存都要清。

    分析结果缓存（ROTATION_NS）不清的话：加完标的再次请求，query 参数没变 → 命中旧键
    → 新标的既不在排名里也不在热力图里，用户看到的就是「加了没反应」。
    """
    await FastAPICache.clear(namespace=ROTATION_POOL_NS)
    await FastAPICache.clear(namespace=ROTATION_NS)


@etf_rotation_router.get('/etf_rotation')
@cache(expire=cache_setting['etf_rotation'], namespace=ROTATION_NS)
def get_etf_rotation(
    lookback: Optional[int] = Query(None, ge=LOOKBACK_RANGE[0], le=LOOKBACK_RANGE[1],
                                    description='动量窗口（交易日），默认 20'),
    rebalance_days: Optional[int] = Query(None, ge=REBALANCE_RANGE[0], le=REBALANCE_RANGE[1],
                                          description='调仓周期（交易日），5≈周频，默认 5'),
    top_n: Optional[int] = Query(None, ge=1, le=POOL_LIMIT, description='每期持有只数，默认 3'),
    abs_filter: Optional[bool] = Query(None, description='绝对动量过滤：动量转负则空仓，默认开启'),
    cost: Optional[float] = Query(None, ge=COST_RANGE[0], le=COST_RANGE[1],
                                  description='单边交易费率，默认 0.0005'),
    window_days: Optional[int] = Query(None, ge=WINDOW_RANGE[0], le=WINDOW_RANGE[1],
                                       description='回测区间（自然日），默认 1095≈3 年'),
    user_id: int = Depends(get_current_user_id),
):
    """跑一次轮动分析：当前排名 + 净值回测 + 持仓演变 + 动量热力图。

    ⚠️ 这是全站最重的读接口之一：池内每只 ETF 都要单独拉区间日线（上游无批量行情接口），
    30 只约 1~2s。已按 cache_setting['etf_rotation']（15 分钟）整体缓存，命中与否看响应头
    `X-FastAPI-Cache: HIT|MISS`。

    池子不足 2 只、或取不到行情的标的 < 2 只时返回 400，detail 里是给用户看的原因。
    """
    try:
        return EtfRotationService.analyze(
            user_id,
            lookback=lookback,
            rebalance_days=rebalance_days,
            top_n=top_n,
            abs_filter=abs_filter,
            cost=cost,
            window_days=window_days,
        )
    except EtfRotationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 上游取数抖动 / 计算异常：记日志但不要把栈丢给前端
        logger.exception(f'etf_rotation analyze failed for user={user_id}: {e}')
        raise HTTPException(status_code=500, detail='轮动分析失败，请稍后重试')
