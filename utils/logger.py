"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import logging

logger = logging.getLogger("sqlalchemy.engine.Engine")
logger.setLevel(logging.CRITICAL)
logger.disabled = True

logger = logging.getLogger('qtrading')
logger.setLevel(logging.INFO)

# 创建一个控制台处理器（handler）
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # 控制台处理器的日志级别也设置为 DEBUG

# 创建一个格式器（formatter），定义日志的输出格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 将格式器添加到处理器
console_handler.setFormatter(formatter)

# 将处理器添加到 logger
logger.addHandler(console_handler)