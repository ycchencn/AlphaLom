"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 任务队列消费者（Redis Stream 版，替代原 RabbitMQ 的 job_server_mq.py）。
 *
 * 语义对照（与原 pika 实现保持等价）：
 * - 消费组模式等价于原「多 worker 共抢一个 durable queue」：多个 job_server 进程
 *   用同一个 group、不同 consumer 名，XREADGROUP 自动分摊、互不重复。
 * - prefetch=1 → XREADGROUP count=1：一次只取一条，处理完再取。
 * - 失败 nack(requeue=False)（毒丸直接丢弃）→ 失败 XACK 丢弃并 error 日志。
 *   **必须 ACK**：不 ACK 它就一直躺在 PEL，超时后被 claim 逻辑重投 → 无限重试毒丸。
 * - pika 断线重连 → Redis 异常外层循环退避重连。
 * - 额外的增强（pika 版没有）：PEL 超时认领。worker 崩溃没来得及 ACK 的消息，
 *   闲置超过 JOB_QUEUE_CLAIM_IDLE_MS 后被存活消费者 XCLAIM 重做 → 至少一次语义
 *   （job 函数因此要能容忍重复执行；现状都是幂等的 upsert 型任务）。
 *
 * 只用 Redis 5.0 就有的命令（XADD/XGROUP/XREADGROUP/XACK/XPENDING/XCLAIM），
 * 不用 6.2+ 的 XAUTOCLAIM（5.x 用 XPENDING 明细 + XCLAIM 手工实现等价逻辑）。
"""

import json
import logging
import os
import signal
import socket
import sys
import time
from typing import Any, Callable, Dict, Optional

import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

# Import your specific modules
from backtest.strategy.run_portfolio_daily import run_daily_strategy
from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_update_factors import job_update_stock_factor
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis
from job.job_stock_analysis import job_stock_analysis
from job.job_check_signal import job_check_signal
from config import job_queue_config
from models.database import db_session
from models.job_queue import get_queue_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Type alias for job functions
JobFunc = Callable[..., Any]


class MarketJobConsumer:
    """Redis Stream 消费组消费者（同步阻塞循环，进程级单消费者）。"""

    # 可重试的 Redis 传输层异常（连接断/超时），其余异常按业务错误处理
    _TRANSIENT = (RedisConnectionError, RedisTimeoutError, socket.timeout, OSError)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or job_queue_config
        self.stream: str = self.config['stream']
        self.group: str = self.config['group']
        self._closing = False
        # 消费者名带上主机与 PID：日志里能定位到具体实例，PEL 归属清晰
        self.consumer = f"{socket.gethostname()}-{os.getpid()}"

        # Registry for job functions: maps 'job_func' string to actual function
        self._job_registry: Dict[str, JobFunc] = {
            'job_update_stock_greedy_data': job_update_stock_greedy_data,
            'run_daily_strategy': run_daily_strategy,
            'job_update_stock_factor': job_update_stock_factor,
            'job_stock_dcf_model_analysis': job_stock_dcf_model_analysis,
            'job_stock_analysis': job_stock_analysis,
            'job_check_signal': job_check_signal,
        }

    # ---------- Redis 基础设施 ----------

    def _ensure_group(self, client: redis.Redis) -> None:
        """创建消费组；组已存在（BUSYGROUP）视为成功。

        初始 id 用 '0' 而不是 '$'：对齐被替代的 RabbitMQ 语义 —— 消费者未启动时
        入队的任务要保留并处理（web 先上线、job_server 后启动的切换窗口内投递的任务
        不能凭空消失）。流每次裁剪后头部通常已被消费完，'0' 的额外重放风险仅限
        「人工删除消费组重建」这种运维操作，且 job 均为幂等 upsert。
        """
        try:
            client.xgroup_create(self.stream, self.group, id='0', mkstream=True)
            logger.info(f"消费组已创建: {self.stream} / {self.group}")
        except ResponseError as e:
            if 'BUSYGROUP' not in str(e):
                raise
            logger.info(f"消费组已存在: {self.stream} / {self.group}")

    def _ack(self, client: redis.Redis, message_id: str) -> None:
        """确认并移出 PEL。等价于 pika 的 ack，也等价于 nack(requeue=False)——都终结该消息。"""
        try:
            client.xack(self.stream, self.group, message_id)
        except self._TRANSIENT:
            # ACK 失败：消息留在 PEL，超时后会被 claim 重投（至少一次兜底）
            logger.exception("XACK 失败，消息将由超时认领机制兜底")

    # ---------- 消息处理 ----------

    def _process_entry(self, client: redis.Redis, message_id: str, fields: Dict[bytes, bytes]) -> None:
        raw = fields.get(b'payload', fields.get('payload'))
        if raw is None:
            logger.error(f"[!] 消息缺少 payload 字段，丢弃: {message_id} fields={fields}")
            self._ack(client, message_id)
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"[!] Invalid JSON format: {e}. Body: {str(raw)[:100]}...")
            self._ack(client, message_id)
            return

        job_func_name = message.get('job_func', 'unknown')
        logger.info(f"[x] Received job: {job_func_name} | ID: {message_id}")

        # 与 pika 版一致：注册表里找不到就丢弃，不让它卡住队列
        job_func = self._job_registry.get(job_func_name)
        if not job_func:
            logger.error(f"[!] Unknown job function: {job_func_name}. Message discarded.")
            self._ack(client, message_id)
            return

        try:
            job_args = message.get('job_args', {})
            logger.info(f"[x] Executing {job_func_name} with args: {job_args}")
            job_func(**job_args)
            logger.info(f"[✓] Successfully processed: {job_func_name}")
            self._ack(client, message_id)
        except Exception as job_err:
            # 与原实现同样的取舍：逻辑错误直接丢弃防无限循环；毒丸不重投。
            # 依赖外部监控/日志发现失败任务。
            logger.exception(f"[!] Job execution failed ({job_func_name}): {job_err}")
            self._ack(client, message_id)
        finally:
            # Ensure DB session is removed to return connection to pool
            try:
                db_session.remove()
            except Exception:
                pass  # Ignore errors during cleanup

    def _read_one(self, client: redis.Redis) -> None:
        """XREADGROUP 拉一条（count=1，等价 prefetch=1），阻塞至多 block_ms。"""
        entries = client.xreadgroup(
            self.group, self.consumer, {self.stream: '>'}, count=1,
            block=self.config['block_ms'],
        )
        if not entries:
            return
        _name, msgs = entries[0]
        for message_id, fields in msgs:
            if isinstance(message_id, bytes):
                message_id = message_id.decode()
            self._process_entry(client, message_id, fields)

    def _claim_stale(self, client: redis.Redis) -> None:
        """认领超时未 ACK 的消息（至少一次语义的兜底，等价于 6.2 XAUTOCLAIM 的 5.x 手搓版）。

        只认闲置超过 claim_idle_ms 且不属于本消费者的条目：本消费者正在跑的长任务
        不能被自己重复执行。XPENDING 明细自带 idle（5.x 即可用），按 id 排序取前 100 条足够。
        """
        pending = client.xpending_range(
            self.stream, self.group, min='-', max='+', count=100)
        if not pending:
            return
        claim_idle_ms = self.config['claim_idle_ms']
        mine = self.consumer.encode()
        stale = [
            p['message_id'] for p in pending
            if p.get('time_since_delivered', 0) >= claim_idle_ms and p.get('consumer') != mine
        ]
        if not stale:
            return
        logger.info(f"[claim] 发现 {len(stale)} 条超时未确认消息，认领重投: {stale}")
        claimed = client.xclaim(
            self.stream, self.group, self.consumer,
            min_idle_time=claim_idle_ms, message_ids=stale)
        for message_id, fields in claimed:
            if isinstance(message_id, bytes):
                message_id = message_id.decode()
            self._process_entry(client, message_id, fields)

    # ---------- 主循环 ----------

    def run(self) -> None:
        """常驻消费循环：连接 → 建组 → 读取/认领 → 优雅退出。传输层断连指数退避重连。"""
        logger.info(f"启动任务消费者: stream={self.stream} group={self.group} consumer={self.consumer}")
        backoff = 1
        while not self._closing:
            try:
                client = get_queue_client()
                self._ensure_group(client)
                backoff = 1
                while not self._closing:
                    self._claim_stale(client)
                    self._read_one(client)
            except self._TRANSIENT as e:
                if self._closing:
                    break
                logger.warning(f"Redis 连接异常，{backoff}s 后重连: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            except Exception:
                # 主循环自身抛了未预期异常：记录后退避重来，不让整个进程崩
                logger.exception("消费循环异常，5s 后重启循环")
                time.sleep(5)
        logger.info("消费者已优雅退出")

    def stop(self, *_args) -> None:
        """信号处理：置位退出标志；当前消息处理完、block 等待到期后自然退出。"""
        if self._closing:
            return
        logger.info("收到停止信号，处理完当前消息后退出...")
        self._closing = True


def main():
    consumer = MarketJobConsumer()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Signal {sig} received. Initiating shutdown...")
        consumer.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        consumer.run()
    except Exception as e:
        logger.critical(f"Fatal error running consumer: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
