"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

def load_env(env: str = None):
    if env is None:
        env = os.getenv('ENV', 'dev').lower()

    # 假设此文件在 utils/ 下，项目根是它的父目录
    project_root = Path(__file__).parent.resolve()
    dotenv_file = '.env' if env == 'production' else f'.env.{env}'
    dotenv_path = project_root / dotenv_file

    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=True)
        # print(f"Loaded environment from {dotenv_path}")
    else:
        print(f"Warning: {dotenv_path} not found. Using existing environment variables.")

# 自动加载（可选）
load_env()

# 调试开关
is_debug = os.getenv('DEBUG', False)

# 数据库配置
database_conn_str = os.getenv('DATABASE_CONN_STR')

# Deepseek API
deepseek_apikey = os.getenv('DEEPSEEK_APIKEY')

# 阿里云百炼API
aliyun_bailian_apikey = os.getenv('ALIYUN_BAILIAN_APIKEY')

# 豆包API
ark_apikey = os.getenv('DOUBAO_APIKEY')

# siliconflow
siliconflow_apikey = os.getenv('SILICONFLOW_APIKEY')

# 腾讯API
tencent_api = os.getenv('TENCENT_APIKEY')

# 智谱API
zhipu_api = os.getenv('ZHIPU_APIKEY')

# 飞书机器人Webhook
feishu_webhook_url = os.getenv('FEISHU_WEBHOOK_URL')

# Redis配置
redis_host = os.getenv('REDIS_HOST')

redis_port = int(os.getenv('REDIS_PORT', 6379))

# EODHD API
eodhd_api_key = os.getenv('EODHD_API_KEY')

# RabbitMQ配置
rabbitmq_config = {
    'host': os.getenv('RABBITMQ_HOST'),
    'port': int(os.getenv('RABBITMQ_PORT', 5672)),
    'username': os.getenv('RABBITMQ_USERNAME'),
    'password': os.getenv('RABBITMQ_PASSWORD'),
    'virtual_host': os.getenv('RABBITMQ_VIRTUAL_HOST', '/'),
    'queue_name': os.getenv('RABBITMQ_QUEUE_NAME')
}

# 缓存设置
cache_setting = {
    'stock_list': int(os.getenv('CACHE_STOCK_LIST', 1800)),
    'stock_history': int(os.getenv('CACHE_STOCK_HISTORY', 3600))
}

# 大模型配置
llm_model_setting = {
    'stock_dcf_analysis': {
        'platform': 'volcengine',
        # 'model': 'deepseek-v4-flash-ga-260731'
        'model': 'deepseek-v4-pro-ga-260813'
    },
    'stock_dcf_analysis_extra': {
        'platform': 'volcengine',
        'model': 'doubao-seed-2-0-mini-260428'
    },
    'stock_tech_analysis': {
        'platform': 'volcengine',
        'model': 'deepseek-v4-flash-ga-260731'
    },
    'news_analysis': {
        'platform': 'volcengine',
        'model': ['doubao-seed-1-6-flash-250828', 'glm-4-7-251222']
    },
    'chat_app': {
        'platform': 'deepseek',
        'model': 'deepseek-v4-pro'
    }
}

# 数据接口地址
databull_host = os.getenv('DATAJIJI_HOST')

# mcp 服务器地址
mcp_host = os.getenv('MCP_HOST')

# 策略设置
strategy_setting = {
    'news_limit': 100,
    'stock_pool': 300,
    'stock_position_limit': 10,
    'max_market_limit': 60
}

# elasticsearch
elasticsearch_setting = {
    'enable': False,
    'host': os.getenv( 'ES_HOST'),
    'username': os.getenv( 'ES_USER'),
    'password': os.getenv( 'ES_PASSWORD'),
}

# dcf财务数据提取年数
finance_report_date_limit = 1

# dcf分析日期间隔
dcf_report_date_limit = 7

# 最大上下文
llm_max_tokens = 32768