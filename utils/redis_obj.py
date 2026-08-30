"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import redis
from config import redis_host, redis_port

# 初始化 Redis 连接
redis_obj = redis.Redis(host=redis_host, port=redis_port, db=0, protocol=2)
