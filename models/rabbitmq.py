"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

# models/rabbitmq.py

import pika
import logging
import json
import threading

from config import rabbitmq_config

logger = logging.getLogger(__name__)

class RabbitMQPublisher:
    """RabbitMQ 发布器（线程安全）

    pika 的 BlockingConnection **不是线程安全的**：多线程并发 basic_publish 会交错写入
    AMQP 帧，直接损坏连接（表现为后续 publish 全部报 StreamLostError / 帧错乱）。
    路由早先全是 `async def`、串行跑在唯一的事件循环线程上，问题被掩盖了；改成同步
    `def` 路由（Starlette 丢线程池）之后请求会真正并发，因此连接与信道的所有操作
    都必须串行化 —— 统一由下面这把可重入锁保护。
    """

    def __init__(self, config=None):
        self.config = config or rabbitmq_config
        self._connection = None
        self._channel = None
        # 可重入：publish 失败重连时会再次进入 _connect，但 publish 本身不重入
        self._lock = threading.RLock()

    def _connect(self):
        """建立连接和信道（调用方须持有 self._lock）"""
        if self._connection and self._connection.is_open:
            return

        credentials = pika.PlainCredentials(
            self.config['username'],
            self.config['password']
        )
        parameters = pika.ConnectionParameters(
            host=self.config['host'],
            port=self.config['port'],
            virtual_host=self.config['virtual_host'],
            credentials=credentials,
            heartbeat=600,          # 启用心跳（秒）
            blocked_connection_timeout=300
        )
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.queue_declare(
            queue=self.config['queue_name'],
            durable=True  # 队列持久化
        )

    def _ensure_connection(self):
        """确保连接有效，否则重连（调用方须持有 self._lock）"""
        try:
            if self._connection is None or self._connection.is_closed:
                self._connect()
            elif self._channel is None or self._channel.is_closed:
                self._channel = self._connection.channel()
                self._channel.queue_declare(
                    queue=self.config['queue_name'],
                    durable=True
                )
        except Exception as e:
            logger.error(f"Failed to ensure RabbitMQ connection: {e}")
            self._connection = None
            self._channel = None
            raise

    def _basic_publish(self, body: str):
        """真正投递（调用方须持有 self._lock）"""
        self._channel.basic_publish(
            exchange='',
            routing_key=self.config['queue_name'],
            body=body,
            properties=pika.BasicProperties(delivery_mode=2)  # 持久化消息
        )

    def publish(self, message: dict):
        """安全地发布消息（整段加锁，保证多线程下帧流不被交错）"""
        # 先序列化：原实现在 try 内部才赋值 body，_ensure_connection() 抛错时
        # except 分支引用 body 会变成 NameError，掩盖掉真正的连接错误
        body = json.dumps(message, ensure_ascii=False)

        with self._lock:
            try:
                self._ensure_connection()
                self._basic_publish(body)
                logger.info(f" [x] Sent message: {body}")
            except Exception as e:
                logger.error(f"Failed to publish message: {e}")
                # 可选：在此处重试一次
                try:
                    self._connect()  # 强制重建
                    self._basic_publish(body)
                    logger.info(f" [✓] Retried and sent: {body}")
                except Exception as e2:
                    logger.error(f"Retry failed: {e2}")
                    raise

    def close(self):
        with self._lock:
            if self._channel and self._channel.is_open:
                self._channel.close()
            if self._connection and self._connection.is_open:
                self._connection.close()

# 全局单例（线程安全的惰性初始化）
_publisher = None
_publisher_lock = threading.Lock()

def get_publisher():
    """获取全局 publisher（双重检查锁，多线程下只会创建一个实例）"""
    global _publisher
    if _publisher is None:
        with _publisher_lock:
            if _publisher is None:
                _publisher = RabbitMQPublisher()
    return _publisher
