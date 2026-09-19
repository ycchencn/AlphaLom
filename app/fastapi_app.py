"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主应用初始化
 * 替代原 Flask app/__init__.py
"""

import ipaddress
import re
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import redis_host, redis_port, server_setting
from redis import ConnectionPool

from models.database import (
    begin_request_scope,
    db_session,
    end_request_scope,
)
from utils.api_cache import init_api_cache
from utils.logger import logger

# ==================== 数据库 ====================
# 会话对象统一由 models.database 提供（db_session），业务代码直接使用即可。
# 会话的创建与回收由下面的请求级中间件管理，不要在业务代码里手动 remove()。

# ==================== Redis 连接池 ====================
redis_pool = ConnectionPool(host=redis_host, port=redis_port, db=0)

# ==================== API 前缀 ====================
api_prefix = '/api/v1'

# ==================== 缓存策略 ====================
# 默认一律不缓存：HTML 入口（SPA 路由全部回落到 index.html）和接口响应
# 一旦被浏览器 / CDN / 反向代理缓存住，改完代码用户还是看到旧页面、旧数据。
# 唯一例外是 Vite 构建产物 —— 文件名里带内容 hash（/assets/index-kLiojf6m.js），
# 内容变则文件名必变，可以放心长期缓存，省掉每次开页面重下几 MB 的字体和 Monaco。
CACHE_NO_STORE = 'no-store, no-cache, must-revalidate, max-age=0'      # 页面 + 接口
CACHE_REVALIDATE = 'no-cache, must-revalidate'                          # 其余静态资源，每次回源校验（304 很轻）
CACHE_IMMUTABLE = 'public, max-age=31536000, immutable'                 # 带 hash 的构建产物，一年

# 构建产物目录，且文件名必须带 8 位以上 hash 才认定为不可变资源
HASHED_ASSET_PREFIX = '/assets/'
HASHED_ASSET_PATTERN = re.compile(r'-[A-Za-z0-9_]{8,}\.(?:js|mjs|css|woff2?|ttf|otf|png|jpe?g|svg|wasm)$')

# 这些后缀属于静态资源：缓存但每次回源校验；其余（HTML / API）一律 no-store
STATIC_FILE_SUFFIXES = (
    '.js', '.mjs', '.css', '.map', '.json', '.txt', '.xml',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.woff', '.woff2', '.ttf', '.otf', '.eot', '.wasm',
)


def resolve_cache_control(path: str) -> str:
    """按请求路径决定 Cache-Control"""
    lower_path = path.lower()
    if lower_path.startswith(HASHED_ASSET_PREFIX) and HASHED_ASSET_PATTERN.search(lower_path):
        return CACHE_IMMUTABLE
    if lower_path.endswith(STATIC_FILE_SUFFIXES):
        return CACHE_REVALIDATE
    # 页面（HTML / SPA 路由）与接口
    return CACHE_NO_STORE


# ==================== 代理 IP 配置 ====================
TRUSTED_PROXIES = [
    '127.0.0.1',
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
]


def is_trusted_proxy(ip: str) -> bool:
    """检查 IP 是否在可信代理列表中"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        for trusted in TRUSTED_PROXIES:
            if '/' in trusted:
                if ip_obj in ipaddress.ip_network(trusted, strict=False):
                    return True
            else:
                if ip_obj == ipaddress.ip_address(trusted):
                    return True
        return False
    except ValueError:
        return False


def get_real_ip(request: Request, trusted_only: bool = True) -> Optional[str]:
    """
    获取用户真实 IP 地址（带安全验证）
    FastAPI 版本，需传入 Request 对象
    """
    remote_addr = request.client.host if request.client else None

    if trusted_only and remote_addr and not is_trusted_proxy(remote_addr):
        return remote_addr

    headers_to_check = [
        'x-forwarded-for',
        'x-real-ip',
        'cf-connecting-ip',
        'true-client-ip',
        'x-client-ip',
        'forwarded',
    ]

    for header in headers_to_check:
        value = request.headers.get(header)
        if value:
            if header == 'x-forwarded-for':
                ips = [ip.strip() for ip in value.split(',')]
                for ip in ips:
                    if ip:
                        return ip
            else:
                return value.strip()

    return remote_addr


def get_client_info(request: Request) -> dict:
    """获取完整的客户端信息"""
    return {
        'real_ip': get_real_ip(request),
        'remote_addr': request.client.host if request.client else None,
        'user_agent': request.headers.get('user-agent', ''),
        'forwarded_for': request.headers.get('x-forwarded-for'),
        'is_trusted': is_trusted_proxy(request.client.host) if request.client else False,
    }


def json_resp(ctx: dict) -> dict:
    """统一 JSON 响应（直接返回 dict，FastAPI 自动序列化）"""
    return ctx


# ==================== 并发参数 ====================
def apply_thread_pool_size() -> None:
    """把 config.server_setting['thread_pool_size'] 应用到 anyio 线程池。

    本项目绝大多数路由是同步 `def`，由 Starlette 丢进 anyio 线程池执行（不写
    `async def` 才能拿到多线程并发，见 routes/ 各文件顶部注释）。anyio 线程池
    上限默认 40，这里按配置改。

    **必须在事件循环内调用**：`current_default_thread_limiter()` 依赖当前运行的
    async 后端，在事件循环外调用会抛 `NoEventLoopError`（anyio 4.15 实测）。
    所以不能放在模块导入期，只能放在 lifespan 里。

    多 worker 时每个 worker 进程各自跑一次 lifespan，各改各的，互不影响。
    配 0 或负数表示不干预，沿用 anyio 默认值。
    """
    size = int(server_setting.get('thread_pool_size') or 0)
    if size <= 0:
        return

    limiter = anyio.to_thread.current_default_thread_limiter()
    if limiter.total_tokens == size:
        logger.info(f"线程池上限已是 {size}，无需调整")
        return
    logger.info(
        f"线程池上限 {limiter.total_tokens} -> {size}"
        f"（同步路由最大并发；本进程 workers={server_setting['workers']}）"
    )
    limiter.total_tokens = size


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用启动/关闭钩子（每个 worker 进程各执行一次）"""
    apply_thread_pool_size()
    yield


# ==================== 快速创建 FastAPI 应用 ====================
def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    _app = FastAPI(
        title="AlphaLom 量化交易系统",
        description="基于 LLM 的量化交易与分析平台",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS 配置
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局缓存策略：默认 no-store，只有带 hash 的构建产物长期缓存
    # 中间件统一下发，才能同时覆盖 FileResponse（HTML / 静态文件）、
    # JSONResponse 和直接返回 HTMLResponse 的接口
    @_app.middleware('http')
    async def apply_cache_policy(request: Request, call_next):
        response = await call_next(request)
        cache_control = resolve_cache_control(request.url.path)
        response.headers['Cache-Control'] = cache_control
        if cache_control == CACHE_NO_STORE:
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # 请求级数据库会话：一个请求一个 Session，响应结束立即回收。
    # 不做这件事的话，scoped_session 的 thread-local 作用域在「全 async 路由 + 单事件循环线程」
    # 下会退化成整个进程共用一个 Session：事务长期不提交，MySQL REPEATABLE READ 的读快照
    # 被钉死，接口会一直返回旧数据（看起来就像接口被缓存了），同时连接也不归还连接池。
    @_app.middleware('http')
    async def db_session_scope(request: Request, call_next):
        reset_token = begin_request_scope(uuid.uuid4().hex)
        try:
            return await call_next(request)
        finally:
            # remove() 会关闭会话（回滚未提交事务）并把连接归还连接池
            db_session.remove()
            end_request_scope(reset_token)

    # 接口级缓存（fastapi-cache3，Redis 后端）。缓存的是服务端计算结果，
    # 与上面 apply_cache_policy 是两回事：浏览器侧仍收到 no-store、每次回源，
    # 由服务端决定是否直接返回缓存。具体接法与注意事项见 utils/api_cache.py。
    init_api_cache()

    # 挂载静态文件（Vue 打包产物）
    import os
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dist')
    # if os.path.isdir(static_dir):
    #     _app.mount('/assets', StaticFiles(directory=os.path.join(static_dir, 'assets')), name='assets')
        # _app.mount('/fonts', StaticFiles(directory=os.path.join(static_dir, 'fonts')), name='fonts')

    return _app
