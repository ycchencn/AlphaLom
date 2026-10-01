"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ALTCHA 人机校验（自托管开源版）。

协议细节全部以 `altcha` 库源码为准（v2：camelCase 字段、HMAC-SHA256 签名 canonical
JSON、解 = 让 KDF 派生密钥以 keyPrefix 开头）。**绝不自己重写签名序列化** ——
canonical JSON 的排序+去 None+紧凑分隔符任一处理不同，签名就对不上。

开源版相比官方云版（Sentinel）缺一件事，必须自己补：
  v2 的 payload 是**自证**的（签名保护参数、解可被重算验证），服务端零存储即可验真，
  代价是 **同一份解可无限次重放**。不补「一次性」，就退化成「解一次题、试一万次密码」，
  撞库完全不受阻 —— 加了校验但攻击成本没变。所以每次校验成功都消费掉该题的 nonce。

fail-open / fail-closed 取舍：
  - 一次性标记写不进 Redis（抖动）→ **放行** + WARNING。保护性能力，把登录打死
    比漏挡几次更糟。
  - 缺 HMAC 密钥 / 库没装 → **503 拒绝** + 明确文案。配置问题应显式暴露，
    绝不静默降级成「不校验」（那等于给攻击者一个「搞坏配置就绕过」的开关）。
"""

import hashlib
import hmac as _hmac
import os
from datetime import datetime, timedelta, timezone

from altcha.v2 import (
    Challenge,
    Payload,
    create_challenge,
    verify_solution,
)

from config import altcha_setting
from utils.logger import logger
from utils.redis_obj import redis_obj

# 以下常量仅用于「前端展示 / 排错」，签名与判定一律交给库
ALGORITHM = altcha_setting['algorithm']
KEY_PREFIX = altcha_setting['key_prefix']
COST = altcha_setting['cost']
TTL = altcha_setting['ttl']
USED_PREFIX = altcha_setting['used_prefix']

# 是否整体启用登录人机校验。dev 默认关闭（见 config.altcha_setting['enabled']），
# 可用 ALTCHA_ENABLED 显式覆盖。路由层据此跳过出题与校验。
ENABLED = bool(altcha_setting.get('enabled', True))


def is_enabled() -> bool:
    """是否启用登录人机校验。

    返回 False（如 dev 环境 / 显式 ALTCHA_ENABLED=false）时，路由层必须**整段跳过**
    出题与校验——既不要求前端解题，后端也不验 payload。这与「配置缺失 → 503
    拒绝」是两回事：禁用是明确的策略选择，不是故障。
    """
    return ENABLED


class AltchaNotConfigured(RuntimeError):
    """HMAC 密钥既没有显式配置、也无法从既有密钥派生 —— 属于致命配置问题。

    调用方应据此返回 503（而不是放行）。"""
    pass


# ---------------------------------------------------------------------------
# HMAC 密钥
# ---------------------------------------------------------------------------

def _derive_key() -> str:
    """按优先级取 HMAC 密钥：显式配置 → 从数据库连接串派生。

    ⚠️ 派生源必须是**多进程稳定**的既有配置。绝不用 `secrets`/随机值：多 worker 下
    会变成「请求落到别的 worker 就验不过」，表现为随机登录失败，极难定位。
    """
    explicit = (altcha_setting['hmac_key'] or '').strip()
    if explicit:
        return explicit

    source = (os.getenv('DATABASE_CONN_STR') or '').strip()
    if source:
        # 派生值带项目前缀，避免与其它用途共用同一串
        return hashlib.sha256(f'alphalom::altcha::{source}'.encode()).hexdigest()

    raise AltchaNotConfigured(
        '缺少 ALTCHA_HMAC_KEY，且 DATABASE_CONN_STR 为空无法派生；'
        '请在 .env 配置 ALTCHA_HMAC_KEY 后重启'
    )


def is_configured() -> bool:
    """能否拿到可用的 HMAC 密钥。False 时调用方必须 503，不得放行。"""
    try:
        _derive_key()
        return True
    except AltchaNotConfigured:
        return False


# ---------------------------------------------------------------------------
# 一次性标记（防重放）
# ---------------------------------------------------------------------------

def _used_key(nonce: str) -> str:
    return f'{USED_PREFIX}{nonce}'


def _consume(nonce: str) -> bool:
    """把这道题的 nonce 标记为已用；已经被用过返回 False。

    Redis 抖动时 **fail-open 返回 True**（放行）—— 见模块头部的取舍说明。
    """
    try:
        return bool(redis_obj.set(_used_key(nonce), 1, nx=True, ex=TTL))
    except Exception:
        logger.warning('ALTCHA 一次性标记写入失败，本次放行（fail-open）', exc_info=True)
        return True


# ---------------------------------------------------------------------------
# 出题
# ---------------------------------------------------------------------------

def create() -> dict:
    """生成一道新题（带签名）。

    `expires_at` 写进参数并受签名保护，所以客户端改不了有效期；
    校验端由库按该字段判定过期。
    """
    secret = _derive_key()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TTL)
    challenge: Challenge = create_challenge(
        algorithm=ALGORITHM,
        cost=COST,
        key_prefix=KEY_PREFIX,
        expires_at=expires_at,
        hmac_secret=secret,
    )
    return challenge.to_dict()


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def verify(payload: str) -> tuple[bool, str]:
    """校验前端提交的 payload。返回 (是否通过, 失败原因)。

    判定顺序：库校验（过期 / 签名 / 解）→ 一次性标记。
    ⚠️ 必须**先**验库再消费标记：否则一个非法 payload 也能把某道题的 nonce 用掉。
    """
    if not payload or not isinstance(payload, str):
        return False, '请先完成人机验证'

    try:
        secret = _derive_key()
    except AltchaNotConfigured as e:
        # 这里向上抛，由路由转成 503 —— 配置问题绝不降级成放行
        raise

    try:
        result = verify_solution(payload, secret)
    except Exception:
        logger.warning('ALTCHA payload 解析失败', exc_info=True)
        return False, '人机验证无效，请重试'

    # 库把「payload 根本不是合法 base64/JSON」也表达成 verified=False（附 error 文案），
    # 而不是抛异常 —— 显式挡掉，避免落到下面拿 invalid_signature/invalid_solution 判断
    # 时语义含糊（两者此时都是 None）。
    if result.error:
        return False, '人机验证无效，请重试'

    if result.expired:
        return False, '人机验证已过期，请重试'
    if result.invalid_signature:
        return False, '人机验证无效，请重试'
    if result.invalid_solution:
        return False, '人机验证未通过，请重试'

    # 库已验真 → 消费一次性名额
    try:
        nonce = Payload.from_base64(payload).challenge.parameters.nonce
    except Exception:
        logger.warning('ALTCHA payload 解析 nonce 失败', exc_info=True)
        return False, '人机验证无效，请重试'

    if not _consume(nonce):
        return False, '人机验证已使用过，请重新验证'

    return True, ''
