"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models.job_queue import send_job


class JobService:

    @staticmethod
    def send_job(job):
        # job 形如 {'job_func': ..., 'job_args': {...}}，投递进 Redis Stream
        # （原 RabbitMQ/pika 已移除；消费者见 job/job_server.py）
        send_job(job)

if __name__ == '__main__':

    JobService.send_job({
        'job_func': 'job_update_market_data_all',
        'job_args': {
            'stock_code_override': '688332',
            'delete_old_data': True,
        }
    })
