"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

多用户鉴权入口：从请求里还原「当前用户」的 FastAPI 依赖。

token 的取法（按优先级）：
  1. `Authorization: Bearer <token>` —— 前端 axios 拦截器统一注入（正常路径）
  2. `X-Token: <token>`              —— 手工/脚本调用方便
  3. query 参数 `?token=<token>`      —— 兜底（直接用浏览器打开链接的场景）

用法：
  - 需要「当前用户 id」参与缓存键的路由：
        user_id: int = Depends(get_current_user_id)
    ⚠️ 这是**用户维度隔离接口缓存**的正确做法。FastAPI 会把依赖解析结果作为 kwargs
    传给 endpoint 函数，而 fastapi_cache 的默认 key builder 正是把 kwargs 拼进 key，
    所以 user_id 天然进 key。**不要**去手工拼 namespace，也不要指望给依赖返回
    ORM 对象 —— 那个 repr 带内存地址，每次都不同，缓存会永远不命中。
  - 只需要用户信息：`user: dict = Depends(get_current_user)`
  - 管理员接口：`admin: dict = Depends(require_admin)`（顺带拿到管理员身份做自我校验）

未登录 / 令牌失效一律抛 401。这是多用户下的既定取舍：宁可让前端报错重新登录，
也绝不能「拿不到用户就当默认用户」—— 那等于把 A 的数据给 B 看。
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request

from service import UserService

# 未带/带错凭证的标准响应头
_UNAUTHORIZED_HEADERS = {'WWW-Authenticate': 'Bearer'}


def extract_token(request: Request) -> Optional[str]:
    """从请求里取出 token（取不到返回 None）。"""
    authorization = request.headers.get('authorization') or ''
    if authorization.lower().startswith('bearer '):
        token = authorization[7:].strip()
        if token:
            return token

    token = (request.headers.get('x-token') or '').strip()
    if token:
        return token

    token = (request.query_params.get('token') or '').strip()
    return token or None


def get_current_user(request: Request) -> dict:
    """
    校验令牌并返回当前用户 dict（User.to_dict()，不含密码哈希）。
    未登录或令牌失效抛 401。
    """
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail='未登录：缺少访问令牌',
                            headers=_UNAUTHORIZED_HEADERS)

    user = UserService.resolve_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='登录已失效，请重新登录',
                            headers=_UNAUTHORIZED_HEADERS)
    return user


def get_current_user_id(user: dict = Depends(get_current_user)) -> int:
    """
    只取当前用户 id。给「需要用户维度进缓存键」的路由用（见模块 docstring）。
    """
    return int(user['id'])


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员专用接口的门禁：非 admin 抛 403。"""
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='需要管理员权限')
    return user
