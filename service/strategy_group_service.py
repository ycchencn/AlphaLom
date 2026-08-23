"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models.database import db_session  # 假设这是你的数据库会话
from sqlalchemy.exc import IntegrityError
from models import StrategyGroup
from utils.logger import logger

class StrategyGroupService:
    @staticmethod
    def add_group(group_data):
        try:
            new_group = StrategyGroup(**group_data)
            db_session.add(new_group)
            db_session.commit()
            return new_group.to_dict()
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"StrategyGroup添加失败: {e}")
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f"发生错误: {e}")
            return None

    @staticmethod
    def get_all_groups():
        try:
            groups = db_session.query(StrategyGroup).all()
            return [group.to_dict() for group in groups]
        except Exception as e:
            logger.error(f"查询所有策略组失败: {e}")
            return []

    @staticmethod
    def get_group_by_id(group_id):
        try:
            group = db_session.query(StrategyGroup).filter_by(group_id=group_id).first()
            return group.to_dict() if group else None
        except Exception as e:
            logger.error(f"根据ID {group_id} 查询策略组失败: {e}")
            return None

    @staticmethod
    def update_group(group_id, update_data):
        try:
            group = db_session.query(StrategyGroup).filter_by(group_id=group_id).first()
            if not group:
                return None
            group.group_name = update_data.get('group_name', group.group_name)
            db_session.commit()
            return group.to_dict()
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"更新策略组 {group_id} 失败: {e}")
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f"更新策略组时发生错误: {e}")
            return None

    @staticmethod
    def delete_group(group_id):
        try:
            group = db_session.query(StrategyGroup).filter_by(group_id=group_id).first()
            if not group:
                return False
            db_session.delete(group)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"删除策略组 {group_id} 失败: {e}")
            return False
