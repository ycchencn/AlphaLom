"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_
from models import LlmPrompt
from models.database import db_session
from utils.logger import logger

class LlmPromptService:

    @staticmethod
    def add(prompt_data):
        """
        添加一条 Prompt 记录
        :param prompt_data: dict, 包含 prompt_key, name, content 等字段
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            prompt = LlmPrompt(**prompt_data)
            db_session.add(prompt)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def batch_add(prompt_list):
        """
        批量添加 Prompt 记录
        :param prompt_list: list, 每项为包含 prompt 数据的 dict
        :return: bool, 成功返回 True，失败返回 False
        """
        if not prompt_list:
            return True

        try:
            db_session.bulk_insert_mappings(LlmPrompt, prompt_list)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch insertion failed due to integrity error: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error during batch insertion: {e}")
            return False

    @staticmethod
    def get_by_key(prompt_key: str, is_active: bool = True):
        """
        根据 prompt_key 获取最新版本的 Prompt（默认只查启用的）
        :param prompt_key: str, Prompt 的唯一标识
        :param is_active: bool, 是否只查启用的记录
        :return: LlmPrompt or None
        """
        try:
            query = db_session.query(LlmPrompt).filter(LlmPrompt.prompt_key == prompt_key)
            if is_active:
                query = query.filter(LlmPrompt.is_active == True)
            return query.order_by(LlmPrompt.version.desc()).first()
        except Exception as e:
            logger.error(f"Error fetching prompt by key '{prompt_key}': {e}")
            return None

    @staticmethod
    def update_by_key(prompt_key: str, update_data: dict):
        """
        根据 prompt_key 更新记录（默认更新最新版本，若需指定版本可扩展）
        :param prompt_key: str, Prompt 的唯一标识
        :param update_data: dict, 要更新的字段
        :return: bool, 成功返回 True，失败返回 False
        """
        try:
            # 先获取最新版本的记录
            latest_prompt = db_session.query(LlmPrompt).filter(
                LlmPrompt.prompt_key == prompt_key
            ).order_by(LlmPrompt.version.desc()).first()

            if not latest_prompt:
                logger.warning(f"Prompt with key '{prompt_key}' not found for update.")
                return False

            # 更新字段
            for key, value in update_data.items():
                if hasattr(LlmPrompt, key):
                    setattr(latest_prompt, key, value)

            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed due to integrity error: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred during update: {e}")
        return False

    @staticmethod
    def get_all_active():
        """
        获取所有启用的 Prompt
        :return: list of LlmPrompt
        """
        try:
            return db_session.query(LlmPrompt).filter(LlmPrompt.is_active == True).all()
        except Exception as e:
            logger.error(f"Error fetching all active prompts: {e}")
            return []

    @staticmethod
    def get_versions_by_key(prompt_key: str):
        """
        获取指定 prompt_key 的所有历史版本
        :param prompt_key: str
        :return: list of LlmPrompt
        """
        try:
            return db_session.query(LlmPrompt).filter(
                LlmPrompt.prompt_key == prompt_key
            ).order_by(LlmPrompt.version.desc()).all()
        except Exception as e:
            logger.error(f"Error fetching versions for prompt key '{prompt_key}': {e}")
            return []
