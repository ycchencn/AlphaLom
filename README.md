<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="public/images/alphalom-logo-dark.png">
  <img src="public/images/alphalom-logo-220.png" alt="AlphaLom" width="360">
</picture>

### 一体化金融数据分析与智能投研平台

**以 Alpha（超额收益）为标的、以 Loom（织机）为喻**
把散落在行情、财务、新闻与另类数据中的市场信号，编织成可执行的投资决策。

[![Version](https://img.shields.io/badge/version-v4.4.0-D63C33?style=flat-square)](#)
[![License](https://img.shields.io/badge/license-Apache--2.0-4C8BF5?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?style=flat-square&logo=vuedotjs&logoColor=white)](#)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?style=flat-square&logo=mysql&logoColor=white)](#)
[![Redis](https://img.shields.io/badge/Redis-cache%20%2B%20queue-DC382D?style=flat-square&logo=redis&logoColor=white)](#)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](#)

</div>

---

## 📖 项目简介

AlphaLom 面向个人量化投资者与投研团队，提供从 **多源数据采集 → 因子与信号计算 → LLM 智能研判 → 投资组合管理 → 策略回测** 的全链路能力。

平台以 **REST API + Web 控制台** 双形态交付，原生集成多路大语言模型（火山方舟 · 阿里云百炼 · DeepSeek · 智谱 GLM · SiliconFlow），把 LLM 的语义理解系统性地嵌进投研流程——财报解读、新闻情绪投票、量化策略代码生成、AI 辅助调仓。让机器读得懂市场，也让决策留得下痕迹。

> 模型接入层（`llms/`）封装了多家平台；**实际生效的路由由 `config.llm_model_setting` + 系统设置页共同决定**，可在不改代码的前提下切换场景 → 模型。

## ✨ 功能特性

| | 模块 | 能力 |
|:--:|:--|:--|
| 📈 | **市场监控** | 沪深大盘指数与申万一级行业涨跌、板块情绪、市场温度计；事件驱动流按题材聚合全市场新闻，附关联个股、标签与多空情绪强度，并提供**每小时刷新的 AI 速览**（置顶前三条摘要） |
| 🎯 | **个股监控** | 股票池支持关键字搜索添加（代码 / 名称双路联想）；个股详情整合 K 线与技术指标、主力行为阶段判定、恐贪指数、财务评分与 DCF 估值 |
| 🧮 | **技术面因子分析** | 基于 **2130 万行 / 1888 标的 / 107 因子** 的因子库，提供四层分析：因子看板、技术面仪表盘（均线排列 · 动量-波动象限 · 超买超卖热度 · ATR 动态止损）、因子雷达 + 同行业横向对比、因子选股器与技术信号扫描（纯规则计算，不消耗大模型额度） |
| 🛰️ | **ETF 监控** | 监控清单持久化到数据库，支持搜索添加与删除；详情页含历史走势（K 线 + 量价指标）、基本资料、成分股穿透 |
| 💼 | **投资组合** | 组合总资产 / 仓位 / 浮动盈亏 / 夏普比率 / 最大回撤 / 年化收益，净值与收益走势曲线，持仓行业分布，交易复盘与 AI 调仓计划落库 |
| 🔁 | **量化策略与回测** | 多策略账户信号总览、回测参数设置、回测记录与逐笔明细、QuantStats 绩效报告 |
| 🧠 | **AI 分析** | 统一封装多路 LLM 按任务画像路由；自动生成研报、多模型新闻投票、策略代码生成，以及支持 MCP 工具调用的 AI 对话 |
| 👥 | **多用户与权限** | 管理员建号（不开放自助注册），令牌存 Redis、7 天滑动续期；股票池 / 投资组合 / ETF 自选按账号隔离；越权一律返回 **404**（不泄露资源存在性） |
| 🧩 | **数据接口** | 覆盖市场、股票、ETF、投资组合、回测、因子六大域的 REST 接口；投资组合另提供**对外开放 API（API Key 鉴权 + OpenAPI）**，可直接对接第三方系统 |

## 🧱 系统架构

![系统架构](public/readme/architecture.svg)

「单体仓库 + 多进程服务」：同一镜像 `alphalom-service` 由 `docker-compose.yaml` 编排启动多个角色。

| 服务 | 端口 | 入口 | 职责 |
|:--|:--|:--|:--|
| `web` | 8080 | `run_fastapi.py` | FastAPI REST API（主节点，静态资源 + SPA，含 /api/v1/chat 流式对话） |
| `scheduler` | — | `scheduler.py` | 收盘后数据 / 因子 / 信号调度 |
| `job_server` | — | `job/job_server.py` | Redis Stream 任务消费者（消费组） |
| `news_server` | — | `job/news_server.py` | 新闻聚合 |
| `log_comsumer` | — | `log_comsumer.py` | 日志消费 |

**后端模块**

- `app/` —— FastAPI 应用工厂、可信代理白名单、缓存策略、统一 JSON 响应
- `routes/`（16 个已注册路由器）· `service/`（33 个业务模块）· `llms/`（多模型封装）· `backtest/`（回测引擎与策略）
- `job/`（17 个离线任务）· `models/`（DB / Redis / 任务队列）· `utils/` · `prompts/`
- `alphalom/` —— 项目自研的行情数据 SDK：股票 / ETF / 新闻多源抓取（雪球 · 同花顺 · 新浪 · CNBC），扁平包布局、仓库根直接可 `import`

**前端视图**（`src/views/`）：`market` · `stock` · `etf` · `portfolios` · `quant` · `ai` · `trading` · `user` · `system` · `auth` · `uikit`

## 🛠 技术栈

| 层次 | 选型 |
|:--|:--|
| 🎨 **前端** | Vue 3 · Vite · PrimeVue · Tailwind · klinecharts / ECharts · Monaco Editor |
| ⚙️ **后端** | Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Pydantic 2 · uvicorn |
| 🗄️ **存储 / 中间件** | MySQL（业务库）· Redis（接口缓存 + 会话 + Stream 任务队列） |
| 🤖 **模型层** | 火山方舟（豆包 / GLM）· 阿里云百炼 · DeepSeek · 智谱 GLM · SiliconFlow——按场景画像路由，可在系统设置页热切换 |
| 📡 **数据源** | DataBull（主力行情 / 财务数据 SDK）· 自研 `alphalom` SDK 多源抓取（雪球 · 同花顺 · 新浪 · CNBC） |
| 🚀 **调度 / 部署** | APScheduler · Docker / docker-compose |

## 🎯 关键设计

- **交易时段缓存**：盘前 / 盘中用正常缓存键，15:00–09:00（盘后）强制换 Key 回源，避免盘后行情被长期缓存。
- **多模型 LLM 路由**（`config.llm_model_setting` + 系统设置页覆盖）：按场景分配模型，例如 DCF 深度研报走火山方舟 `deepseek-v4-flash`、研报补充与技术面走 `doubao-seed-2-0-mini`、新闻分析在豆包 / GLM 间按序回退、新闻速览固定走实测可用的快模型控成本。⚠️ 平台「模型列表里存在」≠「账号可用」，路由表只登记实测可用的模型，避免同一任务时好时坏。
- **因子库查询红线**：`factor_values` 是 EAV 长表，主键为 `(trade_date, ticker, factor_name)`（交易日居首）。任何「取最新值」都必须先用 `trade_date IN (<最近 K 个交易日>)` 命中主键首列，**绝不写 range 条件**，否则会退化为全表扫描（实测某查询 57s → 1.3s）。同时「最新交易日」不能取全表 `MAX`——日更按监控池分批落库，需取最近 K 个有数据的交易日并集。
- **定时调度**（`scheduler.py`，Asia/Shanghai）：16:15 回测、16:30 调仓（周日 20:30 补）；20:10 个股刷新 + 因子 + 信号（周一/三/五）、20:15 Beta、20:35 申万行业、20:55 恐贪、21:00 ETF 恐贪；周五 20:30 DCF 与基础评分；每日 00:05 刷新交易日历。
- **并发模型**：绝大多数路由写成同步 `def`，由 anyio 线程池承接阻塞调用，从而拿到真并发；worker 数与线程池上限均配置化，不写死在代码里。
- **真实 IP**：`app/__init__.py` 维护可信代理白名单，仅信任来自可信代理的 `X-Forwarded-For`，防 IP 伪造。

## 🌐 对外开放 API（OpenAPI）

投资组合模块提供一套**基于 API Key 鉴权、只读**的开放数据接口，挂载在独立的 `/api/ext` 下，自带独立 Swagger 文档（`/api/ext/docs`），与主应用互不干扰。支持密钥自助管理、每日调用配额（429 + `Retry-After`）、字段级敏感信息剥离。

- 调用方式、鉴权头、配额、四个数据端点、密钥管理接口、cURL / Python / Node 示例、服务端配置：👉 **[docs/EXTERNAL_API.md](docs/EXTERNAL_API.md)**
- 部署后可在 `<你的域名或IP>:8080/api/ext/docs` 直接试调。

## 🧮 技术面因子分析

在既有的因子库（`factor_values`）之上，为个股与全市场提供四层分析能力，接口挂在 `/factor/*`：

| 层 | 端点 | 说明 |
|:--|:--|:--|
| L0 | `GET /factor/catalog` | 因子字典（107 个因子的中文名 / 描述 / 分类） |
| L0 | `GET /factor/stock/{symbol}` | 因子看板：按分组展示该标的最新因子快照 |
| L1 | `GET /factor/stock/{symbol}/dashboard` | 技术面仪表盘：均线排列、动量-波动象限、超买超卖热度、关键位与 ATR 动态止损 |
| L2 | `GET /factor/stock/{symbol}/radar` | 因子雷达 |
| L2 | `GET /factor/stock/{symbol}/industry_rank` | 同行业横向对比（按 `stocks.industry` 精确匹配） |
| L3 | `POST /factor/screen` | 因子选股器：多条件 AND 组合筛选全市场标的 |
| L3 | `GET /factor/signals` | 技术信号扫描（内置信号目录见 `/factor/signals/catalog`） |

前端入口：个股详情「技术面」Tab 的 `FactorPanel` 组件，以及独立页面 `/quant/factor_screen`（因子选股）。设计说明见 👉 **[docs/技术面分析专业功能方案.md](docs/技术面分析专业功能方案.md)**

> ⚠️ **数值口径**（写阈值前务必先量 min/max）：`mom_*` / `bias_*` / `vol_*` 是**小数**（`0.03` = 3%，非百分数）；`rsi_14` / `52week_position` 是 **0~100**；`closing_strength` 是 0~1；`turnover_*` 是**成交量均值**（无流通股本，非换手率）；`atr_14` 是价格。

## 👥 多用户与鉴权

系统**不开放自助注册**，账号一律由管理员在「系统管理 · 用户管理」创建。

- **登录标识**：用户名或邮箱 + 密码；成功后签发令牌存 Redis（前缀 `alphalom:auth:token:`，7 天滑动续期）。
- **数据隔离**：股票池（`user_stock_pool`）、投资组合（`investment_portfolio.uid`）、ETF 自选（`etf_watchlist.user_id`）按账号隔离。
- **权限模型**：`require_admin` 兜底管理接口；前端路由守卫按 `meta.requiresAdmin` 拦一道。
- **越权处理**：访问他人的资源一律返回 **404**，不返回 403——避免通过状态码泄露「该资源存在」。
- **载荷约定**：接口只返回 DTO（`to_dict()`），绝不直接序列化 ORM 对象；`user_id` 严禁出现在可写白名单里。

## 📁 目录结构

```
alphalom/
├── run_fastapi.py        # FastAPI REST 入口（含流式对话 /api/v1/chat）
├── scheduler.py          # 定时任务入口
├── log_comsumer.py       # 日志消费入口
├── config.py             # 全局配置（按 ENV 加载 .env / .env.<env>）
├── app/ routes/ service/ llms/ backtest/ job/ models/ utils/ prompts/ alphalom/
├── src/                  # Vue 前端源码
├── public/               # 静态资源（images/ 品牌资源、readme/ 截图与配图）
├── install/              # SQL 初始化脚本
├── docs/                 # 专题文档（对外开放 API、因子分析方案）
├── dist/                 # 前端构建产物（由 FastAPI SPA 路由直接服务）
├── docker-compose.yaml   # 服务编排
├── Dockerfile
└── requirements.txt
```

## 🚀 快速开始

### 安装与配置

```bash
pip install -r requirements.txt
npm install
cp .env.sample .env       # 配置数据库 / Redis / 各 LLM API Key
```

`config.py` 在导入时按环境变量 `ENV` 加载对应文件：`ENV=production`（默认值之外）读 `.env`，其余读 `.env.<ENV>`（如 `.env.dev`），未找到时回退到进程已有的环境变量。

主要环境变量（详见 `config.py`）：`DATABASE_CONN_STR`、`REDIS_*`、`JOB_QUEUE_*`（任务队列 stream / 消费组名等）、`*_APIKEY`、`DATABULL_HOST`、`DATABULL_KEY`、`MCP_HOST`。

**并发配置**（见 `config.py` 的 `server_setting`）：

| 变量 | 默认 | 说明 |
|:--|:--|:--|
| `WEB_HOST` | `0.0.0.0` | 监听地址 |
| `WEB_PORT` | `8080` | 监听端口 |
| `WEB_WORKERS` | `1` | uvicorn 多进程 worker 数（每 worker 独立事件循环 + 线程池 + 连接池） |
| `WEB_THREAD_POOL_SIZE` | `40` | 单进程 anyio 线程池上限，即「同时执行的同步阻塞路由数」 |

> `WEB_THREAD_POOL_SIZE` 只约束同步 `def` 路由（本项目绝大多数路由是同步的，才能拿多线程并发）；纯 `async` 路由靠事件循环并发，不受其约束。调大前注意 DB 连接池容量：单进程最多 `pool_size + max_overflow = 80` 条连接，多 worker 时总连接数按倍数增长。

### 启动服务

```bash
python run_fastapi.py          # 主服务（FastAPI，dev 下自动热重载，含流式对话 /api/v1/chat）
python scheduler.py            # 定时调度
docker-compose up -d           # 或一键编排全部服务

npm run dev                    # Vite 开发服务器
npm run build                  # 构建到 dist/（由 FastAPI SPA 路由直接服务）
```

### Docker 构建与部署

`./docker.sh` 管理镜像与服务：`all` / `base` / `build` / `up` / `down` / `restart` / `status` / `logs` / `clean` / `help`。无参数运行默认「构建并启动」。

## 🖼 界面预览

<table>
<tr>
<td width="50%">
<img src="public/readme/01-market-overview.png" alt="沪深大盘监控">
<b>沪深大盘监控</b><br>指数行情卡片 + 大盘恐惧贪婪指数 + 成长/价值轮动，申万行业涨跌排行（一 / 二 / 三级可切换）
</td>
<td width="50%">
<img src="public/readme/02-event-driven.png" alt="事件驱动">
<b>事件驱动</b><br>AI 事件驱动速览（按时间展示，跟随时区设置）+ 按题材聚合全市场新闻，附关联个股与多空情绪
</td>
</tr>
<tr>
<td width="50%">
<img src="public/readme/03-stock-pool.png" alt="股票池">
<b>股票池（个股监控）</b><br>左侧分组含<strong>组内等权涨跌幅</strong>；主力行为阶段、概念题材、52 周价格区间
</td>
<td width="50%">
<img src="public/readme/04-stock-detail.png" alt="个股详情">
<b>个股详情</b><br>K 线走势（多周期 / 多指标切换）+ 技术面仪表盘：均线排列、超买超卖热度、关键位与 ATR 动态止损
</td>
</tr>
<tr>
<td width="50%">
<img src="public/readme/05-etf-insight.png" alt="ETF 洞察">
<b>ETF 洞察</b><br>监控清单可持久化，支持搜索添加与删除，列表带净值涨跌与 52 周价格区间
</td>
<td width="50%">
<img src="public/readme/06-etf-detail.png" alt="ETF 详情">
<b>ETF 详情</b><br>基本资料、恐惧贪婪指标、历史走势，申赎清单（PCF）成分股穿透与快捷入池
</td>
</tr>
</table>

> 以上截图取自真实运行的实例（沪深大盘 / 事件驱动 / 股票池 / 个股详情 / ETF 洞察 / ETF 详情），
> 统一 1600×1050 取景、以普通用户视角抓取（因此侧栏不含管理员专属的「系统管理」分组）。

## 👤 作者

**Yc** —— `yccheni@163.com`

## 📄 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源。
