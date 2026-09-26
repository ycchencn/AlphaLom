"""
 * @author Yc
 * 对外 API 的 API Key 鉴权依赖 + 每日配额。
 *
 * 设计（对齐 fastapi-api-key-auth-quota 技能）：
 * - 凭证两种等价写法：请求头 `X-API-Key: <key>` 或 `Authorization: Bearer <key>`；
 *   从 request.headers 直接读，**不**把 X-API-Key 声明成函数参数，避免 Swagger 每个接口都多出
 *   一个重复字段（安全方案由外部子应用的 custom_openapi 单独注入）。
 * - 失败原因不细分：不存在 / 已吊销 / 已过期 / 用户被禁用 → 统一 401，不泄露密钥是否存在。
 * - 鉴权 fail-closed（Redis 连不上 = 503，不能猜）；配额 fail-open（Redis 抖动宁可放行，别打死正常业务）。
 * - 配额按「用户 + 自然日」计（`apiquota:used:{user_id}:{YYYYMMDD}`），同用户多 Key 共享额度；
 *   超限返回 429 + Retry-After（到次日零点的秒数）。
"""

import hashlib
import json
from datetime import datetime, timedelta

from config import api_setting
from fastapi import HTTPException, Request, Response
from utils.logger import logger
from utils.redis_obj import redis_obj

# 配额计数键前缀（与 api_key 的 Redis 索引前缀区分开，避免误删）
_QUOTA_KEY_PREFIX = 'apiquota:used:'


class ApiAuthError(HTTPException):
    """对外 API 的统一鉴权错误：翻成 `{'code': status, 'message': detail}` 信封。

    只接管这一个子类，其它 HTTPException（404/400 等）行为不变，不误伤既有接口。
    """

    def __init__(self, status_code: int, detail: str, retry_after: int = None):
        headers = {}
        if status_code == 401:
            headers['WWW-Authenticate'] = 'ApiKey'
        if retry_after is not None:
            headers['Retry-After'] = str(retry_after)
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def _extract_api_key(request: Request) -> str | None:
    ak = request.headers.get('x-api-key')
    if ak and ak.strip():
        return ak.strip()
    authorization = request.headers.get('authorization') or ''
    if authorization.lower().startswith('bearer '):
        token = authorization[7:].strip()
        if token:
            return token
    return None


def _seconds_to_next_day() -> int:
    now = datetime.now()
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return int((tomorrow - now).total_seconds())


def _check_quota(user_id: int, quota):
    """返回 (allowed, remaining_or_None, retry_after_or_None)。quota=None 表示不限。"""
    if quota is None:
        return True, None, None
    key = f"{_QUOTA_KEY_PREFIX}{int(user_id)}:{datetime.now():%Y%m%d}"
    try:
        current = int(redis_obj.get(key) or 0)
        if current >= quota:
            return False, 0, _seconds_to_next_day()
        new = redis_obj.incr(key)
        if new == 1:
            # 首次计数才设过期：窗口 = 到次日零点 + 1 小时冗余；跨天归零靠键里带日期，不用定时任务
            redis_obj.expire(key, _seconds_to_next_day() + 3600)
        remaining = max(0, quota - new)
        return True, remaining, None
    except Exception as e:
        logger.warning(f"配额计数失败，按 fail-open 放行: {e}")
        return True, None, None


def require_api_user(request: Request, response: Response) -> int:
    """
    对外 API 的鉴权依赖：解析并校验 API Key，返回当前用户 id（用于隔离与缓存键）。

    用法（外部子应用的路由）：`user_id: int = Depends(require_api_user)`
    """
    from service.api_key import ApiKeyService  # 局部导入，避免循环依赖

    raw = _extract_api_key(request)
    if not raw:
        raise ApiAuthError(401, '缺少 API Key：请在 X-API-Key 或 Authorization: Bearer 头中提供')

    key_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    try:
        data = redis_obj.get(f"{api_setting['key_prefix']}{key_hash}")
    except Exception as e:
        # 鉴权强依赖 Redis，连不上不能猜 → 503
        logger.error(f"API Key 校验时 Redis 不可用: {e}")
        raise ApiAuthError(503, '鉴权服务暂不可用，请稍后重试')

    if not data:
        raise ApiAuthError(401, 'API Key 无效或已吊销')

    try:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode('utf-8')
        payload = json.loads(data)
        user_id = int(payload['u'])
        quota = payload.get('q')
    except Exception:
        raise ApiAuthError(401, 'API Key 无效或已吊销')

    # 有效配额：本 Key 覆盖值优先，否则回退全局默认；两者皆 None → 不限
    effective_quota = quota if quota is not None else api_setting.get('daily_quota')
    allowed, remaining, retry_after = _check_quota(user_id, effective_quota)
    if not allowed:
        raise ApiAuthError(429, '今日调用额度已用尽，请于次日重试', retry_after=retry_after)

    if remaining is not None:
        response.headers['X-RateLimit-Limit'] = str(effective_quota)
        response.headers['X-RateLimit-Remaining'] = str(remaining)

    # 节流写回 last_used_at（每次请求都 UPDATE 会把读接口的写压力抬起来）
    try:
        ApiKeyService.touch_last_used(key_hash)
    except Exception:
        pass

    return user_id
