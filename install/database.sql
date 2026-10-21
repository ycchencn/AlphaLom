/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE IF NOT EXISTS `alphalom` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `alphalom`;

CREATE TABLE IF NOT EXISTS `api_key` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '密钥内部 id（管理接口用）',
  `user_id` int NOT NULL COMMENT '所属用户（users.id）',
  `name` varchar(100) NOT NULL COMMENT '用户给密钥起的备注名',
  `key_prefix` varchar(12) NOT NULL COMMENT '明文密钥前缀（前 12 字符），用于展示',
  `key_hash` varchar(64) NOT NULL COMMENT 'sha256(明文密钥)，hex',
  `status` varchar(10) NOT NULL COMMENT 'active / revoked',
  `daily_quota` int DEFAULT NULL COMMENT '单密钥每日配额覆盖；NULL=用全局默认',
  `last_used_at` datetime DEFAULT NULL COMMENT '最近一次成功调用时间（节流写入）',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `expires_at` datetime DEFAULT NULL COMMENT '过期时间；NULL=不过期',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_api_key_key_hash` (`key_hash`),
  KEY `ix_api_key_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `app_logs` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `timestamp` datetime NOT NULL COMMENT '日志时间戳',
  `level` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '日志级别',
  `logger` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'logger 名称',
  `message` text COLLATE utf8mb4_unicode_ci COMMENT '日志消息',
  `module` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '模块名',
  `func` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '函数名',
  `line` int DEFAULT NULL COMMENT '行号',
  `created_at` datetime DEFAULT NULL COMMENT '入库时间',
  PRIMARY KEY (`id`),
  KEY `ix_app_logs_timestamp` (`timestamp`),
  KEY `ix_app_logs_level` (`level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `daily_pnl_records` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `date` date NOT NULL COMMENT '交易日期',
  `portfolio_id` varchar(50) NOT NULL COMMENT '组合ID',
  `stock_code` varchar(20) NOT NULL COMMENT '股票代码',
  `stock_name` varchar(50) DEFAULT NULL COMMENT '股票名称',
  `position_size` int DEFAULT NULL COMMENT '持仓数量',
  `cost_price` decimal(12,4) DEFAULT NULL COMMENT '成本价',
  `close_price` decimal(12,4) DEFAULT NULL COMMENT '当日收盘价',
  `market_value` decimal(18,2) DEFAULT NULL COMMENT '市值 = size * close',
  `unrealized_pnl` decimal(18,2) DEFAULT NULL COMMENT '浮动盈亏金额',
  `pnl_pct` decimal(10,4) DEFAULT NULL COMMENT '浮动盈亏百分比（%）',
  `total_assets` decimal(18,2) DEFAULT NULL COMMENT '组合总资产（冗余）',
  `cash_balance` decimal(18,2) DEFAULT NULL COMMENT '现金余额',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_daily_pnl_records_stock_code` (`stock_code`),
  KEY `ix_daily_pnl_records_portfolio_id` (`portfolio_id`),
  KEY `ix_daily_pnl_records_date` (`date`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `etf_rotation_pool` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int DEFAULT NULL COMMENT '所属用户（users.id）',
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'ETF代码，如 512480',
  `name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'ETF名称（加入时从 databull 取，可空）',
  `created_at` datetime DEFAULT NULL COMMENT '加入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_symbol` (`user_id`,`symbol`),
  KEY `ix_etf_rotation_pool_symbol` (`symbol`),
  KEY `ix_etf_rotation_pool_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `etf_watchlist` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int DEFAULT NULL COMMENT '所属用户（users.id）',
  `symbol` varchar(25) NOT NULL COMMENT 'ETF代码，如 159901',
  `name` varchar(100) DEFAULT NULL COMMENT 'ETF名称（加入时从 databull 取，可空）',
  `created_at` datetime DEFAULT NULL COMMENT '加入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_symbol` (`user_id`,`symbol`),
  KEY `ix_etf_watchlist_user_id` (`user_id`),
  KEY `ix_etf_watchlist_symbol` (`symbol`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `factor_values` (
  `trade_date` date NOT NULL COMMENT '交易日期，如 2024-12-01',
  `ticker` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码，如 000001.SZ、600519.SH',
  `factor_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '因子名称，如 pe_ttm, roe_q, momentum_20d',
  `value` decimal(18,6) DEFAULT NULL COMMENT '因子值，支持高精度浮点',
  `source` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '数据来源，如 wind, tushare, custom',
  `update_time` datetime DEFAULT NULL COMMENT '执行时间',
  PRIMARY KEY (`trade_date`,`ticker`,`factor_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `investment_portfolio` (
  `portfolio_id` int NOT NULL AUTO_INCREMENT COMMENT '组合唯一ID（自增）',
  `uid` int DEFAULT NULL COMMENT '所属用户（users.id）',
  `name` varchar(100) NOT NULL COMMENT '组合名称',
  `strategy_type` int NOT NULL COMMENT '策略类型',
  `total_position_pct` decimal(5,2) NOT NULL COMMENT '总仓位百分比',
  `base_currency` varchar(10) DEFAULT NULL COMMENT '基准货币',
  `position_plan` json DEFAULT NULL COMMENT '仓位计划（JSON）',
  `position_plan_reason` text COMMENT '仓位计划理由',
  `init_cash` decimal(18,2) NOT NULL COMMENT '初始资金',
  `current_cash` decimal(18,2) NOT NULL COMMENT '当前资金',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `llm_prompt` text COMMENT '大模型提示词',
  `llm_setting` json DEFAULT NULL COMMENT '大模型配置（JSON）',
  `desc` text COMMENT '组合描述',
  `enable` int NOT NULL COMMENT '是否启用：0-停用, 1-启用',
  `market` varchar(50) NOT NULL COMMENT '市场：cn/hk/us 等',
  `quantstat_json` json DEFAULT NULL COMMENT '量化绩效统计（JSON）',
  PRIMARY KEY (`portfolio_id`),
  UNIQUE KEY `uniq_uid_name` (`uid`,`name`),
  KEY `ix_investment_portfolio_uid` (`uid`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `llm_agent` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int NOT NULL COMMENT '所属用户（users.id）',
  `name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '智能体名称',
  `emoji` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '头像 emoji',
  `platform` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '大模型平台标识',
  `model` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模型名称',
  `system_prompt` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '系统提示词',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_name` (`user_id`,`name`),
  KEY `ix_llm_agent_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `llm_conversation_context` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `chat_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '会话ID',
  `chat_context` text COLLATE utf8mb4_bin COMMENT '会话上下文内容',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `llm_token_usage` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int DEFAULT NULL COMMENT '调用者用户（users.id）；后台任务为 NULL',
  `scene` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '业务场景/LLM 配置名，如 stock_dcf_analysis / chat',
  `platform` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '平台标识：deepseek/volcengine/siliconflow/aliyun/zhipu',
  `model` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模型名称',
  `prompt_tokens` int DEFAULT NULL COMMENT '输入 token 数',
  `completion_tokens` int DEFAULT NULL COMMENT '输出 token 数',
  `total_tokens` int DEFAULT NULL COMMENT '总 token 数',
  `input_text` text COLLATE utf8mb4_unicode_ci COMMENT '对话输入（messages 拼接，截断到 6000 字）',
  `output_text` text COLLATE utf8mb4_unicode_ci COMMENT '模型输出文本（截断到 6000 字）',
  `created_at` datetime DEFAULT NULL COMMENT '调用时间',
  PRIMARY KEY (`id`),
  KEY `ix_llm_token_usage_user_id` (`user_id`),
  KEY `ix_llm_token_usage_scene` (`scene`),
  KEY `ix_llm_token_usage_created_at` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=41 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `market_news` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `digest` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '新闻摘要',
  `tags` json NOT NULL COMMENT '标签列表',
  `relation_level` int DEFAULT NULL COMMENT '关联程度等级',
  `bullish_level` int NOT NULL COMMENT '是否看涨',
  `relations_stocks` json NOT NULL COMMENT '关联股票列表，格式为 [{"code": "...", "name": "..."}]',
  `relations_imported` int DEFAULT NULL COMMENT '是否已导入个股监控',
  `news_time` datetime NOT NULL COMMENT '新闻发布时间',
  `news_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '新闻类型',
  `news_md5` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '新闻唯一哈希值',
  `sources` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '新闻来源',
  `url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '新闻来源url',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `news_digest` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `generated_at` datetime NOT NULL COMMENT '生成时间',
  `window_start` datetime NOT NULL COMMENT '统计窗口起（含）',
  `window_end` datetime NOT NULL COMMENT '统计窗口止（含）',
  `news_count` int NOT NULL COMMENT '参与总结的新闻条数',
  `title` varchar(120) DEFAULT NULL COMMENT '速览标题，如「新闻流速览」',
  `headlines` json NOT NULL COMMENT '前三条头条（最多 3 条）',
  `highlights` json NOT NULL COMMENT '次要要点（一句话/条）',
  `model` varchar(120) DEFAULT NULL COMMENT '生成所用模型标识',
  `trigger_type` varchar(20) NOT NULL COMMENT '触发方式：auto-定时任务 / manual-页面手动刷新',
  PRIMARY KEY (`id`),
  KEY `ix_news_digest_generated_at` (`generated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `portfolio_assets` (
  `asset_id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `portfolio_id` varchar(36) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '投资组合ID（与 investment_portfolio.portfolio_id 对应）',
  `stock_code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票/ETF标的代码',
  `asset_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '标的名称',
  `position_pct` decimal(5,2) NOT NULL COMMENT '标的仓位百分比',
  `create_time` datetime DEFAULT NULL COMMENT '创建时间',
  `last_update` datetime DEFAULT NULL COMMENT '更新时间',
  `position_price` float NOT NULL COMMENT '最新价格',
  `cost_price` float NOT NULL COMMENT '持仓价格（成本价）',
  `position_size` int NOT NULL COMMENT '持仓数量',
  `position_beta` float NOT NULL COMMENT 'Beta',
  `base_rsi_threshold` int NOT NULL COMMENT 'RSI卖出阈值',
  `stop_loss_percent` float NOT NULL COMMENT '止损线（%）',
  `take_profit_percent` float NOT NULL COMMENT '止盈线（%）',
  `remark` text COLLATE utf8mb4_unicode_ci COMMENT '备注',
  PRIMARY KEY (`asset_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `portfolio_daily_summary` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `date` date NOT NULL COMMENT '交易日期（组合级唯一）',
  `portfolio_id` varchar(50) NOT NULL COMMENT '组合ID',
  `total_assets` decimal(18,2) NOT NULL COMMENT '总资产',
  `total_unrealized_pnl` decimal(18,2) NOT NULL COMMENT '总浮动盈亏',
  `total_pnl_pct` decimal(10,4) NOT NULL COMMENT '总盈亏%',
  `position_ratio` decimal(5,4) NOT NULL COMMENT '仓位比例（0~1）',
  `cash_balance` decimal(18,2) NOT NULL COMMENT '现金余额',
  `daily_pnl_change` float DEFAULT NULL COMMENT '相对前一日的变化',
  `cumulative_realized_pnl` float DEFAULT NULL COMMENT '累计已实现盈亏',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_portfolio_daily_summary_date` (`date`),
  KEY `ix_portfolio_daily_summary_portfolio_id` (`portfolio_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `portfolio_transaction` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `date` date NOT NULL COMMENT '交易日期',
  `action` enum('BUY','SELL') COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '交易动作：BUY-买入, SELL-卖出',
  `code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '标的代码',
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '标的名称',
  `qty` int NOT NULL COMMENT '成交数量',
  `price` decimal(15,4) NOT NULL COMMENT '成交价格',
  `amount` decimal(18,2) NOT NULL COMMENT '成交金额',
  `realized_pnl` decimal(18,2) DEFAULT NULL COMMENT '已实现盈亏',
  `portfolio_id` int NOT NULL COMMENT '投资组合编号',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `research_reports` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `report_type` smallint NOT NULL COMMENT '研报类型: 1-个股, 2-行业, 3-宏观/策略',
  `stock_code` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '股票代码 (如: 600519.SH)',
  `stock_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '股票名称',
  `industry_code` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '行业代码 (申万/中信)',
  `industry_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '行业名称',
  `title` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研报标题',
  `summary` text COLLATE utf8mb4_unicode_ci COMMENT '摘要/核心观点',
  `content_text` text COLLATE utf8mb4_unicode_ci COMMENT '全文内容 (用于检索)',
  `content_json` json DEFAULT NULL COMMENT '结构化内容（JSON，如估值/图表数据）',
  `rating` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '投资评级 (买入/增持/中性/卖出)',
  `target_price` decimal(10,2) DEFAULT NULL COMMENT '目标价格',
  `current_price` decimal(10,2) DEFAULT NULL COMMENT '发布时股价',
  `broker_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '券商机构名称',
  `analyst_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '分析师姓名 (多人逗号分隔)',
  `publish_time` datetime NOT NULL COMMENT '研报发布时间',
  `created_at` datetime NOT NULL COMMENT '入库时间',
  PRIMARY KEY (`id`),
  KEY `ix_research_reports_stock_code` (`stock_code`),
  KEY `ix_research_reports_industry_code` (`industry_code`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sector_daily_stats` (
  `stat_date` date NOT NULL COMMENT '统计日期（上游 stat_date）',
  `sector_type` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '板块级别：SW1/SW2/SW3',
  `sector_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '申万板块名称',
  `change_pct` decimal(10,2) DEFAULT NULL COMMENT '涨跌幅（%）',
  `stock_count` int DEFAULT NULL COMMENT '成分股数量',
  `up_count` int DEFAULT NULL COMMENT '上涨家数',
  `down_count` int DEFAULT NULL COMMENT '下跌家数',
  `flat_count` int DEFAULT NULL COMMENT '平盘家数',
  `up_down_ratio` decimal(10,2) DEFAULT NULL COMMENT '涨跌比（上游原值，down=0 时为 100）',
  `top_stock` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '领涨股名称',
  `top_stock_pct` decimal(10,2) DEFAULT NULL COMMENT '领涨股涨跌幅（%）',
  `bottom_stock` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '领跌股名称',
  `bottom_stock_pct` decimal(10,2) DEFAULT NULL COMMENT '领跌股涨跌幅（%）',
  `total_trade_amount` decimal(20,2) DEFAULT NULL COMMENT '总成交额（亿）',
  `update_time` datetime DEFAULT NULL COMMENT '入库时间',
  PRIMARY KEY (`stat_date`,`sector_type`,`sector_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stock_daily_valuation` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `symbol` varchar(25) NOT NULL COMMENT 'A 股代码，如 600519',
  `trade_date` date NOT NULL COMMENT '估值对应日期（上游 valuation_date）',
  `pe_ttm` decimal(14,4) DEFAULT NULL COMMENT '市盈率 PE-TTM（滚动市盈率）',
  `pb` decimal(14,4) DEFAULT NULL COMMENT '市净率 PB',
  `total_volume` decimal(20,2) DEFAULT NULL COMMENT '总股本（股）',
  `update_time` datetime DEFAULT NULL COMMENT '写入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_symbol_trade_date` (`symbol`,`trade_date`),
  KEY `ix_stock_daily_valuation_trade_date` (`trade_date`),
  KEY `ix_stock_daily_valuation_symbol` (`symbol`)
) ENGINE=InnoDB AUTO_INCREMENT=993 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `stock_financial_scores` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `code` varchar(12) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码',
  `roe` decimal(10,4) NOT NULL COMMENT '净资产收益率 ROE（原始值）',
  `profit_growth` decimal(12,4) NOT NULL COMMENT '利润增长率（原始值，%）',
  `cash_quality` decimal(8,4) NOT NULL COMMENT '现金流质量（原始值）',
  `pe` decimal(10,4) NOT NULL COMMENT '市盈率 PE（原始值）',
  `debt_ratio` decimal(8,4) NOT NULL COMMENT '资产负债率（原始值，%）',
  `roe_score` decimal(6,2) NOT NULL COMMENT 'ROE 维度得分',
  `profit_growth_score` decimal(6,2) NOT NULL COMMENT '利润增长维度得分',
  `cash_quality_score` decimal(6,2) NOT NULL COMMENT '现金流质量维度得分',
  `pe_score` decimal(6,2) NOT NULL COMMENT '估值（PE）维度得分',
  `debt_ratio_score` decimal(6,2) NOT NULL COMMENT '负债率维度得分',
  `composite_score` decimal(6,2) NOT NULL COMMENT '综合得分',
  `created_at` datetime DEFAULT (now()) COMMENT '创建时间',
  `updated_at` datetime DEFAULT (now()) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_stock_financial_scores_code` (`code`),
  KEY `ix_stock_financial_scores_composite_score` (`composite_score`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stock_guba_sentiment` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码，如 600519',
  `trade_date` date NOT NULL COMMENT '统计归属日期（采集当日）',
  `bullish_ratio` decimal(5,2) DEFAULT NULL COMMENT '看多帖占比 0~100',
  `neutral_ratio` decimal(5,2) DEFAULT NULL COMMENT '中性帖占比 0~100',
  `bearish_ratio` decimal(5,2) DEFAULT NULL COMMENT '看空帖占比 0~100',
  `sentiment_score` decimal(5,2) DEFAULT NULL COMMENT '散户情绪分 0~100（50=中性，由后端公式计算）',
  `confidence` decimal(5,2) DEFAULT NULL COMMENT '置信度 0~100（样本量不足时模型主动降级）',
  `heat_level` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '活跃度：冷清/正常/活跃/过热',
  `post_count` int NOT NULL COMMENT '24h 内抓到的原始帖子数',
  `sample_size` int NOT NULL COMMENT '实际送入 LLM 的帖子数（超过上限会采样）',
  `effective_count` int DEFAULT NULL COMMENT '模型判定的有效散户自发帖数（剔除资讯转贴后）',
  `close` decimal(18,4) DEFAULT NULL COMMENT '当日收盘价（画双轴用）',
  `dominant_topic` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '当期最集中的话题',
  `reasoning` text COLLATE utf8mb4_unicode_ci COMMENT '模型给出的判断依据',
  `keywords` json DEFAULT NULL COMMENT '高频关键词',
  `notable_posts` json DEFAULT NULL COMMENT '代表性帖子（标题+立场）',
  `model` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '产出该条记录的模型名，便于回溯',
  `update_time` datetime DEFAULT NULL COMMENT '写入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_guba_symbol_trade_date` (`symbol`,`trade_date`),
  KEY `ix_stock_guba_sentiment_symbol` (`symbol`),
  KEY `ix_stock_guba_sentiment_trade_date` (`trade_date`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stock_industry` (
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码，如 000001 / 600519',
  `industry` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属行业（证监会/国民经济行业分类）',
  `market` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '市场：cn-沪深, hk-港股, us-美股',
  `source` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '行业来源：databull / stocks',
  `update_time` datetime DEFAULT (now()),
  PRIMARY KEY (`symbol`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stocks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '股票代码，如 000001 / 600519（唯一标识）',
  `name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '股票名称',
  `name_en` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '英文名称',
  `province` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '省',
  `city` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '市',
  `district` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '区',
  `industry` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属行业',
  `market` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '市场：cn-沪深, hk-港股, us-美股',
  `last_update` datetime DEFAULT NULL COMMENT '最后更新时间',
  `pe_ratio` float DEFAULT NULL COMMENT '市盈率 PE',
  `pb_ratio` float DEFAULT NULL COMMENT '市净率 PB',
  `concepts` text COLLATE utf8mb4_unicode_ci COMMENT '概念板块标签（文本）',
  `securities_type` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '证券类型：stock/etf/fund 等',
  `monitoring` int DEFAULT NULL COMMENT '是否纳入监控：0-否, 1-是',
  `monitor_by` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '监控创建人/来源',
  `setting` json DEFAULT NULL COMMENT '扩展设置（JSON）',
  `ohlc_last` json DEFAULT NULL COMMENT '最近 OHLC 行情快照（JSON）',
  `company_profile` json DEFAULT NULL COMMENT '公司信息',
  PRIMARY KEY (`id`),
  UNIQUE KEY `symbol` (`symbol`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stocks_fear_greed` (
  `trade_date` date NOT NULL COMMENT '交易日期',
  `index_code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '指数代码',
  `close` decimal(18,4) NOT NULL COMMENT '收盘点位',
  `fear_greed` decimal(5,2) NOT NULL COMMENT '恐惧贪婪综合指数',
  `vol_score` decimal(5,2) NOT NULL COMMENT '波动率分项得分',
  `mom_score` decimal(5,2) NOT NULL COMMENT '动量分项得分',
  PRIMARY KEY (`trade_date`,`index_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `system_setting` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `setting_key` varchar(120) COLLATE utf8mb4_bin NOT NULL COMMENT '配置键（全局唯一），如 llm_model_setting.stock_dcf_analysis',
  `setting_group` varchar(60) COLLATE utf8mb4_bin NOT NULL COMMENT '配置分组，如 llm_model_setting',
  `setting_value` json DEFAULT NULL COMMENT '配置值（JSON，可存字符串/数字/布尔/对象/数组）',
  `value_type` varchar(20) COLLATE utf8mb4_bin NOT NULL COMMENT '值类型提示：json/string/int/float/bool（供前端渲染表单）',
  `description` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '说明',
  `updated_by` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '最后修改人',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_system_setting_setting_key` (`setting_key`),
  KEY `ix_system_setting_setting_group` (`setting_group`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `user_stock_pool` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int NOT NULL COMMENT '所属用户（users.id）',
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码',
  `market` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '市场：cn/hk/us',
  `monitor_by` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '加入来源标签（沿用原 stocks.monitor_by 的取值习惯）',
  `group_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '分组名称，NULL/空=未分组',
  `created_at` datetime DEFAULT NULL COMMENT '加入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_symbol` (`user_id`,`symbol`),
  KEY `ix_user_stock_pool_user_id` (`user_id`),
  KEY `ix_user_stock_pool_symbol` (`symbol`)
) ENGINE=InnoDB AUTO_INCREMENT=20 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `username` varchar(50) COLLATE utf8mb4_bin NOT NULL COMMENT '登录用户名（唯一）',
  `password_hash` varchar(255) COLLATE utf8mb4_bin NOT NULL COMMENT '密码哈希（bcrypt/pbkdf2，不存明文）',
  `nickname` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '昵称',
  `email` varchar(100) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '邮箱',
  `role` varchar(20) COLLATE utf8mb4_bin NOT NULL COMMENT '角色：admin-管理员, user-普通用户',
  `is_active` int NOT NULL COMMENT '是否启用：0-禁用, 1-启用',
  `must_change_password` smallint NOT NULL COMMENT '是否需强制修改密码：1-需修改, 0-已修改',
  `last_login_at` datetime DEFAULT NULL COMMENT '最后登录时间',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `uniq_email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
