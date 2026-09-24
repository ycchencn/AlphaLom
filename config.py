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

# ===== 任务队列（Redis Stream，原 RabbitMQ 已移除）=====
# stream 为队列名；group 为消费组名（多个 job_server 进程共组分摊 + 各自 PEL）；
# block_ms 是 XREADGROUP 阻塞等待时长（无任务时多久醒一次，也决定优雅退出延迟）；
# claim_idle_ms：消息滞留 PEL 超过该时长即视为消费者已死，会被其他消费者 XCLAIM 认领重投
# （至少一次语义 —— job 函数要能容忍重复执行）。
job_queue_config = {
    'stream': os.getenv('JOB_QUEUE_STREAM', 'alphalom-job'),
    'group': os.getenv('JOB_QUEUE_GROUP', 'alphalom-job-workers'),
    'block_ms': int(os.getenv('JOB_QUEUE_BLOCK_MS', 5000)),
    'claim_idle_ms': int(os.getenv('JOB_QUEUE_CLAIM_IDLE_MS', 10 * 60 * 1000)),
}

# ===== HTTP 服务（uvicorn 启动参数与并发模型）=====
# 两个独立的并发旋钮，作用层次不同，别混为一谈：
#
#   workers          多进程。每个 worker 是独立进程，各自有事件循环、anyio 线程池、
#                    数据库连接池；进程间不共享内存（缓存/限流只能靠 Redis）。
#                    吞吐线性提升，但**内存与数据库连接数按倍数增长**。
#   thread_pool_size 单进程内线程数上限。本项目绝大多数路由是同步 `def`（内部调用
#                    pymysql / requests 等阻塞库），Starlette 会把它们丢进 anyio 线程池
#                    执行，这个值即「一个进程能同时处理多少个阻塞型请求」。
#                    anyio 默认 40。注意它只约束阻塞型路由，纯 async 路由不受约束。
#
# 容量约束（改大之前先看这里）：
#   - 线程池上限不要超过本进程数据库连接池容量，否则线程会排队等连接，白占线程。
#     models/database.py 是 pool_size=30 + max_overflow=50 → 单进程最多 80 条连接。
#   - 每个 worker 各自建连接池，MySQL 侧总连接数 = workers × (pool_size + max_overflow)，
#     改 workers 前先确认数据库 max_connections 够用。
#   - dev 下 reload=True，uvicorn 强制单进程，workers 不生效（见 run_fastapi.py）。
server_setting = {
    'host': os.getenv('WEB_HOST', '0.0.0.0'),
    'port': int(os.getenv('WEB_PORT', 8080)),                    # 默认 8080
    'workers': int(os.getenv('WEB_WORKERS', 1)),                 # 默认 1（多进程）
    'thread_pool_size': int(os.getenv('WEB_THREAD_POOL_SIZE', 40))  # 默认对齐 anyio 的 40
}

# ===== 接口缓存（单位：秒）=====
cache_setting = {
    'stock_list': int(os.getenv('CACHE_STOCK_LIST', 1800)),     # 股票列表缓存 1800s（30 分钟）
    'stock_history': int(os.getenv('CACHE_STOCK_HISTORY', 3600)), # 历史行情缓存 3600s（1 小时）
    # 监控股票列表：接口内部是 N+1 查询（每只票 4 次），开销大；
    # 所含数据（恐惧贪婪、52 周高低、主力行为阶段）都是日频更新，
    # 但 monitoring 标记可能被后台任务随时改动，故 TTL 取短一些（默认 5 分钟）
    'monitored_stocks': int(os.getenv('CACHE_MONITORED_STOCKS', 300)),
    # ETF 监控列表：与个股池同类（每只 ETF 2 次因子查询 + 1 次上游实时行情，是 N+1），
    # 但它的载荷里带**实时报价**，缓存久了页面上的价格就是假的，
    # 所以 TTL 取短（默认 60 秒），只用来吸收「反复进出页面」的重复请求。
    # 增删 ETF 由写接口主动失效（见 routes/etf.py 的 ETF_LIST_NS），不依赖这个 TTL。
    'etfs': int(os.getenv('CACHE_ETFS', 60))
}

# ===== 登录鉴权（多用户）=====
# 登录 token 存 Redis：键 = token_prefix + token，值 = 该 token 所属用户的 id，
# 到点自动过期。登出 = 删键，改密码/禁用 = 按前缀扫删该用户的全部令牌。
# 与旧实现的关键差别：旧 token 是「只发号不落库」的 uuid4，全仓无人校验，
# 等于后端没有鉴权；现在后端能由 token 反查「当前用户」，多用户隔离才成立。
# 每次校验成功都会续期（滑动过期），避免用户正在使用时被踢下线。
auth_setting = {
    'token_prefix': os.getenv('AUTH_TOKEN_PREFIX', 'alphalom:auth:token:'),
    'token_ttl': int(os.getenv('AUTH_TOKEN_TTL', 7 * 24 * 3600)),   # 秒，默认 7 天
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
        'model': 'doubao-seed-2-0-mini-260428'
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
# 数据接口（DataBull）根地址，env: DATABULL_HOST
databull_host = os.getenv('DATABULL_HOST')

# 数据接口（DataBull）密钥
databull_key = os.getenv('DATABULL_KEY')

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
