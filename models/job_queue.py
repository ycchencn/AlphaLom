"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 任务队列（Redis Stream 实现，替代原 RabbitMQ/pika）。
 *
 * 为什么用 Stream 而不是简单的 LIST（LPUSH/BRPOP）：
 * - 消费组（XGROUP + XREADGROUP + XACK）提供「至少一次」语义：消费者取走后
 *   消息滞留 PEL（pending list），进程崩溃没 ACK 的条目可被 XCLAIM 认领重投；
 *   LIST 弹出即丢，worker 处理中途挂掉那条任务就没了。
 * - 复用已部署的 Redis，少一个中间件（原 RabbitMQ 独立容器/凭据全部移除）。
 *
 * 兼容性约束：dev 与生产的 Redis 是 5.x ——
 * 1) 客户端必须 protocol=2（5.x 不支持 RESP3 的 HELLO 命令，默认协议连不上）；
 * 2) 只能用 5.0 就有的命令：XADD / XGROUP / XREADGROUP / XACK / XCLAIM / XPENDING。
 *    不要用 6.2+ 的 XAUTOCLAIM 和 XADD 的 NOMKSTREAM。
"""

import json
import logging
import threading

import redis

from config import redis_host, redis_port, job_queue_config

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()


def get_queue_client() -> redis.Redis:
    """队列专用同步客户端（全局单例，双重检查锁）。

    与 utils/redis_obj.py 分开：那个挂了缓存等其他用途；这里独立一个 db0
    连接池，protocol=2 对齐服务器能力（见模块注释）。redis-py 的同步客户端
    底层是连接池，单条命令线程安全，多线程路由并发 publish 没有问题
    （这正是当初 pika BlockingConnection 需要加 RLock 的坑，这里天然免疫）。
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=0,
                    protocol=2,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    decode_responses=False,
                )
    return _client


def send_job(job: dict) -> str:
    """投递一条任务：job 形如 {'job_func': ..., 'job_args': {...}}。

    字段里冗余一份 job_func 只是为了在 Redis 里肉眼可辨（SCAN/monitor 时不用解 JSON），
    消费者只信任 payload。maxlen 粗裁：约 10 万条封顶（任务消息很小），
    防止长期无人消费时无限增长；正常消费下 PEL/历史都远小于此。
    返回消息 ID（如 '1789785744660-0'）。
    """
    stream = job_queue_config['stream']
    message_id = get_queue_client().xadd(
        stream,
        {
            'payload': json.dumps(job, ensure_ascii=False),
            'job_func': str(job.get('job_func', '')),
        },
        maxlen=100000,
    )
    if isinstance(message_id, bytes):
        message_id = message_id.decode()
    logger.info(f"[job_queue] 已投递 {job.get('job_func')} -> {stream}@{message_id}")
    return message_id
