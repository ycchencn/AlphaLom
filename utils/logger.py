"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
import logging
import os
from datetime import datetime


class RedisHandler(logging.Handler):
    """将日志写入 Redis List 的自定义 Handler"""

    def __init__(self, redis_client, key='app:logs', max_len=50000):
        super().__init__()
        self.redis = redis_client
        self.key = key
        self.max_len = max_len

    def emit(self, record):
        try:
            # 格式化日志为 dict
            log_entry = {
                'timestamp': datetime.utcfromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': self.format(record),
                'module': record.module,
                'func': record.funcName,
                'line': record.lineno,
            }

            # LPUSH 到 Redis List，同时用 LTRIM 控制长度防止爆内存
            pipe = self.redis.pipeline()
            pipe.lpush(self.key, json.dumps(log_entry, ensure_ascii=False))
            pipe.ltrim(self.key, 0, self.max_len - 1)  # 只保留最近 max_len 条
            pipe.execute()

        except Exception:
            self.handleError(record)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

logger = logging.getLogger('qtrading')
logger.setLevel(logging.INFO)

# 创建一个格式器（formatter），定义日志的输出格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 非开发模式下才挂载 Redis 写入
env = os.getenv('ENV', 'dev').lower()
if env != 'dev':
    try:
        from utils.redis_obj import redis_obj
        logger.addHandler(RedisHandler(redis_obj))
    except Exception as e:
        logger.warning(f"Failed to initialize Redis log handler: {e}")
