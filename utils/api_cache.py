"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

接口级缓存接线（fastapi-cache3）。

用法：
  1. 应用启动时调用一次 `init_api_cache()`（`app.fastapi_app.create_app()` 已调用）；
  2. 路由上叠加装饰器 —— `@cache` 必须紧贴函数、放在 `@router.get` 下方：

        @stock_router.get('/stocks_monitored')
        @cache(expire=300, namespace='stocks_monitored')
        async def get_stocks_monitored(...):
            ...

  3. 失效：`await FastAPICache.clear(namespace='stocks_monitored')`

几个要点：
  - key 由 `default_key_builder` 生成：md5(func.__module__:__qualname__:args:kwargs)。
    FastAPI 会把 query 参数作为 kwargs 传给 endpoint，因此**所有查询参数天然进 key**，
    不像手写装饰器那样需要手工传参（也就不会漏参数导致串数据）。
  - 缓存里存的是 JSON（`JsonCoder`）。不能直接缓存 ORM 实例，必须先 `to_dict()`。
  - 服务端缓存与浏览器缓存是两回事：响应头由 `app.fastapi_app` 的 `apply_cache_policy`
    中间件统一压成 `no-store`（属于全局缓存策略的一部分），fastapi-cache3 想写的
    `max-age` 会被覆盖；命中情况看 `X-FastAPI-Cache: HIT|MISS` 头。
  - Redis 不可用不会导致 500：读失败回源、写失败只记 warning（库内部已捕获）。
    但每次请求都要等一次连接超时，所以 socket 超时设短。
"""

import os

import redis.asyncio as aioredis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import JsonCoder

from config import redis_host, redis_port

# 缓存 key 的统一前缀，便于在 Redis 中辨认与批量清理
CACHE_PREFIX = 'finfilo'

# Redis 故障时不要拖慢接口：连接与读写超时都设短，失败即回源
_SOCKET_TIMEOUT = float(os.getenv('CACHE_REDIS_TIMEOUT', '0.5'))


def _truthy(value):
    return value.strip().lower() not in ('0', 'false', 'no', 'off', '')


class ScanRedisBackend(RedisBackend):
    """用 SCAN 替代 KEYS 的 Redis 后端。

    fastapi-cache3 自带的 `clear(namespace=...)` 走 Lua + `KEYS`，
    keyspace 较大时会阻塞 Redis 单线程。这里改为游标式 SCAN 分批删除，
    与 `utils/redis_cache.py` 的失效方式保持一致。
    """

    async def clear(self, namespace=None, key=None):
        if key:
            return await self.redis.delete(key)
        if not namespace:
            return 0

        removed = 0
        async for k in self.redis.scan_iter(match=f'{namespace}:*', count=500):
            removed += await self.redis.delete(k)
        return removed


# 供业务代码复用（需要自己 set/get 时）；RedisBackend 要求 bytes 模式，
# 故 decode_responses=False —— 不要改成 True，否则反序列化会拿到 str 而失败。
async_redis = aioredis.Redis(
    host=redis_host,
    port=redis_port,
    db=0,
    decode_responses=False,
    socket_connect_timeout=_SOCKET_TIMEOUT,
    socket_timeout=_SOCKET_TIMEOUT,
    protocol=2
)


def init_api_cache():
    """初始化接口缓存。

    `FastAPICache.init()` 幂等（只生效第一次），重复调用无副作用。
    `API_CACHE_ENABLE=0` 可全局关停：接口照常工作，只是每次都回源，便于排查。
    """
    FastAPICache.init(
        ScanRedisBackend(async_redis),
        prefix=CACHE_PREFIX,
        coder=JsonCoder,
        enable=_truthy(os.getenv('API_CACHE_ENABLE', 'true')),
    )
