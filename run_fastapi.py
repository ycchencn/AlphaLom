"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主服务入口
 * 替代原 Flask run_app.py
"""

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
)
from app.fastapi_app import create_app
from config import server_setting
from models.init_db import init_database
import os

# 创建 FastAPI 应用
# docs_url=None / redoc_url=None：Swagger UI / ReDoc 的静态资源默认走 jsdelivr CDN，
# 该 CDN 曾被 reset 导致 /docs 白屏。这里关闭默认路由，改用本地自托管资源
# （static/vendor/swagger-ui/，见下方 _docs_router()），彻底摆脱外部 CDN 依赖。
app = create_app(docs_url=None, redoc_url=None)
env = os.getenv('ENV', 'dev').lower()

# ==================== 路由注册 ====================
from routes.auth import auth_router
from routes.altcha import altcha_router
from routes.stock import stock_router
from routes.market import market_router
from routes.portfolio import portfolio_router
from routes.etf import etf_router
from routes.etf_rotation import etf_rotation_router
from routes.quant import quant_router
from routes.index import index_router
from routes.syslog import syslog_router
from routes.llm import llm_router
from routes.system_setting import settings_router
from routes.backtest import backtest_router
from routes.agent import agent_router
from routes.chat_stream import chat_router
from routes.token_usage import token_usage_router
from routes.api_key import api_key_router
from routes.factor import factor_router
from app.external_api import create_external_app

app.include_router(auth_router)
# 人机校验出题（登录页在拿到令牌前调用，故不鉴权）；校验逻辑在 utils/altcha.py
app.include_router(altcha_router)
app.include_router(stock_router)
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(etf_router)
# ETF 轮动（池管理 + 动量轮动回测）；与 etf_router 同 prefix/tags，Swagger 里同属 ETF 分组
app.include_router(etf_rotation_router)
app.include_router(quant_router)
app.include_router(index_router)
app.include_router(syslog_router)
app.include_router(llm_router)
app.include_router(settings_router)
app.include_router(backtest_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(token_usage_router)
app.include_router(api_key_router)
app.include_router(factor_router)

# ==================== 自托管 Swagger UI / ReDoc ====================
# 默认的 /docs、/redoc 指向 jsdelivr CDN，被 reset 后无法加载。这里用本地
# static/vendor/swagger-ui/（app/fastapi_app.py 里已 mount 到 /swagger-ui）重新注册。
# 必须放在所有 include_router 之后、/api/ext mount 与 SPA 兜底之前注册。
app.add_api_route(
    '/docs',
    lambda: get_swagger_ui_html(
        openapi_url='/openapi.json',
        title='AlphaLom 量化交易系统 - Swagger UI',
        swagger_js_url='/swagger-ui/swagger-ui-bundle.js',
        swagger_css_url='/swagger-ui/swagger-ui.css',
        swagger_favicon_url='/swagger-ui/favicon-32x32.png',
    ),
    methods=['GET'],
    include_in_schema=False,
)
app.add_api_route(
    '/redoc',
    lambda: get_redoc_html(
        openapi_url='/openapi.json',
        title='AlphaLom 量化交易系统 - ReDoc',
        redoc_js_url='/swagger-ui/redoc.standalone.js',
        redoc_favicon_url='/swagger-ui/favicon-32x32.png',
        with_google_fonts=False,
    ),
    methods=['GET'],
    include_in_schema=False,
)

# ==================== 对外 API 子应用（mount 必须在 SPA catch-all 之前）====================
# /api/ext 提供独立的 Swagger/OpenAPI（API Key 鉴权 + 每日配额），详见 app/external_api.py。
# 必须在下面的 `if os.path.isdir(static_dir)` SPA 兜底之前 mount，否则 /api/ext/* 会被当成页面回落。
ext_app = create_external_app()
app.mount('/api/ext', ext_app)

# ==================== 登录接口 ====================
# 登录 / 登出 / 当前用户 / 用户管理已统一收敛到 routes/auth.py（含签发与校验逻辑），
# 这里不再单独注册 —— 两处同时注册同一路径时，先注册的会接走请求，
# 排查起来像是「改了没生效」。

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
    # 启动参数统一来自 config.server_setting（host / port / workers）。
    # 单进程内的多线程并发由 server_setting['thread_pool_size'] 控制，
    # 在应用的 lifespan 里应用（须在事件循环内，见 app/fastapi_app.py）。
    uvicorn.run(
        'run_fastapi:app',
        host=server_setting['host'],
        port=server_setting['port'],
        # dev 下开启热重载；uvicorn 在 reload 模式下会强制单进程，workers 随之失效
        reload=(env == 'dev'),
        workers=server_setting['workers'],
    )
