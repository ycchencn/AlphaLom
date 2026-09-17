"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * Optimized Version:
 * - Strategy pattern for job routing
 * - Robust session management
 * - Enhanced error handling and logging
 * - Type hinting and better structure
"""

import json
import logging
import signal
import sys
from typing import Any, Callable, Dict, Optional

import pika
from pika.adapters.select_connection import SelectConnection

# Import your specific modules
from backtest.strategy.run_portfolio_daily import run_daily_strategy
from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_update_factors import job_update_stock_factor
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis
from job.job_stock_analysis import job_stock_analysis
from job.job_check_signal import job_check_signal
from models.rabbitmq import rabbitmq_config
from models.database import db_session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Type alias for job functions
JobFunc = Callable[..., Any]

class MarketJobConsumer:
    """
    Asynchronous RabbitMQ Consumer for Stock Market Jobs.
    Uses pika's SelectConnection for non-blocking I/O.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or rabbitmq_config
        self._connection: Optional[SelectConnection] = None
        self._channel: Optional[pika.channel.Channel] = None
        self._closing = False
        self._consumer_tag: Optional[str] = None

        # Registry for job functions: maps 'job_func' string to actual function
        self._job_registry: Dict[str, JobFunc] = {
            'job_update_stock_greedy_data': job_update_stock_greedy_data,
            'run_daily_strategy': run_daily_strategy,
            'job_update_stock_factor': job_update_stock_factor,
            'job_stock_dcf_model_analysis': job_stock_dcf_model_analysis,
            'job_stock_analysis': job_stock_analysis,
            'job_check_signal': job_check_signal,
        }

    def _get_job_function(self, func_name: str) -> Optional[JobFunc]:
        """Retrieve job function from registry."""
        return self._job_registry.get(func_name)

    def callback(self, ch: pika.channel.Channel, method: pika.spec.Basic.Deliver,
                 properties: pika.spec.BasicProperties, body: bytes):
        """Message processing callback with robust error handling."""
        message_str = ""
        job_func_name = "unknown"

        try:
            # 1. Parse Message
            message_str = body.decode('utf-8')
            message = json.loads(message_str)
            job_func_name = message.get('job_func', 'unknown')

            logger.info(f"[x] Received job: {job_func_name} | Tag: {method.delivery_tag}")

            # 2. Validate Job Function
            job_func = self._get_job_function(job_func_name)
            if not job_func:
                logger.error(f"[!] Unknown job function: {job_func_name}. Message discarded.")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # 3. Database Session Management
            # Assuming db_session is a scoped_session factory.
            # We ensure removal happens even if exceptions occur.
            session_removed = False
            try:
                # Trigger session creation within this thread/context
                # If your db_session is a context manager, use: with db_session() as session: ...
                # Here we assume standard scoped_session usage where access creates the session
                # and we must call remove() afterwards.

                # Execute Job
                job_args = message.get('job_args', {})

                # 增加这行日志，方便排查是哪个股票代码出了问题
                logger.info(f"[x] Executing {job_func_name} with args: {job_args}")

                job_func(**job_args)

                logger.info(f"[✓] Successfully processed: {job_func_name}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as job_err:
                # Specific job execution error
                logger.exception(f"[!] Job execution failed ({job_func_name}): {job_err}")
                # Decision: Requeue or Nack?
                # If it's likely a transient error (DB lock, network), requeue with caution.
                # If it's a logic error, nack without requeue to avoid poison pill.
                # For simplicity here, we nack without requeue to prevent infinite loops,
                # relying on external monitoring or DLQ configured in RabbitMQ.
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            finally:
                # Ensure DB session is removed to return connection to pool
                try:
                    db_session.remove()
                except Exception:
                    pass # Ignore errors during cleanup

        except json.JSONDecodeError as e:
            logger.error(f"[!] Invalid JSON format: {e}. Body: {message_str[:100]}...")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.exception(f"[!] Critical error in callback: {e}")
            # In critical failures, we might want to requeue if we suspect infrastructure issue,
            # but usually safe to nack to stop processing bad state.
            if ch.is_open:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def connect(self):
        """Initiate connection to RabbitMQ."""
        logger.info("Connecting to RabbitMQ...")
        credentials = pika.PlainCredentials(
            self.config['username'],
            self.config['password']
        )
        parameters = pika.ConnectionParameters(
            host=self.config['host'],
            port=self.config['port'],
            virtual_host=self.config['virtual_host'],
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
            connection_attempts=5, # Increased attempts
            retry_delay=5,
            socket_timeout=10
        )

        self._connection = pika.SelectConnection(
            parameters,
            on_open_callback=self.on_connection_open,
            on_open_error_callback=self.on_connection_open_error,
            on_close_callback=self.on_connection_closed
        )

    def on_connection_open(self, connection: SelectConnection):
        """Callback when connection is successfully opened."""
        logger.info("Connection opened")
        connection.channel(on_open_callback=self.on_channel_open)

    def on_connection_open_error(self, _unused_connection: SelectConnection, err: Exception):
        """Callback when connection open fails."""
        logger.error(f"Connection open failed: {err}")
        if not self._closing:
            self.reconnect()

    def on_connection_closed(self, _unused_connection: SelectConnection, reason: Exception):
        """Callback when connection is closed."""
        self._channel = None
        if self._closing:
            logger.info("Connection closed gracefully. Stopping IOLoop.")
            self._connection.ioloop.stop()
        else:
            logger.warning(f"Connection closed unexpectedly: {reason}. Reconnecting in 5s...")
            if self._connection and self._connection.ioloop:
                self._connection.ioloop.call_later(5, self.reconnect)

    def reconnect(self):
        """Logic to restart the consumer loop for reconnection."""
        if self._connection and self._connection.ioloop:
            self._connection.ioloop.stop()

        if not self._closing:
            logger.info("Restarting consumer loop...")
            self.run()

    def on_channel_open(self, channel: pika.channel.Channel):
        """Callback when channel is opened."""
        logger.info("Channel opened")
        self._channel = channel
        self._channel.add_on_close_callback(self.on_channel_closed)

        # Declare Queue
        self._channel.queue_declare(
            queue=self.config['queue_name'],
            durable=True,
            callback=self.on_queue_declareok
        )

    def on_channel_closed(self, channel: pika.channel.Channel, reason: Exception):
        """Callback when channel is closed."""
        logger.warning(f"Channel closed: {reason}")
        if self._connection and self._connection.is_open:
            self._connection.close()

    def on_queue_declareok(self, method_frame: pika.frame.Method):
        """Callback when queue declaration succeeds."""
        logger.info(f"Queue declared: {self.config['queue_name']}")

        # Set QoS (Prefetch count)
        prefetch_count = 1 # Process one message at a time per consumer
        self._channel.basic_qos(prefetch_count=prefetch_count, callback=self.start_consuming)

    def start_consuming(self, _unused_frame):
        """Start consuming messages."""
        self._consumer_tag = self._channel.basic_consume(
            queue=self.config['queue_name'],
            on_message_callback=self.callback
        )
        logger.info(f" [*] Waiting for messages. To exit press CTRL+C (Tag: {self._consumer_tag})")

    def run(self):
        """Run the consumer."""
        self.connect()
        try:
            self._connection.ioloop.start()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Stopping...")
            self.stop()

    def stop(self):
        """Stop the consumer gracefully."""
        if self._closing:
            return

        logger.info("Stopping consumer...")
        self._closing = True

        if self._channel:
            # Cancel consuming first
            if self._consumer_tag:
                self._channel.basic_cancel(self._consumer_tag, callback=self.on_cancelok)
            else:
                self._channel.close()
        elif self._connection:
            self._connection.close()

    def on_cancelok(self, _unused_frame):
        """Callback after cancelling consumer."""
        logger.info("Consumer cancelled. Closing channel...")
        if self._channel:
            self._channel.close()

    def on_stop_ok(self, _unused_frame):
        """Callback after channel is closed."""
        logger.info("Channel closed. Closing connection...")
        if self._connection:
            self._connection.close()


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
