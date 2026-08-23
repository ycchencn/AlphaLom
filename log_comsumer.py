"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
import time
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from models import AppLog
from models.database import db_session
from utils.redis_obj import redis_obj

REDIS_KEY = 'app:logs'
BATCH_SIZE = 200
FLUSH_INTERVAL = 10

def consume_logs():
    """从 Redis 批量取日志，用 SQLAlchemy 批量写入 MySQL"""
    pipe = redis_obj.pipeline()
    pipe.lrange(REDIS_KEY, 0, BATCH_SIZE - 1)
    pipe.ltrim(REDIS_KEY, BATCH_SIZE, -1)
    logs_json, _ = pipe.execute()

    if not logs_json:
        return

    logs = [json.loads(item) for item in logs_json]

    try:
        # 批量构建 ORM 对象
        log_objects = []
        for log in logs:
            log_objects.append(AppLog(
                timestamp=datetime.fromisoformat(log['timestamp']),
                level=log.get('level', 'INFO'),
                logger=log.get('logger'),
                message=log.get('message'),
                module=log.get('module'),
                func=log.get('func'),
                line=log.get('line'),
                created_at=datetime.utcnow(),
            ))

        # 批量 add + commit
        db_session.bulk_save_objects(log_objects)
        db_session.commit()

        print(f"[{datetime.now()}] 写入 {len(log_objects)} 条日志")

    except SQLAlchemyError as e:
        db_session.rollback()
        print(f"写入失败, rollback: {e}")
        # 可选：把这批日志推到失败队列，防止死循环重试
        # redis_client.rpush('app:logs:failed', *logs_json)

    finally:
        db_session.remove()  # ⚠️ scoped_session 必须 remove，否则连接不归还连接池


def run_consumer():
    print(f"日志消费者启动，每 {FLUSH_INTERVAL}s 轮询一次...")
    while True:
        try:
            consume_logs()
        except Exception as e:
            print(f"消费异常: {e}")
        time.sleep(FLUSH_INTERVAL)


if __name__ == '__main__':
    run_consumer()