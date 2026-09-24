"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

认证与用户管理路由。

登录链路（与原实现的关键差别）：
  登录成功 → 签发 token 并写入 Redis（值 = user_id）→ 前端保存并在后续请求的
  `Authorization: Bearer <token>` 里带上 → `utils.auth.get_current_user` 每次校验。
原实现的 token 只是一串 uuid4、不落库不校验，业务接口实际是裸奔的；多用户隔离
必须建立在这条可校验的链路之上。

⚠️ 登录接口从 `run_fastapi.py` 迁到这里，**路径与响应结构保持不变**
（`/api/v1/auth/login`，返回 {status, message, token, user}），否则前端登录页立刻失效。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.fastapi_app import api_prefix
from service import UserService
from utils.auth import extract_token, get_current_user, require_admin
from utils.logger import logger

auth_router = APIRouter(prefix=api_prefix, tags=['认证与用户'])

# ⚠️ 这里的 async/def 取舍与其它模块同理：Service 层全是同步阻塞实现（pymysql +
# werkzeug 密码哈希），在 `async def` 路由里直接调用会占死唯一的事件循环
# （并发度退化为 1，登录一慢全站跟着卡）。凡是 `async def` 的地方，同步调用
# 一律走 run_in_threadpool；不需要 await 的（logout）就用同步 `def`。

# 管理员可改的用户字段（password 单独处理成 password_hash）
USER_WRITABLE_FIELDS = {'nickname', 'email', 'role', 'is_active'}


@auth_router.post('/auth/login', summary='登录', description='校验用户名或邮箱 + 密码，成功后签发令牌（存 Redis）')
async def auth_login(request: Request):
    """
    登录：从数据库校验账号/密码，成功返回 {status:1, token, user}。

    ⚠️ 入参字段名是 `username`（前端沿用历史命名），但语义是**用户名或邮箱** ——
    登录页上写的也是「用户名 / 邮箱」。原实现只按 username 精确匹配，导致
    「界面上写着 Email、实际必须填用户名」：填自己的邮箱永远登不上。

    保留原有的响应结构（前端 `Login.vue` 直接读 `data.status` / `data.token`）。
    新增一处失败语义：Redis 不可用时签发不出可校验的令牌，返回 503 而不是
    假装登录成功 —— 否则用户会拿到一个永远校验不过的 token，卡在
    「登录成功但每个页面都提示未登录」。
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    identifier = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not identifier or not password:
        return JSONResponse(content={'status': 0, 'message': '用户名/邮箱和密码不能为空'}, status_code=400)

    user = await run_in_threadpool(UserService.authenticate, identifier, password)
    if not user:
        return JSONResponse(content={'status': 0, 'message': '用户名/邮箱或密码错误'}, status_code=401)

    token = await run_in_threadpool(UserService.issue_token, user['id'])
    if not token:
        return JSONResponse(content={'status': 0, 'message': '鉴权服务暂不可用，请稍后再试'}, status_code=503)

    return JSONResponse(content={
        'status': 1,
        'message': 'Login successful!',
        'token': token,
        'user': user,
    }, status_code=200)


@auth_router.post('/auth/logout', summary='退出登录', description='删除当前令牌，立即失效')
def auth_logout(request: Request):
    """登出：删掉当前请求携带的令牌。令牌已失效时也返回成功（幂等）。"""
    UserService.revoke_token(extract_token(request))
    return {'status': 1, 'message': '已退出登录'}


@auth_router.get('/auth/me', summary='当前登录用户', description='返回令牌所属用户信息，可用于校验登录态是否仍然有效')
def auth_me(user: dict = Depends(get_current_user)):
    """当前用户信息。前端可用它判断令牌是否还有效（401 即需重新登录）。"""
    return user


@auth_router.get('/users', summary='用户列表', description='管理员查看全部账号')
def list_users(_admin: dict = Depends(require_admin)):
    users = UserService.get_all()
    users.sort(key=lambda u: u['id'])
    return users


@auth_router.post('/users', summary='新建用户', description='管理员建号（系统不开放自助注册）')
async def create_user(request: Request, _admin: dict = Depends(require_admin)):
    """
    管理员新建账号。入参：username / password 必填，nickname / email / role 可选。
    role 只接受 admin / user（默认 user），避免拼错角色名导致后续权限判断失效。

    ⚠️ 邮箱必须查占用再写：`users.email` 上有唯一索引（邮箱也是登录凭证，
    重复邮箱会让「邮箱登录」变成随机进某个账号），撞索引会抛 IntegrityError
    变成 500，体验上不如提前给 400。
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail='Request must be JSON')

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or 'user').strip()
    email = UserService.normalize_email(data.get('email'))

    if not username or not password:
        raise HTTPException(status_code=400, detail='用户名和密码不能为空')
    if role not in ('admin', 'user'):
        raise HTTPException(status_code=400, detail='role 只能是 admin 或 user')
    if await run_in_threadpool(UserService.get_by_username, username):
        raise HTTPException(status_code=400, detail=f'用户名 {username} 已存在')
    if email and await run_in_threadpool(UserService.email_exists, email):
        raise HTTPException(status_code=400, detail=f'邮箱 {email} 已被其它账号使用')

    created = await run_in_threadpool(UserService.add, {
        'username': username,
        'password': password,
        'nickname': (data.get('nickname') or username).strip(),
        'email': email,
        'role': role,
        'is_active': 1,
    })
    if not created:
        raise HTTPException(status_code=500, detail='创建用户失败')

    logger.info(f"管理员 {_admin['username']} 创建了用户 {username}（role={role}）")
    return created


@auth_router.put('/users/{user_id}', summary='修改用户', description='管理员修改昵称/邮箱/角色/启用状态/密码')
async def update_user(user_id: int, request: Request, _admin: dict = Depends(require_admin)):
    """
    管理员改用户。支持 nickname / email / role / is_active / password。

    ⚠️ 两条自我保护：不允许把自己禁用、不允许把自己降级为非管理员 ——
    否则一个误操作就能把系统里最后一个管理员锁在门外（再没人能改回来）。
    ⚠️ 改密码或禁用账号时会顺带撤销该用户的全部令牌（立即下线），
    否则旧令牌在 TTL 内仍然可用，改密码等于没改。
    ⚠️ 邮箱是登录凭证：改号前要查是否与别人重复（唯一索引会抛 IntegrityError → 500）；
    传空值表示清空邮箱（Service 层归一化成 NULL，不会与别人撞空串）。
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail='Request must be JSON')

    target = await run_in_threadpool(UserService.get_by_id, user_id)
    if not target:
        raise HTTPException(status_code=404, detail='用户不存在')

    payload = {k: v for k, v in data.items() if k in USER_WRITABLE_FIELDS}
    if 'password' in data:
        if not data['password']:
            raise HTTPException(status_code=400, detail='密码不能为空')
        payload['password'] = data['password']
    if 'role' in payload and payload['role'] not in ('admin', 'user'):
        raise HTTPException(status_code=400, detail='role 只能是 admin 或 user')
    if payload.get('email') and await run_in_threadpool(
            UserService.email_exists, payload['email'], user_id):
        raise HTTPException(status_code=400, detail='该邮箱已被其它账号使用')
    if not payload:
        raise HTTPException(status_code=400, detail='没有可更新的字段')

    if int(user_id) == int(_admin['id']):
        if payload.get('is_active') == 0:
            raise HTTPException(status_code=400, detail='不能禁用当前登录的管理员账号')
        if payload.get('role') not in (None, 'admin'):
            raise HTTPException(status_code=400, detail='不能取消当前登录管理员的管理员角色')

    ok = await run_in_threadpool(UserService.update, user_id, payload)
    if not ok:
        raise HTTPException(status_code=500, detail='更新用户失败')

    # 凭证相关变更必须立刻生效：改密码 / 禁用 → 撤销该用户所有令牌
    if 'password' in payload or payload.get('is_active') == 0:
        revoked = await run_in_threadpool(UserService.revoke_all_tokens, user_id)
        logger.info(f"用户 {target['username']} 凭证已变更，撤销 {revoked} 个登录令牌")

    return await run_in_threadpool(UserService.get_by_id, user_id)


@auth_router.delete('/users/{user_id}', summary='删除用户', description='管理员删除账号（不清理该用户名下的业务数据）')
async def delete_user(user_id: int, _admin: dict = Depends(require_admin)):
    """
    删除账号。

    ⚠️ 只删 `users` 里的一行，**不会**连带删除该用户名下的股票池 / 组合 / ETF 自选 ——
    那些数据会变成无主数据。要彻底清干净得先手工处理业务表，所以这里先禁止删除自己，
    其余情况下由调用方确认。撤销令牌是必做的，否则被删用户手里的 token 在 TTL 内仍然有效。
    """
    if int(user_id) == int(_admin['id']):
        raise HTTPException(status_code=400, detail='不能删除当前登录的账号')

    target = await run_in_threadpool(UserService.get_by_id, user_id)
    if not target:
        raise HTTPException(status_code=404, detail='用户不存在')

    ok = await run_in_threadpool(UserService.delete, user_id)
    if not ok:
        raise HTTPException(status_code=500, detail='删除用户失败')

    revoked = await run_in_threadpool(UserService.revoke_all_tokens, user_id)
    logger.info(f"管理员 {_admin['username']} 删除了用户 {target['username']}，撤销 {revoked} 个令牌")
    return {'code': 0, 'message': 'ok', 'revoked_tokens': revoked}
