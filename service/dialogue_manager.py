"""
@author Yc
Chaos isn't a pit. Chaos is a ladder. - Littlefinger
Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
from datetime import datetime
from service.llm_conversation_context import LlmConversationContextService
from utils.logger import logger


class DialogueManager:
    """
    @brief 对话上下文闭环管理器

    @details 负责对话上下文的读取、追加、写入，以及 token 控制。
    """

    @staticmethod
    def get_context(chat_id: str) -> list:
        """
        @brief 从数据库获取完整的消息列表

        @param chat_id: 会话唯一ID
        @type chat_id: str

        @return: 消息列表（空列表表示无历史）
        @rtype: list
        """
        record = LlmConversationContextService.get_by_chat_id(chat_id)
        if record and record.get('chat_context'):
            try:
                return json.loads(record['chat_context'])
            except (json.JSONDecodeError, TypeError):
                logger.error(f"chat_id {chat_id} 的 chat_context 格式无效，已重置")
        return []  # 首次对话或数据异常时返回空列表

    @staticmethod
    def append_messages(chat_id: str, new_messages: list, max_tokens: int = 4096):
        """
        @brief 将新消息追加到上下文并保存到数据库

        @param chat_id: 会话唯一ID
        @type chat_id: str
        @param new_messages: 要追加的消息列表（通常为[user_msg, assistant_msg]）
        @type new_messages: list
        @param max_tokens: 上下文最大 token 数（超过则截断）
        @type max_tokens: int

        @return: 是否更新成功
        @rtype: bool
        """
        # 1. 获取现有上下文
        messages = DialogueManager.get_context(chat_id)

        # 2. 追加新消息
        messages.extend(new_messages)

        # 3. 控制上下文长度（滑动窗口 + 保留system消息）
        # messages = DialogueManager._truncate_context(messages, max_tokens)

        # 4. 序列化
        context_str = json.dumps(messages, ensure_ascii=False)

        # 5. 更新或创建数据库记录
        record = LlmConversationContextService.get_by_chat_id(chat_id)
        if record:
            # 已有记录，更新
            return LlmConversationContextService.update(
                id=record['id'],
                update_data={
                    'chat_context': context_str,
                    'updated_at': datetime.utcnow()
                }
            )
        else:
            # 首次创建
            return LlmConversationContextService.create({
                'chat_id': chat_id,
                'chat_context': context_str,
            })

    @staticmethod
    def _truncate_context(messages: list, max_tokens: int) -> list:
        """
        @brief 根据 token 数限制进行截断（保留 system 消息和最近的消息）

        @param messages: 完整消息列表
        @type messages: list
        @param max_tokens: 允许的最大 token 数
        @type max_tokens: int

        @return: 截断后的消息列表
        @rtype: list
        """
        # 简易实现：按字符数估算（实际生产需用 tokenizer）
        # 假设平均每个中文字符占 2 token，英文占 1 token
        total_chars = sum(len(msg.get('content', '')) for msg in messages)
        estimated_tokens = total_chars * 2  # 粗略估算

        if estimated_tokens <= max_tokens:
            return messages

        # 需要截断：保留 system 消息，然后从后往前保留
        system_messages = [msg for msg in messages if msg.get('role') == 'system']
        other_messages = [msg for msg in messages if msg.get('role') != 'system']

        # 从后往前保留，直到接近 max_tokens
        truncated = []
        current_tokens = sum(len(msg.get('content', '')) * 2 for msg in system_messages)
        # 预先加上 system 的 token
        for msg in reversed(other_messages):
            msg_tokens = len(msg.get('content', '')) * 2
            if current_tokens + msg_tokens <= max_tokens:
                truncated.insert(0, msg)  # 保持原始顺序
                current_tokens += msg_tokens
            else:
                break

        return system_messages + truncated
