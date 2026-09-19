# FinFilo

金融数据分析与投资组合管理平台：提供股票 / ETF / 市场行情接口，并集成多 LLM 做智能分析（财报解读、新闻解读、量化策略生成与回测）。

> 当前版本：`v4.2.0`

## 功能特性

- **数据接口**：市场（大盘 / 板块 / 情绪 / 温度）、股票（行情 / 档案 / 技术信号 / DCF / 恐贪指数 / 财务评分）、ETF、投资组合（组合 / 统计 / 交易 / 盈亏）、回测（任务 / 信号 / 调仓）。
- **AI 分析**：统一封装 DeepSeek、通义千问、豆包、智谱 GLM、SiliconFlow、MiniMax；自动生成报告、多模型新闻投票、策略代码生成、支持 MCP 的 AI 对话。

## 技术栈

- **前端**：Vue 3 + Vite + PrimeVue + Tailwind + klinecharts / echarts
- **后端**：Python · FastAPI（REST + 流式对话 + MCP 工具调用）
- **存储 / 中间件**：MySQL（SQLAlchemy）、Redis（缓存 + 会话 + Stream 任务队列）
- **数据源**：DataBull、Baostock、Akshare、Tushare、EODHD
- **调度 / 部署**：APScheduler · Docker / docker-compose

## 系统架构

「单体仓库 + 多进程服务」：同一镜像 `finfilo-service` 由 `docker-compose.yaml` 编排启动多个角色。

| 服务 | 端口 | 入口 | 职责 |
|---|---|---|---|
| `web` | 8080 | `run_fastapi.py` | FastAPI REST API（主节点） |
| `web_slave` | 8081 | `run_fastapi.py` | FastAPI REST API（从节点，负载均衡） |
| `chat_app` | 8082→8000 | `run_chat_app.py` | FastAPI 流式对话 + MCP |
| `scheduler` | — | `scheduler.py` | 收盘后数据 / 因子 / 信号调度 |
| `job_server`(+slave) | — | `job/job_server.py` | Redis Stream 任务消费者（消费组） |
| `news_server` | — | `job/news_server.py` | 新闻聚合 |
| `log_comsumer` | — | `log_comsumer.py` | 日志消费 |

**后端模块**：`app/`（FastAPI 应用工厂、可信代理白名单、缓存策略、统一 JSON 响应）、`routes/`（路由器）、`service/`（~30 个业务逻辑）、`llms/`（多模型封装）、`backtest/`（回测引擎 / 策略）、`job/`（12 个离线任务）、`models/`（db / redis / 任务队列）、`utils/`、`prompts/`、`finfilo/`（框架内部件）、`config.py`（全局配置）。

**前端视图**（`src/views/`）：market / stock / portfolios / quant / ai / trading / user / system / auth / uikit。

## 关键设计

- **交易时段缓存**：盘前 / 盘中用正常缓存键，15:00–09:00（盘后）强制换 Key 回源，避免盘后行情被长期缓存。
- **多模型 LLM 路由**（`config.llm_model_setting`）：DCF → 火山方舟 `deepseek-v4-flash`；新闻 → 豆包 / 智谱多模型投票；对话 → DeepSeek `deepseek-v4-pro`。
- **定时调度**（`scheduler.py`，Asia/Shanghai）：16:15 回测、16:30 调仓（周日 20:30 补）；20:10 个股刷新 + 因子 + 信号、20:15 Beta、20:55 恐贪；周五 20:30 DCF 与基础评分。
- **真实 IP**：`app/__init__.py` 维护可信代理白名单，仅信任来自可信代理的 `X-Forwarded-For`，防 IP 伪造。

## 目录结构

```
finfilo/
├── run_fastapi.py        # FastAPI REST 入口
├── run_chat_app.py       # FastAPI 对话入口
├── scheduler.py          # 定时任务入口
├── log_comsumer.py       # 日志消费入口
├── config.py             # 全局配置
├── app/ routes/ service/ llms/ backtest/ job/ models/ utils/ prompts/ finfilo/
├── src/                  # Vue 前端源码
├── public/               # 静态资源
├── install/              # SQL 初始化脚本
├── dist/                 # 前端构建产物
├── docker-compose.yaml   # 服务编排
├── Dockerfile
└── requirements.txt
```

## 快速开始

### 安装与配置

```bash
pip install -r requirements.txt
npm install
cp .env.example .env      # 配置数据库 / Redis / 各 LLM API Key
```

主要环境变量（详见 `config.py`）：`DATABASE_CONN_STR`、`REDIS_*`、`JOB_QUEUE_*`（任务队列 stream/消费组名等）、`*_APIKEY`、`DATABULL_HOST`、`MCP_HOST`。

**并发配置**（见 `config.py` 的 `server_setting`）：

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `WEB_HOST` | `0.0.0.0` | 监听地址 |
| `WEB_PORT` | `8080` | 监听端口 |
| `WEB_WORKERS` | `1` | uvicorn 多进程 worker 数（每 worker 独立事件循环 + 线程池 + 连接池） |
| `WEB_THREAD_POOL_SIZE` | `40` | 单进程 anyio 线程池上限，即「同时执行的同步阻塞路由数」 |

> `WEB_THREAD_POOL_SIZE` 只约束同步 `def` 路由（本项目绝大多数路由是同步的，才能拿多线程并发）；纯 `async` 路由靠事件循环并发，不受其约束。调大前注意 DB 连接池容量：单进程最多 `pool_size + max_overflow = 80` 条连接，多 worker 时总连接数按倍数增长。

### 启动服务

```bash
python run_fastapi.py          # 主服务（FastAPI，dev 下自动热重载）
python run_chat_app.py         # AI 对话服务（独立进程，端口 8000）
docker-compose up -d           # 或一键编排全部服务

npm run dev                    # Vite 开发服务器
npm run build                  # 构建到 dist/（由 FastAPI SPA 路由直接服务）
```

### Docker 构建与部署

`./docker.sh` 管理镜像与服务：`all` / `base` / `build` / `up` / `down` / `restart` / `status` / `logs` / `clean` / `help`。无参数运行默认「构建并启动」。

## 截图

![SNI (5).png](public/readme/SNI%20%285%29.png)
![SNI (4).png](public/readme/SNI%20%284%29.png)
![SNI (3).png](public/readme/SNI%20%283%29.png)
![SNI (1).png](public/readme/SNI%20%281%29.png)
![SNI (6).png](public/readme/SNI%20%286%29.png)
