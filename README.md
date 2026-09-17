# FinFilo

FinFilo 是一个**金融数据分析与投资组合管理平台**，提供股票、ETF、市场行情等数据接口，并集成多种大语言模型 (LLM) 进行智能分析（财报解读、新闻解读、量化策略生成、回测）。

> 当前版本：`v4.2.0`

## 功能特性

### 📊 数据接口
- **市场数据**：沪深大盘、ETF 信息、成分股查询、市场温度/情绪、板块涨跌
- **股票数据**：历史行情、股票档案、技术分析（信号）、DCF 研究报告、恐贪指数、财务评分
- **投资组合**：组合管理、每日统计、交易记录、盈亏日历
- **回测系统**：回测任务管理、信号生成、调仓计划

### 🤖 AI 智能分析
- 多模型统一封装：DeepSeek、通义千问、豆包（火山方舟）、智谱 GLM、SiliconFlow、MiniMax
- 财务分析报告自动生成（DCF / 基本面）
- 金融新闻智能解读（多模型投票）
- 量化策略代码生成、AI 对话（支持 MCP 工具调用）

## 技术栈

- **前端**：Vue 3 + Vite + PrimeVue + Tailwind + klinecharts / echarts / chart.js
- **后端**：Python
  - REST API：Flask + Flask-RESTX + Flask-Caching
  - AI 对话服务：FastAPI（流式响应 + MCP 工具调用）
- **数据库 / 中间件**：MySQL（SQLAlchemy）、Redis（缓存 + 会话）、RabbitMQ（异步任务）、Elasticsearch（可选）
- **数据源**：DataBull、Baostock、Akshare、Tushare、EODHD
- **调度**：APScheduler
- **部署**：Docker / docker-compose

## 系统架构

FinFilo 采用「单体仓库 + 多进程服务」的部署形态：同一镜像 `finfilo-service` 通过不同入口脚本启动多个角色，由 `docker-compose.yaml` 编排。

### 服务编排（docker-compose）

| 服务 | 端口 | 入口脚本 | 职责 |
|---|---|---|---|
| `web` | 8080 | `run_app.py` | Flask REST API（主节点） |
| `web_slave` | 8081 | `run_app.py` | Flask REST API（从节点，负载均衡） |
| `chat_app` | 8082→8000 | `run_chat_app.py` | FastAPI 流式对话 + MCP 工具调用 |
| `scheduler` | — | `scheduler.py` | 定时任务调度（收盘后跑数据/因子/信号） |
| `job_server` | — | `job/job_server_mq.py` | RabbitMQ 任务消费者 |
| `job_server_slave` | — | `job/job_server_mq.py` | RabbitMQ 任务消费者（从节点） |
| `news_server` | — | `job/news_server.py` | 新闻聚合 |
| `log_comsumer` | — | `log_comsumer.py` | 日志消费 |

### 后端模块

| 目录 | 作用 |
|---|---|
| `app/` | Flask 应用工厂、`get_real_ip`（可信代理白名单）、缓存配置、统一 JSON 响应 |
| `routes/` | 12 个蓝图：main、stock、market、portfolio、watchlist、etf、quant、index、chat、syslog、api |
| `service/` | 核心业务逻辑（约 30 个）：组合、回测任务、新闻、因子、DCF、恐贪指数、市场温度、提示词管理等 |
| `llms/` | 多模型统一封装：deepseek / 火山方舟(ark) / 阿里百炼 / siliconflow / 智谱，分同步与异步两套 |
| `backtest/` | 回测引擎、策略（`strategy/` 子目录：组合日策略、持仓计划）、量化统计、文本嵌入 |
| `job/` | 12 个离线/定时任务（每日行情更新、新闻分析、DCF 建模、因子计算、信号检查、ETF 分析） |
| `models/` | 连接封装：db（SQLAlchemy）、redis、rabbitmq |
| `utils/` | 数据加载、财务计算、Beta 计算、Logger、Redis 缓存 |
| `prompts/` | LLM 提示词模板 |
| `finfilo/` | 框架内部件：`_config`、异常、请求封装 |
| `config.py` | 全局配置：数据库/Redis/RabbitMQ 连接、各 LLM API Key、模型路由、策略参数、缓存时长 |

### 前端视图（`src/views/`）

按业务域组织：

- **市场 `market/`**：大盘概览、ETF 详情/洞察、新闻流、板块情绪、股票池、市场温度
- **个股 `stock/`**：股票详情、股票监控
- **组合 `portfolios/`**：组合列表、组合视图
- **量化 `quant/`**：回测详情、回测记录、量化信号、DCF 洞察、回测设置
- **AI `ai/`**：智能对话
- **交易 `trading/`**：交易终端
- **用户 `user/`**：自选列表
- **系统 `system/`**：系统日志
- **认证 `auth/`**：登录、无权限页
- **组件文档 `uikit/`**：PrimeVue 组件示例集合

## 关键设计

### 交易时段缓存策略
`app/__init__.py` 中的 `trading_cache_key` 在**盘前/交易中**使用正常缓存键，在 **15:00–09:00（盘后）** 强制换 Key 回源，避免盘后过时行情被长期缓存。

### 多模型 LLM 路由
`config.llm_model_setting` 按场景指定平台与模型，例如：
- 股票 DCF 分析 → 火山方舟 `deepseek-v4-flash`
- 新闻分析 → 豆包 `doubao-seed-1.6-flash` / 智谱 `glm-4-7`（多模型投票）
- 对话服务 → DeepSeek `deepseek-v4-pro`

### 定时调度（`scheduler.py`，时区 Asia/Shanghai）
- 16:15 回测策略执行；16:30 生成调仓计划
- 周日 20:30 额外生成调仓计划（`trade_day_override`）
- 20:10 个股信息刷新 + 因子计算 + 技术信号；20:15 更新 Beta；20:55 更新恐贪数据
- 每周五 20:30 更新 DCF 数据与基础财务评分

### 真实 IP 识别
`app/__init__.py` 维护可信代理白名单（`127.0.0.1` / `10.0.0.0/8` / `172.16.0.0/12` / `192.168.0.0/16`），仅信任来自可信代理的 `X-Forwarded-For` 等头部，防止 IP 伪造。

## 目录结构

```
finfilo/
├── run_app.py            # Flask REST 入口
├── run_chat_app.py       # FastAPI 对话入口
├── scheduler.py          # 定时任务入口
├── log_comsumer.py       # 日志消费入口
├── config.py             # 全局配置
├── app/  routes/  service/  llms/  backtest/  job/  models/  utils/  prompts/  finfilo/
├── src/                  # Vue 前端源码
├── public/               # 静态资源
├── install/              # SQL 初始化脚本
├── dist/                 # 前端构建产物
├── docker-compose.yaml   # 服务编排
├── Dockerfile
└── requirements.txt
```

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 配置环境

复制 `.env.example` 为 `.env` 并配置相关 API Key 和数据库连接：

```bash
cp .env.example .env
```

主要环境变量（见 `config.py`）：
- `DATABASE_CONN_STR`：MySQL 连接串
- `REDIS_HOST` / `REDIS_PORT`：Redis 连接
- `RABBITMQ_*`：消息队列连接
- `*_APIKEY`：各 LLM 厂商 API Key（DEEPSEEK / ALIYUN_BAILIAN / DOUBAO / SILICONFLOW / TENCENT / ZHIPU）
- `DATAJIJI_HOST`：DataBull 数据接口地址
- `MCP_HOST`：MCP 服务器地址

### 启动服务

```bash
# 开发环境（Flask REST）
python run_app.py

# AI 对话服务（FastAPI，独立进程）
python run_chat_app.py

# 或使用 docker-compose 一键编排全部服务
docker-compose up -d
```

前端开发服务器：

```bash
npm run dev      # 启动 Vite 开发服务器
npm run build    # 构建到 dist/（Flask 的 static 目录）
```

### Docker 构建与部署

使用 `docker.sh` 脚本管理 Docker 镜像和服务：

```bash
# 完整构建（基础镜像 + 服务镜像 + 启动服务）
./docker.sh all

# 构建基础镜像（BE + FE）
./docker.sh base

# 仅构建服务镜像
./docker.sh build

# 启动/停止/重启服务
./docker.sh up
./docker.sh down
./docker.sh restart

# 查看服务状态和日志
./docker.sh status
./docker.sh logs

# 清理未使用的镜像和容器
./docker.sh clean

# 查看帮助
./docker.sh help
```

> 直接运行 `./docker.sh`（无参数）会执行默认操作：构建服务镜像并启动。

## ⚠️ 注意事项

- 

## 截图

![SNI (5).png](public/readme/SNI%20%285%29.png)

![SNI (4).png](public/readme/SNI%20%284%29.png)

![SNI (3).png](public/readme/SNI%20%283%29.png)

![SNI (1).png](public/readme/SNI%20%281%29.png)

![SNI (6).png](public/readme/SNI%20%286%29.png)
