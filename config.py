"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 全局配置中心
 * - 所有敏感凭证 / 环境相关参数均从 .env（或 .env.<ENV>）读取，禁止在此硬编码明文。
 * - 模块导入时自动调用 load_env() 注入环境变量。
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def load_env(env: str = None):
    """
    根据运行环境加载对应的 .env 文件。
    :param env: 环境名，默认取系统变量 ENV，未设置则为 'dev'
    """
    if env is None:
        env = os.getenv('ENV', 'dev').lower()

    # config.py 位于项目根目录，项目根即当前文件所在目录
    project_root = Path(__file__).parent.resolve()
    dotenv_file = '.env' if env == 'production' else f'.env.{env}'
    dotenv_path = project_root / dotenv_file

    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=True)
    else:
        # 未找到对应 .env 文件时回退到进程已有环境变量，仅告警不中断
        print(f"Warning: {dotenv_path} not found. Using existing environment variables.")


# 模块导入即自动加载一次环境（如需指定环境可显式调用 load_env('prod')）
load_env()

# ===== 调试开关 =====
# 取环境变量 DEBUG，未设置则 False（非 '0'/'false' 视为开启）
is_debug = os.getenv('DEBUG', False)

# ===== 数据库 =====
# 数据库连接串（如 mysql+pymysql://user:pwd@host:port/db），env: DATABASE_CONN_STR
database_conn_str = os.getenv('DATABASE_CONN_STR')

# ===== 各厂商 LLM / 平台 API Key =====
# 火山方舟（Doubao / Deepseek on VolcEngine）密钥，env: DOUBAO_APIKEY
ark_apikey = os.getenv('DOUBAO_APIKEY')
# DeepSeek 官方密钥，env: DEEPSEEK_APIKEY
deepseek_apikey = os.getenv('DEEPSEEK_APIKEY')
# 阿里云百炼密钥，env: ALIYUN_BAILIAN_APIKEY
aliyun_bailian_apikey = os.getenv('ALIYUN_BAILIAN_APIKEY')
# SiliconFlow 密钥，env: SILICONFLOW_APIKEY
siliconflow_apikey = os.getenv('SILICONFLOW_APIKEY')
# 腾讯混元密钥，env: TENCENT_APIKEY
tencent_api = os.getenv('TENCENT_APIKEY')
# 智谱 GLM 密钥，env: ZHIPU_APIKEY
zhipu_api = os.getenv('ZHIPU_APIKEY')

# ===== 通知 =====
# 飞书机器人 Webhook 地址，用于告警 / 推送，env: FEISHU_WEBHOOK_URL
feishu_webhook_url = os.getenv('FEISHU_WEBHOOK_URL')

# ===== Redis =====
redis_host = os.getenv('REDIS_HOST')
redis_port = int(os.getenv('REDIS_PORT', 6379))   # 默认 6379

# ===== EODHD 行情数据源 =====
eodhd_api_key = os.getenv('EODHD_API_KEY')

# ===== RabbitMQ 消息队列 =====
rabbitmq_config = {
    'host': os.getenv('RABBITMQ_HOST'),
    'port': int(os.getenv('RABBITMQ_PORT', 5672)),           # 默认 5672
    'username': os.getenv('RABBITMQ_USERNAME'),
    'password': os.getenv('RABBITMQ_PASSWORD'),
    'virtual_host': os.getenv('RABBITMQ_VIRTUAL_HOST', '/'), # 默认 '/'
    'queue_name': os.getenv('RABBITMQ_QUEUE_NAME')
}

# ===== 接口缓存（单位：秒）=====
cache_setting = {
    'stock_list': int(os.getenv('CACHE_STOCK_LIST', 1800)),     # 股票列表缓存 1800s（30 分钟）
    'stock_history': int(os.getenv('CACHE_STOCK_HISTORY', 3600)) # 历史行情缓存 3600s（1 小时）
}

# ===== 大模型路由配置 =====
# key 为业务场景名，get_model_by_setting(key) 据此返回对应 LLM 实例
llm_model_setting = {
    'stock_dcf_analysis': {            # 深度研报（job_deep_research）
        'platform': 'volcengine',
        'model': 'deepseek-v4-flash-ga-260731'
        # 备选更强模型（按需切换）：'deepseek-v4-pro-ga-260813'
    },
    'stock_dcf_analysis_extra': {      # 研报补充分析
        'platform': 'volcengine',
        'model': 'doubao-seed-2-0-mini-260428'
    },
    'stock_tech_analysis': {           # 技术分析
        'platform': 'volcengine',
        'model': 'deepseek-v4-flash-ga-260731'
    },
    'news_analysis': {                 # 新闻分析（多模型候选，按顺序回退）
        'platform': 'volcengine',
        'model': ['doubao-seed-1-6-flash-250828', 'glm-4-7-251222']
    },
    'chat_app': {                      # 对话应用
        'platform': 'deepseek',
        'model': 'deepseek-v4-pro'
    }
}

# ===== 外部数据接口 =====
# 数据接口（DataBull）根地址，env: DATAJIJI_HOST
databull_host = os.getenv('DATAJIJI_HOST')

# ===== MCP 服务 =====
mcp_host = os.getenv('MCP_HOST')      # MCP 服务器地址

# ===== 策略参数 =====
strategy_setting = {
    'news_limit': 100,                 # 单次抓取新闻条数上限
    'stock_pool': 300,                 # 候选股票池规模
    'stock_position_limit': 10,        # 单策略持仓标的数量上限
    'max_market_limit': 60             # 市场标的处理上限
}

# ===== Elasticsearch（可选，默认关闭）=====
elasticsearch_setting = {
    'enable': False,                   # 是否启用 ES 检索
    'host': os.getenv('ES_HOST'),
    'username': os.getenv('ES_USER'),
    'password': os.getenv('ES_PASSWORD'),
}

# ===== 财务 / DCF 分析参数 =====
# 财务数据回溯年数：查询起点 = 今天 - finance_report_date_limit × 365 天
finance_report_date_limit = 1
# DCF / 深度研报生成最小间隔（天）：同一股票在该天数内已生成则跳过，避免重复消耗
dcf_report_date_limit = 7

# 对话 / 上下文最大 token 数（供 DialogueManager 截断使用）
llm_max_tokens = 32768
