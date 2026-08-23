"""
@author Yc
Chaos isn't a pit. Chaos is a ladder. - Littlefinger
Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import SQLAlchemyError
from models import LlmConversationContext
from models.database import db_session
from utils.logger import logger
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import desc, asc


class LlmConversationContextService:

    # ==================== 读取类方法 ====================

    @staticmethod
    def get_by_id(id: int) -> Optional[Dict[str, Any]]:
        """
        根据主键 ID 获取一条对话上下文记录

        Args:
            id: 记录主键

        Returns:
            字典格式的记录，如果不存在则返回 None
        """
        record = db_session.query(LlmConversationContext).get(id)
        return record.to_dict() if record else None

    @staticmethod
    def get_by_chat_id(chat_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 chat_id 获取第一条匹配的对话上下文（通常 chat_id 唯一，否则返回最新的记录）

        Args:
            chat_id: 对话 ID

        Returns:
            字典格式的记录，如果不存在则返回 None
        """
        record = (
            db_session.query(LlmConversationContext)
            .filter_by(chat_id=chat_id)
            .order_by(LlmConversationContext.created_at.desc())
            .first()
        )
        return record.to_dict() if record else None

    @staticmethod
    def get_all(
            page: int = 1,
            per_page: int = 50,
            order_by: str = "created_at",
            order_direction: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        获取所有对话上下文记录，支持分页和排序

        Args:
            page: 页码（从1开始）
            per_page: 每页数量
            order_by: 排序字段，默认 created_at
            order_direction: 排序方向，'asc' 或 'desc'，默认 desc

        Returns:
            记录字典列表
        """
        query = db_session.query(LlmConversationContext)

        # 排序
        if hasattr(LlmConversationContext, order_by):
            sort_column = getattr(LlmConversationContext, order_by)
            if order_direction.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        offset = (page - 1) * per_page
        records = query.offset(offset).limit(per_page).all()
        return [record.to_dict() for record in records]

    @staticmethod
    def search(
            chat_id: Optional[str] = None,
            page: int = 1,
            per_page: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        根据 chat_id 精确或模糊查询（此处实现精确查询，如需模糊可改）

        Args:
            chat_id: 对话 ID（精确匹配）
            page: 页码
            per_page: 每页数量

        Returns:
            记录字典列表
        """
        query = db_session.query(LlmConversationContext)
        if chat_id:
            query = query.filter(LlmConversationContext.chat_id == chat_id)

        offset = (page - 1) * per_page
        records = query.offset(offset).limit(per_page).all()
        return [record.to_dict() for record in records]

    @staticmethod
    def count() -> int:
        """返回对话上下文总记录数"""
        from sqlalchemy import func
        return db_session.query(func.count(LlmConversationContext.id)).scalar()

    @staticmethod
    def exists(chat_id: str) -> bool:
        """判断指定 chat_id 的记录是否已存在"""
        return (
                db_session.query(LlmConversationContext)
                .filter_by(chat_id=chat_id)
                .first()
                is not None
        )

    # ==================== 写入类方法 ====================

    @staticmethod
    def create(context_data: Dict[str, Any]) -> bool:
        """
        新增一条对话上下文，自动设置 created_at 和 updated_at

        Args:
            context_data: 包含 chat_id, chat_context 等字段的字典

        Returns:
            成功返回 True，失败返回 False
        """
        try:
            now = datetime.utcnow()
            context_data.setdefault("created_at", now)
            context_data.setdefault("updated_at", now)

            record = LlmConversationContext(**context_data)
            db_session.add(record)
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Failed to create LlmConversationContext: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error in create: {e}")
            return False

    @staticmethod
    def update(id: int, update_data: Dict[str, Any]) -> bool:
        """
        根据主键 ID 更新一条对话上下文，自动刷新 updated_at

        Args:
            id: 记录主键
            update_data: 需要更新的字段字典

        Returns:
            成功返回 True，失败返回 False
        """
        record = db_session.query(LlmConversationContext).get(id)
        if not record:
            logger.warning(f"LlmConversationContext with id {id} not found for update")
            return False

        try:
            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.updated_at = datetime.utcnow()
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Update failed for id {id}: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error in update: {e}")
            return False

    @staticmethod
    def delete(id: int) -> bool:
        """
        根据主键 ID 删除一条对话上下文记录

        Args:
            id: 记录主键

        Returns:
            成功返回 True，失败返回 False
        """
        record = db_session.query(LlmConversationContext).get(id)
        if not record:
            logger.warning(f"LlmConversationContext with id {id} not found for deletion")
            return False

        try:
            db_session.delete(record)
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Deletion failed for id {id}: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error in delete: {e}")
            return False
