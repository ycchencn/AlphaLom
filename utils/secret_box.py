"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

对称加解密工具：把「需要回读明文」的凭据（各平台 LLM API Key）加密后落库。

为什么不直接存明文 / 不止存哈希：
  - 哈希不可逆，无法回填给上游 SDK 调用（api_key 必须原样发出）；
  - 明文落库 = 任何拿到数据库读权限（备份、误配的只读账号、SQL 注入）的人直接
    拿到可用凭据，且日志/导出里可能出现。加密存储把「库被读走」的损失上限降到
    「还必须再拿到 SECRET_KEY」。

密钥来源（env: ALPHALOM_SECRET_KEY，退回 SECRET_KEY）：
  - **必须显式配置**。缺失时不静默降级成明文，也不现场随机生成（随机生成会导致
    重启后全部解不开，且多 worker 之间不一致 —— 那是比明文更糟的故障形态）。
    加密时才抛错，解密时返回 None（读侧按「没配 key」处理，不让设置页崩掉）。

密文格式（自描述，便于以后换算法）：
  v1:<base64(fernet_token)>
  其中 Fernet 内部已带「版本(1B) + 时间戳(8B) + IV + 密文 + HMAC」，随机 IV 保证
  同一明文每次加密结果不同（可以安全地做去重比较之外的一切事）。

密钥派生：env 里给的任意字符串 → sha256 摘要 → urlsafe_b64encode 成 32 字节 Fernet key。
  这样用户随便写一段口令即可，不必自己生成合法 Fernet key。
"""

import base64
import hashlib
import os
from typing import Optional

from utils.logger import logger

# 密文前缀：v1 表示 sha256(口令) 派生的 Fernet。将来换算法时新前缀并存，旧数据仍可解。
_PREFIX = 'v1:'

# 取密钥的环境变量名，按优先级尝试
_ENV_NAMES = ('ALPHALOM_SECRET_KEY', 'SECRET_KEY')

# 主密钥不存在时是否只告警一次（避免每次解密都刷屏）
_warned = False


def _raw_secret() -> Optional[str]:
    """从环境变量里取主密钥；未配置返回 None。"""
    for name in _ENV_NAMES:
        value = (os.getenv(name) or '').strip()
        if value:
            return value
    return None


def is_configured() -> bool:
    """主密钥是否已配置（设置页据此提示「能不能保存 key」）。"""
    return _raw_secret() is not None


def _fernet():
    """构造 Fernet 实例；主密钥缺失时抛 RuntimeError（调用方决定是抛还是降级）。"""
    global _warned
    secret = _raw_secret()
    if not secret:
        if not _warned:
            logger.warning(
                f'未配置 {" / ".join(_ENV_NAMES)}，平台 API Key 无法加密存储；'
                '请在 .env 里设置一段随机口令后重启服务。'
            )
            _warned = True
        raise RuntimeError('未配置加解密主密钥（ALPHALOM_SECRET_KEY）')

    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """
    加密明文，返回可直接落库的字符串。空值原样返回空串（便于「不填就是不设」）。
    :raises RuntimeError: 主密钥未配置
    """
    if plaintext is None:
        return ''
    plaintext = str(plaintext)
    if not plaintext:
        return ''
    token = _fernet().encrypt(plaintext.encode('utf-8'))
    return _PREFIX + token.decode('ascii')


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """
    解密。任何异常（无密钥 / 格式不对 / 密钥换过）都返回 None，绝不上抛 ——
    配置读侧统一按「该平台未配置 key」处理，不能因为一行坏数据把接口打挂。
    """
    if not ciphertext or not isinstance(ciphertext, str):
        return None
    if not ciphertext.startswith(_PREFIX):
        # 兼容历史误写的明文行：直接当明文返回会误导（看着像能用），
        # 但静默丢弃又会让用户困惑。这里返回 None 并告警，让上层明确报「未配置 key」。
        logger.warning('secret_box.decrypt 收到非 v1 前缀的值，已忽略（可能历史写入了明文）')
        return None
    try:
        token = ciphertext[len(_PREFIX):].encode('ascii')
        return _fernet().decrypt(token).decode('utf-8')
    except Exception as e:
        logger.warning(f'secret_box.decrypt 失败（密钥可能已更换）：{e}')
        return None


def mask(plaintext: Optional[str], head: int = 4, tail: int = 4) -> str:
    """
    掩码展示：只保留头尾各几个字符，中间用 * 替代。供设置页回显用，
    **不返回明文**。空值返回空串（前端显示「未配置」）。
    """
    if not plaintext:
        return ''
    s = str(plaintext)
    if len(s) <= head + tail:
        # 太短就别透出内容了，长度也一并隐去
        return '*' * 8
    return f'{s[:head]}{"*" * 8}{s[-tail:]}'
