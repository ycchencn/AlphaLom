"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主应用初始化
 * 替代原 Flask app/__init__.py
"""

import ipaddress
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import redis_host, redis_port
from redis import ConnectionPool

# ==================== 数据库 ====================
# Flask-SQLAlchemy 的 db 实例共用同一个 engine
# FastAPI 中直接使用 db.session 或 models.database.db_session

# ==================== Redis 连接池 ====================
redis_pool = ConnectionPool(host=redis_host, port=redis_port, db=0)

# ==================== API 前缀 ====================
api_prefix = '/api/v1'

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


def trading_cache_key() -> str:
    """
    动态生成缓存键
    注意：FastAPI 中需在路由内调用，传入 request 参数
    """
    now = datetime.now()
    is_after_hours = now.hour >= 15 or now.hour < 9
    return f"PH_{now.strftime('%Y%m%d%H')}" if is_after_hours else f"TRD_{now.strftime('%Y%m%d%H')}"


# ==================== 快速创建 FastAPI 应用 ====================
def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    _app = FastAPI(
        title="FinFilo 量化交易系统",
        description="基于 LLM 的量化交易与分析平台",
        version="2.0.0",
    )

    # CORS 配置
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载静态文件（Vue 打包产物）
    import os
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dist')
    if os.path.isdir(static_dir):
        _app.mount('/assets', StaticFiles(directory=os.path.join(static_dir, 'assets')), name='assets')
        # _app.mount('/fonts', StaticFiles(directory=os.path.join(static_dir, 'fonts')), name='fonts')

    return _app


# ==================== 向后兼容：导出 cache 对象 ====================
class _NoopCache:
    """占位缓存对象，替换 Flask-Caching 的 cache
    后续可替换为基于 Redis 的 FastAPI 缓存实现"""

    @staticmethod
    def cached(timeout=300, query_string=False, make_cache_key=None):
        def decorator(func):
            return func
        return decorator


cache = _NoopCache()