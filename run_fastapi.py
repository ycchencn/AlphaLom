"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * FastAPI 主服务入口
 * 替代原 Flask run_app.py
"""

import uvicorn
import time
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
)
from app.fastapi_app import create_app
from config import server_setting
from models.init_db import init_database
import os

logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
# docs_url=None / redoc_url=None：Swagger UI / ReDoc 的静态资源默认走 jsdelivr CDN，
# 该 CDN 曾被 reset 导致 /docs 白屏。这里关闭默认路由，改用本地自托管资源
# （public/vendor/swagger-ui/，见下方 _docs_router()），彻底摆脱外部 CDN 依赖。
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
from routes.announcement import stock_announcement_router
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
# 公司公告（投资组合 → 公司公告）：本地副本查询 + 手动同步投递
app.include_router(stock_announcement_router)

# ==================== 自托管 Swagger UI / ReDoc ====================
# 默认的 /docs、/redoc 指向 jsdelivr CDN，被 reset 后无法加载。这里用本地
# public/vendor/swagger-ui/（app/fastapi_app.py 里已 mount 到 /swagger-ui）重新注册。
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
    # ==================== 网站统计代码（后端注入） ====================
    # 管理员在「系统管理 → 通用设置 → 网站统计代码」粘贴的第三方统计片段
    # （百度统计 / CNZZ / Google Analytics / umami 等），由后端在服务 index.html
    # 时直接注入 </body> 之前，对所有访客（含未登录）生效。
    #
    # 为什么改成后端注入：原先靠前端 main.js 在启动 / 登录后 fetch 接口再注入，
    # 既要求已登录令牌（未登录访客统计不到），又只在特定时机触发，极易「没效果」。
    # 后端把代码写进 HTML 源，浏览器原生执行其中的 <script>，最稳。
    from service.system_setting_service import SystemSettingService
    from routes.system_setting import GENERAL_SETTING_GROUP, GENERAL_ANALYTICS_KEY

    _analytics_cache = {"value": None, "at": 0.0}
    _ANALYTICS_TTL = 300  # 秒：统计代码读取缓存，避免每个页面请求都打一次 DB
    _index_cache = {"path": None, "mtime": 0.0, "content": ""}

    def _read_index_html():
        """读 dist/index.html 原文并按文件 mtime 缓存（重新构建后自动刷新）。"""
        path = os.path.join(static_dir, 'index.html')
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        if _index_cache["path"] == path and _index_cache["mtime"] == mtime:
            return _index_cache["content"]
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as e:
            logger.error(f"读取 index.html 失败: {e}")
            return None
        _index_cache["path"] = path
        _index_cache["mtime"] = mtime
        _index_cache["content"] = content
        return content

    def _get_analytics_code():
        """读取统计代码（带短时缓存；失败回落到上次成功值，不刷新时间戳以便尽快重试）。"""
        now = time.time()
        if _analytics_cache["value"] is not None and (now - _analytics_cache["at"]) < _ANALYTICS_TTL:
            return _analytics_cache["value"]
        try:
            code = SystemSettingService.get_value(
                f"{GENERAL_SETTING_GROUP}.{GENERAL_ANALYTICS_KEY}", default=""
            ) or ""
            if not isinstance(code, str):
                code = ""
        except Exception as e:
            logger.warning(f"读取统计代码失败，暂用上次缓存值: {e}")
            return _analytics_cache["value"] or ""
        _analytics_cache["value"] = code
        _analytics_cache["at"] = now
        return code

    def _serve_index_html():
        """返回注入了统计代码的 index.html（无统计代码时原样返回）。"""
        html = _read_index_html()
        if html is None:
            raise HTTPException(status_code=503, detail="index.html not found")
        code = (_get_analytics_code() or "").strip()
        if code:
            # 直接把代码片段放进 HTML 源，浏览器会原生执行其中的 <script>，
            # 无需前端 innerHTML 重建。display:none 容器挡住代码里可能夹带的可见图标。
            injection = f'<div data-analytics="server-injected" style="display:none">{code}</div>'
            if "</body>" in html:
                html = html.replace("</body>", f"{injection}\n</body>", 1)
            else:
                html = f"{html}{injection}"
        return HTMLResponse(content=html, media_type="text/html; charset=utf-8")

    @app.get('/')
    def serve_index():
        return _serve_index_html()

    @app.get('/{full_path:path}')
    def serve_spa(full_path: str):
        file_path = os.path.join(static_dir, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        if full_path.lower().endswith(STATIC_ASSET_SUFFIXES):
            raise HTTPException(status_code=404, detail=f'Static asset not found: /{full_path}')
        # SPA fallback: 所有非 API 路径返回注入了统计代码的 index.html
        return _serve_index_html()


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
