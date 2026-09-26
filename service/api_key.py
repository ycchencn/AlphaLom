"""
 * @author Yc
 * API Key 服务：对外 portfolio 接口的密钥管理 + Redis 快速校验索引。
 *
 * 设计要点：
 * - 明文密钥只在 create() 返回一次，落库只存 sha256 摘要（key_hash）。
 * - Redis 存 `api_setting['key_prefix'] + key_hash -> JSON{"u": user_id, "q": daily_quota|null}`，
 *   校验走 Redis；吊销/停用 = 删 Redis 键，下次校验直接 401（fail-closed）。
 * - DB 的 api_key 表是管理视图（列表 / 改名 / 启停 / 吊销）的权威来源。
"""

import hashlib
import json
import secrets
from datetime import datetime

from config import api_setting
from models import ApiKey
from models.database import db_session
from utils.logger import logger
from utils.redis_obj import redis_obj

# 明文前缀：便于在 Swagger / 日志里一眼区分这是「对外 API Key」而非登录令牌
RAW_KEY_PREFIX = 'flp_'
# 列表里展示的前缀长度（flp_ + 8 位随机）
DISPLAY_PREFIX_LEN = 12
# last_used_at 的写入节流：距上次不足 N 秒就跳过，避免每个请求都 UPDATE
LAST_USED_THROTTLE_SECONDS = 60


class ApiKeyService:

    @staticmethod
    def _hash(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    @staticmethod
    def _set_redis(key_hash: str, user_id: int, daily_quota) -> None:
        """把校验索引写进 Redis（含可选 TTL）。失败只记日志，不阻断创建流程。"""
        try:
            payload = json.dumps({'u': int(user_id), 'q': daily_quota}, ensure_ascii=False)
            ttl = int(api_setting.get('key_ttl') or 0)
            key = f"{api_setting['key_prefix']}{key_hash}"
            if ttl > 0:
                redis_obj.set(key, payload, ex=ttl)
            else:
                redis_obj.set(key, payload)
        except Exception as e:
            logger.error(f"写入 API Key Redis 索引失败: {e}")

    @staticmethod
    def _del_redis(key_hash: str) -> None:
        try:
            redis_obj.delete(f"{api_setting['key_prefix']}{key_hash}")
        except Exception as e:
            logger.error(f"删除 API Key Redis 索引失败: {e}")

    @staticmethod
    def create(user_id: int, name: str = 'default', daily_quota=None, expires_at=None):
        """生成一枚新密钥。

        :return: (plaintext_key, record_dict)。plaintext_key 只在这一次返回，务必在响应里交给用户。
        """
        raw = RAW_KEY_PREFIX + secrets.token_urlsafe(32)
        key_hash = ApiKeyService._hash(raw)
        record = ApiKey(
            user_id=int(user_id),
            name=name or 'default',
            key_prefix=raw[:DISPLAY_PREFIX_LEN],
            key_hash=key_hash,
            status='active',
            daily_quota=daily_quota,
            expires_at=expires_at,
            created_at=datetime.now(),
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)
        ApiKeyService._set_redis(key_hash, user_id, daily_quota)
        return raw, record.to_dict_masked()

    @staticmethod
    def list_by_user(user_id: int):
        rows = (
            db_session.query(ApiKey)
            .filter(ApiKey.user_id == int(user_id))
            .order_by(ApiKey.created_at.desc())
            .all()
        )
        return [r.to_dict_masked() for r in rows]

    @staticmethod
    def get_by_id(key_id: int, user_id: int):
        """按 id 取密钥，且必须是该用户自己的（越权返回 None，统一当不存在）。"""
        return (
            db_session.query(ApiKey)
            .filter(ApiKey.id == int(key_id), ApiKey.user_id == int(user_id))
            .first()
        )

    @staticmethod
    def revoke(key_id: int, user_id: int) -> bool:
        record = ApiKeyService.get_by_id(key_id, user_id)
        if not record:
            return False
        record.status = 'revoked'
        db_session.commit()
        ApiKeyService._del_redis(record.key_hash)
        return True

    @staticmethod
    def update(key_id: int, user_id: int, name=None, status=None, daily_quota='__nochange__'):
        """改名 / 启停 / 改配额。daily_quota 传 None 表示显式置空（回退全局默认）。"""
        record = ApiKeyService.get_by_id(key_id, user_id)
        if not record:
            return None
        if name is not None:
            record.name = name
        if status is not None and status in ('active', 'revoked'):
            record.status = status
            if status == 'revoked':
                ApiKeyService._del_redis(record.key_hash)
            else:
                ApiKeyService._set_redis(record.key_hash, record.user_id, record.daily_quota)
        if daily_quota != '__nochange__':
            record.daily_quota = daily_quota
            if record.status == 'active':
                ApiKeyService._set_redis(record.key_hash, record.user_id, daily_quota)
        db_session.commit()
        return record.to_dict_masked()

    @staticmethod
    def touch_last_used(key_hash: str) -> None:
        """节流更新 last_used_at：距上次不足 N 秒则跳过（用 Redis 标记避免每次都 UPDATE）。"""
        try:
            throttle_key = f"{api_setting['key_prefix']}last:{key_hash}"
            if redis_obj.exists(throttle_key):
                return
            redis_obj.set(throttle_key, '1', ex=LAST_USED_THROTTLE_SECONDS)
            record = db_session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
            if record:
                record.last_used_at = datetime.now()
                db_session.commit()
        except Exception as e:
            logger.warning(f"更新 API Key last_used_at 失败（可忽略）: {e}")
