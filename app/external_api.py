"""
 * @author Yc
 * 对外 API 子应用：挂载到主应用的 /api/ext，自带独立 Swagger/OpenAPI 文档，
 * 仅暴露「只读投资组合数据」，统一用 API Key 鉴权 + 每日配额。
 *
 * 为什么用子应用（mount）而不是主应用里加 tag：
 *   - 主应用 /docs 是给内部前端用的（会话 token 鉴权），混进对外接口会污染文档；
 *   - 子应用有自己独立的 /api/ext/docs 与 /api/ext/openapi.json，文档只描述对外接口；
 *   - 安全方案（ApiKeyAuth）只在对外文档里出现，内部文档不受影响。
 *
 * 挂载顺序由 run_fastapi.py 保证：必须在 SPA catch-all 之前 mount，否则 /api/ext/* 会被当成页面回落。
"""

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from routes.external_portfolio import ext_portfolio_router
from utils.api_auth import ApiAuthError


def _auth_error_handler(request: Request, exc: ApiAuthError):
    """把 ApiAuthError 翻成统一信封 `{'code', 'message'}`（带 WWW-Authenticate / Retry-After）。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={'code': exc.status_code, 'message': exc.detail},
        headers=exc.headers,
    )


def create_external_app() -> FastAPI:
    app = FastAPI(
        title='AlphaLom 投资组合开放 API',
        description=(
            '基于 API Key 鉴权的投资组合数据开放接口（只读）。\n\n'
            '**鉴权**：在「API Key 管理」页创建密钥后，请求时携带 '
            '`X-API-Key: <你的密钥>`（或 `Authorization: Bearer <密钥>`）。\n\n'
            '**配额**：按用户 + 自然日计调用次数，超限返回 429 并带 `Retry-After`。'
        ),
        version='1.0.0',
        docs_url='/docs',
        openapi_url='/openapi.json',
    )

    app.include_router(ext_portfolio_router)
    app.add_exception_handler(ApiAuthError, _auth_error_handler)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        # 注入 API Key 安全方案，让 Swagger 出现「Authorize」按钮
        schema.setdefault('components', {}).setdefault('securitySchemes', {})['ApiKeyAuth'] = {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-API-Key',
            'description': '在「API Key 管理」页创建的对外密钥，作为请求头 X-API-Key 携带。',
        }
        # 对所有对外 operation 应用该安全方案（跳过 /docs、/openapi.json 本身）
        for path, ops in schema.get('paths', {}).items():
            if path in ('/docs', '/openapi.json'):
                continue
            for op in ops.values():
                if isinstance(op, dict):
                    op['security'] = [{'ApiKeyAuth': []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
    return app
