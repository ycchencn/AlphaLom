"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import os
import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from models import User
from models.database import db_session
from config import auth_setting
from utils.logger import logger
from utils.redis_obj import redis_obj

# 默认管理员账号（仅在 users 表为空时自动创建），可通过环境变量覆盖
DEFAULT_ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
DEFAULT_ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123456')


class UserService:

    # ---------- 基础 CRUD ----------

    @staticmethod
    def add(user_data: dict):
        """
        新增用户。若 provider 未提供 password_hash，则对明文 password 做哈希。
        :param user_data: 含 username/password(明文) 或 password_hash 的字典
        :return: 成功返回新用户 dict，失败返回 None
        """
        try:
            data = dict(user_data)
            plain_pwd = data.pop('password', None)
            if 'email' in data:
                data['email'] = UserService.normalize_email(data['email'])
            if 'password_hash' not in data and plain_pwd:
                data['password_hash'] = generate_password_hash(plain_pwd)
            user = User(**data)
            db_session.add(user)
            db_session.commit()
            return user.to_dict()
        except Exception as e:
            db_session.rollback()
            logger.error(f"创建用户失败: {e}")
            return None

    @staticmethod
    def get_by_username(username: str):
        """按用户名查用户，返回 ORM 对象（内部用，含 password_hash）"""
        try:
            return db_session.query(User).filter_by(username=username).first()
        except Exception as e:
            logger.error(f"查询用户失败: {e}")
            return None

    @staticmethod
    def normalize_email(email):
        """
        邮箱归一化：去空格 + 转小写；空值统一成 None。

        ⚠️ 两个必须做的理由：
          1. `users.email` 是 utf8mb4_bin（**区分大小写**）→ 存 'A@x.com' 用
             'a@x.com' 查不到。邮箱大小写不敏感，只能靠写入时就统一小写。
          2. 唯一索引下**多个空串会被判成重复**，而「不填邮箱」是正常的 ——
             所以空值一律写 NULL（MySQL 唯一索引允许多个 NULL）。
        """
        if email is None:
            return None
        email = str(email).strip().lower()
        return email or None

    @staticmethod
    def get_by_email(email):
        """按邮箱查用户（大小写不敏感）。返回列表 —— 唯一索引是后加的，历史数据可能重复。"""
        normalized = UserService.normalize_email(email)
        if not normalized:
            return []
        try:
            return db_session.query(User).filter_by(email=normalized).all()
        except Exception as e:
            logger.error(f"按邮箱查询用户失败: {e}")
            return []

    @staticmethod
    def email_exists(email, exclude_user_id=None) -> bool:
        """
        邮箱是否已被别的账号占用（建号/改号的前置校验，避免撞唯一索引变成 500）。
        :param exclude_user_id: 改号时排除自己
        """
        normalized = UserService.normalize_email(email)
        if not normalized:
            return False
        try:
            query = db_session.query(User).filter_by(email=normalized)
            if exclude_user_id is not None:
                query = query.filter(User.id != int(exclude_user_id))
            return bool(db_session.query(query.exists()).scalar())
        except Exception as e:
            logger.error(f"检查邮箱占用失败: {e}")
            return False

    @staticmethod
    def find_by_identifier(identifier: str):
        """
        登录入口的账号查找：**先当用户名，再当邮箱**。

        用户名唯一且优先，所以「某人的邮箱恰好等于另一人的用户名」时按用户名走，
        符合直觉。邮箱只在用户名没命中时才尝试。

        ⚠️ 邮箱命中多个账号时必须**拒绝登录**，不能取第一条：历史数据里可能存在
        重复邮箱（唯一索引是后加的），静默取第一条会让人「输入自己的邮箱、登录进
        别人的账号」——这是最坏的一种失败方式。
        :return: 命中且无歧义时返回 ORM 对象，否则 None
        """
        identifier = (identifier or '').strip()
        if not identifier:
            return None
        user = UserService.get_by_username(identifier)
        if user:
            return user
        matched = UserService.get_by_email(identifier)
        if len(matched) > 1:
            logger.warning(f"邮箱 {identifier} 对应 {len(matched)} 个账号，已拒绝邮箱登录（请改用用户名）")
            return None
        return matched[0] if matched else None

    @staticmethod
    def get_by_id(user_id):
        try:
            user = db_session.query(User).filter_by(id=user_id).first()
            return user.to_dict() if user else None
        except Exception as e:
            logger.error(f"查询用户失败: {e}")
            return None

    @staticmethod
    def get_all():
        try:
            return [u.to_dict() for u in db_session.query(User).all()]
        except Exception as e:
            logger.error(f"查询用户列表失败: {e}")
            return []

    @staticmethod
    def update(user_id, update_data: dict):
        """
        部分更新用户。若含明文 password 则重新哈希后写入 password_hash。
        """
        try:
            user = db_session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            data = dict(update_data)
            plain_pwd = data.pop('password', None)
            if 'email' in data:
                data['email'] = UserService.normalize_email(data['email'])
            if plain_pwd:
                data['password_hash'] = generate_password_hash(plain_pwd)
            for key, value in data.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"更新用户失败: {e}")
            return False

    @staticmethod
    def delete(user_id):
        try:
            user = db_session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            db_session.delete(user)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"删除用户失败: {e}")
            return False

    # ---------- 认证 ----------

    @staticmethod
    def authenticate(identifier: str, password: str):
        """
        校验账号/密码。`identifier` 既可以是用户名，也可以是邮箱（大小写不敏感）。

        ⚠️ 参数语义从「用户名」放宽成「用户名或邮箱」，所以日志里记的是
        `user.username` 而不是用户输入 —— 否则日志里会出现一堆邮箱，排查时
        对不上 users 表。
        :return: 成功返回用户 dict；失败返回 None
        """
        user = UserService.find_by_identifier(identifier)
        if not user:
            return None
        if not user.is_active:
            logger.warning(f"账号 {user.username} 已被禁用")
            return None
        if check_password_hash(user.password_hash, password):
            # 更新最后登录时间
            try:
                user.last_login_at = datetime.now()
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                logger.error(f"更新最后登录时间失败: {e}")
            return user.to_dict()
        return None

    # ---------- 登录令牌（Redis）----------
    # 多用户隔离的前提：后端必须能从请求还原「当前用户」。这里把 token 作为键写进
    # Redis、值是 user_id，校验时反查；登出/禁用/改密直接删键即刻生效。
    # ⚠️ 不要退回「只返回随机串、不落库」的写法 —— 那种 token 无法校验，
    # 等于后端没有鉴权，任何人不带凭证也能读写所有人的数据。

    @staticmethod
    def _token_key(token: str) -> str:
        return f"{auth_setting['token_prefix']}{token}"

    @staticmethod
    def _as_text(value):
        """Redis（decode_responses=False）取回来的是 bytes，统一转成 str 再比较"""
        if isinstance(value, (bytes, bytearray)):
            return value.decode('utf-8', errors='ignore')
        return value

    @staticmethod
    def issue_token(user_id):
        """
        为指定用户签发登录令牌（写入 Redis）。

        :return: 成功返回 token 字符串；Redis 不可用返回 None。
                 注意不能「失败也发号」—— 那样会发给前端一个永远校验不过的 token，
                 用户会卡在「登录成功但每个页面都报未登录」，还不如直接报错。
        """
        token = uuid.uuid4().hex
        try:
            redis_obj.set(UserService._token_key(token), str(int(user_id)),
                          ex=auth_setting['token_ttl'])
            return token
        except Exception as e:
            logger.error(f"签发登录令牌失败（Redis 不可用？）: {e}")
            return None

    @staticmethod
    def resolve_token(token: str):
        """
        校验登录令牌，返回对应用户 dict（不含 password_hash）；无效一律返回 None。

        无效的三种情况都能覆盖：token 不存在/已过期（Redis 无此键）、Redis 不可用、
        用户已被删除或禁用（此时顺手把令牌删掉，不让它继续挂着）。
        校验通过会续期一次（滑动过期）。
        """
        if not token:
            return None
        try:
            raw = redis_obj.get(UserService._token_key(token))
        except Exception as e:
            logger.error(f"校验登录令牌失败（Redis 不可用？）: {e}")
            return None
        if raw is None:
            return None
        try:
            user_id = int(UserService._as_text(raw))
        except (TypeError, ValueError):
            logger.warning(f"登录令牌的值不是合法 user_id: {raw!r}")
            return None

        user = UserService.get_by_id(user_id)
        if not user or not user.get('is_active'):
            UserService.revoke_token(token)
            return None

        try:
            redis_obj.expire(UserService._token_key(token), auth_setting['token_ttl'])
        except Exception:
            # 续期失败不影响本次校验结果（令牌仍在有效期内）
            pass
        return user

    @staticmethod
    def revoke_token(token: str) -> bool:
        """登出：删除该令牌。令牌本来就不存在也返回 False，不视为错误。"""
        if not token:
            return False
        try:
            return bool(redis_obj.delete(UserService._token_key(token)))
        except Exception as e:
            logger.error(f"注销登录令牌失败: {e}")
            return False

    @staticmethod
    def revoke_all_tokens(user_id) -> int:
        """
        让某个用户的全部登录令牌立即失效（禁用账号 / 改密码时调用）。
        按前缀 SCAN 后逐个比对值，不用 KEYS 以免阻塞 Redis。
        :return: 删掉的令牌个数
        """
        prefix = auth_setting['token_prefix']
        target = str(int(user_id))
        removed = 0
        try:
            for key in redis_obj.scan_iter(match=f'{prefix}*', count=500):
                if UserService._as_text(redis_obj.get(key)) == target:
                    removed += redis_obj.delete(key)
        except Exception as e:
            logger.error(f"清理用户 {user_id} 的登录令牌失败: {e}")
        return removed

    # ---------- 初始化 ----------

    @staticmethod
    def count():
        try:
            return db_session.query(User).count()
        except Exception as e:
            logger.error(f"统计用户失败: {e}")
            return -1

    @staticmethod
    def create_user_if_not_exists(username=DEFAULT_ADMIN_USERNAME, password=DEFAULT_ADMIN_PASSWORD,
                                  role='admin', nickname='管理员'):
        """
        用户不存在时创建（默认创建管理员，首次安装时自动调用）。
        已存在同用户名时不重复创建。
        :param username: 用户名
        :param password: 明文密码（内部会哈希）
        :param role: 角色，默认 admin
        :param nickname: 昵称，默认「管理员」
        """
        try:
            existing = UserService.get_by_username(username)
            if existing:
                return False
            password_hash = generate_password_hash(password)
            db_session.add(User(
                username=username,
                password_hash=password_hash,
                nickname=nickname,
                role=role,
                is_active=1,
            ))
            db_session.commit()
            logger.info(f"已创建用户账号：{username}（role={role}）")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"创建用户失败: {e}")
            return False