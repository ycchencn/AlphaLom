"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

两级缓存工具：Redis 为权威来源（跨进程 / 多 worker 一致），进程内 LRU 只作兜底。

三个容易踩的点（否则加了缓存反而制造"数据不刷新"的问题）：
  1. Redis 可达但 key 不存在时**必须**视为未命中，不能再回落到进程内 LRU ——
     否则其它 worker 删掉 key 后，本进程仍会一直吐旧值，失效形同虚设；
  2. 只能装饰同步函数。给 async def 用会把 coroutine 对象 pickle 进 Redis，
     报 "cannot pickle 'coroutine' object"。装饰器会显式拦下这种误用；
  3. 不要把 RedisLRUCache 做成 dict 的子类 —— LRUCache 的 pop / clear / popitem /
     __contains__ 内部都会回调 `self[key]`，一旦把 `__getitem__` 重写成接收
     `(args, kwargs)` 元组就会炸。这里改为显式方法（lookup / store / invalidate）。
  4. 被缓存的值会被 pickle：只放纯 Python 数据（dict / list / 标量 / Decimal / date）。
     别放 ORM 实例 —— 解包后是游离对象，访问未加载属性会抛 DetachedInstanceError。
     现有 service 层统一返回 `to_dict()`，符合该约定。
"""

import functools
import hashlib
import inspect
import pickle

from cachetools import LRUCache

from .redis_obj import redis_obj as redis_client

# 缓存 key 前缀，同时用于按前缀批量失效
CACHE_KEY_PREFIX = 'api_cache'
KEY_PREFIX_SEPARATOR = '__'


class RedisLRUCache:
    """Redis（权威）+ 进程内 LRU（兜底）的两级缓存"""

    def __init__(self, maxsize, expire_time, method_name, *args, **kwargs):
        self._local = LRUCache(maxsize)
        self.expire_time = expire_time
        self.method_name = method_name

    def generate_key(self, args, kwargs):
        # 组合参数和方法名，并生成其md5值
        digest = hashlib.md5((self.method_name + repr(args) + repr(kwargs)).encode('utf-8')).hexdigest()
        return f'{CACHE_KEY_PREFIX}{KEY_PREFIX_SEPARATOR}{self.method_name}{KEY_PREFIX_SEPARATOR}{digest}'

    @property
    def key_pattern(self):
        """本缓存所有 key 的模式，供批量失效使用"""
        return f'{CACHE_KEY_PREFIX}{KEY_PREFIX_SEPARATOR}{self.method_name}{KEY_PREFIX_SEPARATOR}*'

    def lookup(self, key_args_kwargs):
        """取缓存；未命中抛 KeyError（沿用 dict 语义，装饰器好写）"""
        args, kwargs = key_args_kwargs
        key_str = self.generate_key(args, kwargs)

        try:
            raw = redis_client.get(key_str)
        except Exception:
            # Redis 不可用：降级为进程内缓存（有就用，没有就 KeyError 走回源）
            return self._local[key_str]

        if raw is None:
            # Redis 是权威来源：没有就是没有，顺手清掉本地可能残留的旧值
            self._local.pop(key_str, None)
            raise KeyError(key_str)

        return pickle.loads(raw)

    def store(self, key_args_kwargs, value):
        args, kwargs = key_args_kwargs
        key_str = self.generate_key(args, kwargs)

        try:
            redis_client.set(key_str, pickle.dumps(value), ex=self.expire_time)
        except Exception:
            # Redis 写入失败不影响本次返回，进程内缓存仍生效
            pass

        self._local[key_str] = value

    def invalidate(self):
        """清空本缓存：先清进程内，再按前缀删 Redis。
        其它 worker 的进程内缓存没法直接清，但它们读 Redis 会未命中，
        因未命中即权威（见 lookup），下次请求自然回源。"""
        self._local.clear()
        try:
            for key in redis_client.scan_iter(match=self.key_pattern, count=500):
                redis_client.delete(key)
        except Exception:
            pass

    def __len__(self):
        return len(self._local)


# 使用自定义的缓存装饰器
def lru_redis_cache(expire_time=3600, maxsize=100):
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            raise TypeError(
                f'lru_redis_cache 不支持 async 函数（{func.__name__}）：'
                'coroutine 无法 pickle 进 Redis。请把取数逻辑抽成同步函数后再装饰。'
            )

        cache = RedisLRUCache(maxsize, expire_time, func.__name__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key_args_kwargs = (args, kwargs)
            try:
                return cache.lookup(key_args_kwargs)
            except KeyError:
                result = func(*args, **kwargs)
                cache.store(key_args_kwargs, result)
                return result

        # 暴露缓存对象与失效入口，供写路径主动清缓存
        wrapper.cache = cache
        wrapper.invalidate = cache.invalidate
        return wrapper

    return decorator
