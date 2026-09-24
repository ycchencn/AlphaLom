"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import LlmAgent
from models.database import db_session
from utils.logger import logger


class AgentService:
    """智能体（LlmAgent）CRUD 服务层。

    每个用户独立管理自己的智能体，越权查询一律返回 None / 空列表。
    """

    # ---------- 读 ----------

    @staticmethod
    def list_agents(user_id: int) -> List[Dict[str, Any]]:
        """列出某用户的全部智能体，按 id 升序排列。"""
        try:
            rows = (db_session.query(LlmAgent)
                    .filter(LlmAgent.user_id == user_id)
                    .order_by(LlmAgent.id)
                    .all())
            return [r.to_dict() for r in rows]
        except SQLAlchemyError as e:
            logger.error(f"list agents user_id={user_id} failed: {e}")
            return []

    @staticmethod
    def get_agent(agent_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """按 id 取单个智能体，带 user_id 隔离（防越权）。不存在或越权返回 None。"""
        try:
            row = (db_session.query(LlmAgent)
                   .filter(LlmAgent.id == agent_id, LlmAgent.user_id == user_id)
                   .first())
            return row.to_dict() if row else None
        except SQLAlchemyError as e:
            logger.error(f"get agent id={agent_id} user_id={user_id} failed: {e}")
            return None

    # ---------- 写 ----------

    @staticmethod
    def create_agent(
        user_id: int,
        name: str,
        emoji: str,
        platform: str,
        model: str,
        system_prompt: str,
    ) -> Optional[int]:
        """
        新建一个智能体。成功返回新 agent 的 id；失败记录日志并返回 None。
        name 在同用户下必须唯一（DB 唯一约束兜底）。
        """
        agent = LlmAgent(
            user_id=user_id,
            name=name,
            emoji=(emoji or '🤖'),
            platform=(platform or '').strip(),
            model=(model or '').strip(),
            system_prompt=(system_prompt or ''),
        )
        try:
            db_session.add(agent)
            db_session.commit()
            db_session.refresh(agent)
            return agent.id
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"create agent duplicate name: user_id={user_id}, name={name!r}")
            return None
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"create agent user_id={user_id} failed: {e}")
            return None

    @staticmethod
    def update_agent(
        agent_id: int,
        user_id: int,
        payload: Dict[str, Any],
    ) -> bool:
        """
        更新某个智能体的字段（仅允许 name/emoji/platform/model/system_prompt）。
        先查一下 user_id 过滤，越权不修改。
        """
        allowed_keys = {'name', 'emoji', 'platform', 'model', 'system_prompt'}
        updates = {k: v for k, v in payload.items() if k in allowed_keys and v is not None}
        if not updates:
            return False

        try:
            row = (db_session.query(LlmAgent)
                   .filter(LlmAgent.id == agent_id, LlmAgent.user_id == user_id)
                   .first())
            if row is None:
                return False
            for k, v in updates.items():
                setattr(row, k, v)
            db_session.commit()
            db_session.refresh(row)
            return True
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"update agent duplicate name: agent_id={agent_id}, name={updates.get('name')!r}")
            return False
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"update agent id={agent_id} user_id={user_id} failed: {e}")
            return False

    @staticmethod
    def delete_agent(agent_id: int, user_id: int) -> bool:
        """
        删除某个智能体。返回 True 表示已删、False 表示没找到（幂等安全）。
        会话历史在 Redis 中自动过期（session key 由前端生成），无需显式清理。
        """
        try:
            row = (db_session.query(LlmAgent)
                   .filter(LlmAgent.id == agent_id, LlmAgent.user_id == user_id)
                   .first())
            if row is None:
                return False
            db_session.delete(row)
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"delete agent id={agent_id} user_id={user_id} failed: {e}")
            return False
