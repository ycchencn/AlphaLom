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
from utils.logger import logger

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
    def authenticate(username: str, password: str):
        """
        校验用户名/密码。
        :return: 成功返回用户 dict；失败返回 None
        """
        user = UserService.get_by_username(username)
        if not user:
            return None
        if not user.is_active:
            logger.warning(f"账号 {username} 已被禁用")
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

    @staticmethod
    def generate_token(username: str):
        """生成登录 token（UUID4 随机串，替代原硬编码占位符）"""
        return uuid.uuid4().hex

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