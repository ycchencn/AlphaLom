"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主应用初始化
 * 替代原 Flask app/__init__.py
"""

import ipaddress
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

# ==================== 禁用缓存的接口前缀 ====================
# 投资组合（策略）数据必须实时反映最新持仓与净值，
# 这些前缀下的接口响应不参与任何缓存（后端 / 浏览器 / CDN / 反向代理）
NO_CACHE_PATH_PREFIXES = (
    f'{api_prefix}/investment_portfolios',
    f'{api_prefix}/portfolio',
)

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

    # 关闭投资组合相关接口的缓存
    # 显式下发 no-store 响应头，确保浏览器 / CDN / 反向代理都不缓存策略数据
    @_app.middleware('http')
    async def disable_cache_for_portfolio(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(NO_CACHE_PATH_PREFIXES):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # 挂载静态文件（Vue 打包产物）
    import os
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dist')
    if os.path.isdir(static_dir):
        _app.mount('/assets', StaticFiles(directory=os.path.join(static_dir, 'assets')), name='assets')
        # _app.mount('/fonts', StaticFiles(directory=os.path.join(static_dir, 'fonts')), name='fonts')

    return _app
