# FinFilo

FinFilo 是一个金融数据分析与投资组合管理平台，提供股票、ETF、市场行情等数据接口，并集成多种大语言模型 (LLM) 进行智能分析。

## 功能特性

### 📊 数据接口
- **市场数据**: 沪深大盘、ETF信息、成分股查询
- **股票数据**: 历史行情、股票档案、技术分析、DCF研究报告
- **投资组合**: 组合管理、每日统计、交易记录
- **回测系统**: 回测任务管理、信号生成

### 🤖 AI 智能分析
- 基于同义千问/Doubao/DeepSeek/Minimax 等大语言模型
- 财务分析报告自动生成
- 金融新闻智能解读
- 量化策略代码生成

## 技术栈

- **前端**：Vue
- **后端**：Python
- **数据库**：MySQL
- **图表**：klinecharts
- **数据源**：[DataBull金融数据接口](https://www.baidu.com)、Baostock、Akshare

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 配置环境

复制 `.env.example` 为 `.env` 并配置相关 API Key和数据库连接：

```bash
cp .env.example .env
```

### 启动服务

```bash
# 开发环境
python run_app.py
```

![SNI (5).png](public/readme/SNI%20%285%29.png)

![SNI (4).png](public/readme/SNI%20%284%29.png)

![SNI (3).png](public/readme/SNI%20%283%29.png)

![SNI (1).png](public/readme/SNI%20%281%29.png)

![SNI (6).png](public/readme/SNI%20%286%29.png)