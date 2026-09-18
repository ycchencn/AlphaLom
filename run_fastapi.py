"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主服务入口
 * 替代原 Flask run_app.py
"""

import uvicorn
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from app.fastapi_app import create_app, api_prefix
from service import UserService
from models.init_db import init_database
import os

# 创建 FastAPI 应用
app = create_app()
env = os.getenv('ENV', 'dev').lower()

# ==================== 路由注册 ====================
from routes.stock import stock_router
from routes.market import market_router
from routes.portfolio import portfolio_router
from routes.watchlist import watchlist_router
from routes.etf import etf_router
from routes.quant import quant_router
from routes.index import index_router
from routes.syslog import syslog_router

app.include_router(stock_router)
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(etf_router)
app.include_router(quant_router)
app.include_router(index_router)
app.include_router(syslog_router)

# ==================== 登录接口 ====================
@app.post(f'{api_prefix}/auth/login')
async def auth_login(request: Request):
    """登录接口：从数据库校验用户名/密码"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return JSONResponse(content={'status': 0, 'message': '用户名和密码不能为空'}, status_code=400)

    user = UserService.authenticate(username, password)
    if user:
        token = UserService.generate_token(username)
        return JSONResponse(content={
            'status': 1,
            'message': 'Login successful!',
            'token': token,
            'user': user,
        }, status_code=200)
    return JSONResponse(content={'status': 0, 'message': '用户名或密码错误'}, status_code=401)

# ==================== 静态文件服务 ====================
static_dir = os.path.join(os.path.dirname(__file__), 'dist')

# 缺失的静态资源直接 404，不回落 index.html：
# 老页面请求已下线的 hashed 产物（/assets/index-OLD.js）时若返回 HTML，
# 浏览器只会报一个含糊的 MIME 错误，问题很难定位
STATIC_ASSET_SUFFIXES = (
    '.js', '.mjs', '.css', '.map', '.json', '.wasm',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
)

if os.path.isdir(static_dir):
    @app.get('/')
    async def serve_index():
        return FileResponse(os.path.join(static_dir, 'index.html'))

    @app.get('/{full_path:path}')
    async def serve_spa(full_path: str):
        file_path = os.path.join(static_dir, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        if full_path.lower().endswith(STATIC_ASSET_SUFFIXES):
            raise HTTPException(status_code=404, detail=f'Static asset not found: /{full_path}')
        # SPA fallback: 所有非 API 路径返回 index.html
        return FileResponse(os.path.join(static_dir, 'index.html'))


# ==================== 启动 ====================
if __name__ == '__main__':
    init_database()
    uvicorn.run(
        'run_fastapi:app',
        host='0.0.0.0',
        port=8080,
        reload=(env=='dev'),
        workers=int(os.getenv('WEB_WORKERS', '1')),
    )