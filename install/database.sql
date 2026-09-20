/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE IF NOT EXISTS `stock_quantization` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `stock_quantization`;

CREATE TABLE IF NOT EXISTS `app_logs` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `timestamp` datetime NOT NULL,
  `level` varchar(16) NOT NULL,
  `logger` varchar(64) DEFAULT NULL,
  `message` text,
  `module` varchar(64) DEFAULT NULL,
  `func` varchar(64) DEFAULT NULL,
  `line` int DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_timestamp` (`timestamp`),
  KEY `idx_level` (`level`)
) ENGINE=InnoDB AUTO_INCREMENT=10446 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `backtest_tasks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `portfolio_id` int DEFAULT NULL,
  `backtest_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `stock_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `stock_name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `securities_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'stock',
  `buy_volume` int NOT NULL,
  `sell_volume` int NOT NULL,
  `start_date` date NOT NULL,
  `end_date` date DEFAULT NULL,
  `start_value` decimal(15,2) NOT NULL,
  `end_value` decimal(15,2) NOT NULL,
  `annualized_return` decimal(6,4) DEFAULT NULL,
  `sharp_ratio` decimal(15,2) DEFAULT NULL,
  `calmar_ratio` decimal(6,4) DEFAULT NULL,
  `profit` decimal(15,2) NOT NULL,
  `last_signal_date` date DEFAULT NULL,
  `trade_signal_match` int DEFAULT '0',
  `last_signal_trade_type` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `max_drawdown` float DEFAULT NULL,
  `stock_trading_config` json NOT NULL,
  `ai_audit_comment` json DEFAULT NULL,
  `strategy_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'bbs',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `finished` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `索引 2` (`finished`,`securities_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `backtest_trades` (
  `id` int NOT NULL AUTO_INCREMENT,
  `portfolio_id` int DEFAULT NULL,
  `backtest_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT '',
  `trade_type` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `symbol` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `size` float NOT NULL,
  `price` float NOT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `daily_pnl_records` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `date` date NOT NULL,
  `portfolio_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `stock_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `stock_name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  `position_size` int DEFAULT NULL,
  `cost_price` decimal(12,4) DEFAULT NULL,
  `close_price` decimal(12,4) DEFAULT NULL,
  `market_value` decimal(18,2) DEFAULT NULL,
  `unrealized_pnl` decimal(18,2) DEFAULT NULL,
  `pnl_pct` decimal(10,4) DEFAULT NULL,
  `total_assets` decimal(18,2) DEFAULT NULL,
  `cash_balance` decimal(18,2) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_date_portfolio_stock` (`date`,`portfolio_id`,`stock_code`)
) ENGINE=InnoDB AUTO_INCREMENT=15299 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `etf_analysis` (
  `etf_code` varchar(50) COLLATE utf8mb4_bin NOT NULL DEFAULT '',
  `ohlc_last` json DEFAULT NULL,
  `last_update` datetime DEFAULT NULL,
  PRIMARY KEY (`etf_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `factor_values` (
  `trade_date` date NOT NULL COMMENT '交易日期，如 2024-12-01',
  `ticker` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码，如 000001.SZ、600519.SH',
  `factor_name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '因子名称，如 pe_ttm, roe_q, momentum_20d',
  `value` decimal(18,6) DEFAULT NULL COMMENT '因子值，支持高精度浮点',
  `source` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'custom' COMMENT '数据来源，如 wind, tushare, custom',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `factor_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`trade_date`,`ticker`,`factor_name`),
  KEY `idx_factor_ticker_date` (`factor_name`,`ticker`,`trade_date`),
  KEY `idx_ticker` (`ticker`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='股票因子值主表（日频）';

CREATE TABLE IF NOT EXISTS `futures_basis` (
  `trade_date` date NOT NULL COMMENT '交易日期，如 2025-12-19',
  `index_name` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '指数名称：沪深300 / 上证50 / 中证500',
  `future_symbol` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '主力合约代码，如 IF2603',
  `future_close` decimal(18,6) DEFAULT NULL COMMENT '期货收盘价',
  `spot_close` decimal(18,6) DEFAULT NULL COMMENT '现货指数收盘价',
  `basis` decimal(18,6) DEFAULT NULL COMMENT '贴水 = 期货 - 现货',
  `basis_rate_pct` decimal(18,6) DEFAULT NULL COMMENT '贴水率（%）= 贴水 / 现货 * 100',
  `source` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'akshare_cffex' COMMENT '数据来源',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (`trade_date`,`index_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='股指期货贴水数据（宽表格式）';

CREATE TABLE IF NOT EXISTS `index_constituents` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `index_code` varchar(50) COLLATE utf8mb4_bin NOT NULL COMMENT '指数代码',
  `stock_code` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '股票代码',
  `stock_name` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '股票名称',
  `add_date` date DEFAULT NULL COMMENT '纳入日期',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `investment_portfolio` (
  `portfolio_id` int NOT NULL AUTO_INCREMENT COMMENT 'UUID组合唯一ID',
  `uid` int DEFAULT NULL,
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '组合名称',
  `strategy_type` int DEFAULT '1',
  `total_position_pct` decimal(5,2) NOT NULL,
  `base_currency` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'USD' COMMENT '基准货币',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `position_plan` json DEFAULT NULL,
  `position_plan_reason` text COLLATE utf8mb4_bin,
  `init_cash` float DEFAULT '1000000',
  `current_cash` float DEFAULT '1000000',
  `llm_base` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'doubao',
  `llm_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `llm_prompt` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `llm_setting` json DEFAULT NULL,
  `desc` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `enable` int DEFAULT '1',
  `market` varchar(50) COLLATE utf8mb4_bin DEFAULT 'cn',
  `quantstat_json` json DEFAULT NULL,
  PRIMARY KEY (`portfolio_id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='投资组合管理表';

CREATE TABLE IF NOT EXISTS `llm_conversation_context` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `chat_context` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `llm_prompts` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `prompt_key` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Prompt 唯一标识符，如: news_analysis_v1',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Prompt 可读名称',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Prompt 模板内容，支持 {variable} 占位符',
  `variables` json DEFAULT NULL COMMENT '预期变量列表，如: ["content", "stock_code"]',
  `output_format` enum('text','json_object','json_array') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'text' COMMENT '期望输出格式',
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT 'Prompt 功能描述或使用说明',
  `version` int unsigned NOT NULL DEFAULT '1' COMMENT '版本号，用于灰度或回滚',
  `is_active` tinyint(1) NOT NULL DEFAULT '1' COMMENT '是否启用（0=禁用, 1=启用）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_prompt_key_version` (`prompt_key`,`version`),
  KEY `idx_is_active` (`is_active`),
  KEY `idx_prompt_key` (`prompt_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='LLM Prompt 模板表';

CREATE TABLE IF NOT EXISTS `llm_token_record` (
  `id` int NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `market_daily_limit` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `date` date NOT NULL COMMENT '交易日期',
  `rising` int NOT NULL COMMENT '上涨家数',
  `limit_up` int NOT NULL COMMENT '涨停家数',
  `falling` int NOT NULL COMMENT '下跌家数',
  `limit_down` int NOT NULL COMMENT '跌停家数',
  `flat` bigint NOT NULL COMMENT '平盘家数',
  PRIMARY KEY (`id`),
  UNIQUE KEY `date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `market_fear_greed` (
  `trade_date` date NOT NULL,
  `index_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `close` decimal(18,4) NOT NULL,
  `fear_greed` decimal(5,2) NOT NULL,
  `vol_score` decimal(5,2) NOT NULL,
  `mom_score` decimal(5,2) NOT NULL,
  PRIMARY KEY (`trade_date`,`index_code`),
  KEY `idx_trade_date` (`trade_date`),
  KEY `idx_index_code` (`index_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `market_news` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `digest` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '新闻摘要',
  `tags` json NOT NULL DEFAULT (json_array()) COMMENT '标签列表',
  `relation_level` int DEFAULT NULL COMMENT '关联程度等级',
  `bullish_level` tinyint NOT NULL DEFAULT '0' COMMENT '看涨级别：0-否/中性，1-是（可扩展）',
  `relations_stocks` json NOT NULL DEFAULT (json_array()) COMMENT '关联股票列表，格式为 [{"code": "...", "name": "..."}]',
  `relations_imported` tinyint DEFAULT '0',
  `news_time` datetime NOT NULL COMMENT '新闻发布时间',
  `news_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  `news_md5` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  `sources` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  `url` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  FULLTEXT KEY `digest` (`digest`)
) ENGINE=InnoDB AUTO_INCREMENT=88585 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `portfolio_assets` (
  `asset_id` int NOT NULL AUTO_INCREMENT,
  `portfolio_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `stock_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '股票/ETF标的代码',
  `asset_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `position_pct` decimal(5,2) NOT NULL DEFAULT '0.10',
  `position_price` float DEFAULT NULL,
  `cost_price` float DEFAULT NULL,
  `position_beta` float DEFAULT NULL,
  `position_size` int DEFAULT NULL,
  `base_rsi_threshold` int DEFAULT '85',
  `stop_loss_percent` float DEFAULT '-15',
  `take_profit_percent` float DEFAULT '35',
  `last_update` datetime DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `remark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`asset_id`),
  UNIQUE KEY `uni` (`stock_code`,`portfolio_id`) USING BTREE,
  KEY `portfolio_id` (`portfolio_id`),
  KEY `stock_code` (`stock_code`)
) ENGINE=InnoDB AUTO_INCREMENT=1228 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='组合标的持仓记录表';

CREATE TABLE IF NOT EXISTS `portfolio_daily_summary` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `date` date NOT NULL,
  `portfolio_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `total_assets` decimal(18,2) DEFAULT NULL,
  `total_unrealized_pnl` decimal(18,2) DEFAULT NULL,
  `total_pnl_pct` decimal(10,4) DEFAULT NULL,
  `position_ratio` decimal(5,4) DEFAULT NULL,
  `cash_balance` decimal(18,2) DEFAULT NULL,
  `daily_pnl_change` decimal(20,6) DEFAULT NULL,
  `cumulative_realized_pnl` decimal(20,6) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_date_portfolio` (`date`,`portfolio_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1299 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `portfolio_transaction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `date` date NOT NULL COMMENT '交易日期',
  `action` enum('BUY','SELL') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '操作类型：买入/卖出',
  `code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '股票代码',
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '股票名称',
  `qty` int NOT NULL COMMENT '数量',
  `price` decimal(15,4) NOT NULL COMMENT '成交价格',
  `amount` decimal(18,2) NOT NULL COMMENT '成交金额（qty * price）',
  `realized_pnl` decimal(18,2) DEFAULT '0.00' COMMENT '已实现盈亏',
  `portfolio_id` int NOT NULL COMMENT '组合ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_uni` (`date`,`code`,`portfolio_id`),
  KEY `idx_code` (`code`),
  KEY `idx_date` (`date`),
  KEY `idx_portfolio_id` (`portfolio_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4223 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='投资组合交易记录表';

CREATE TABLE IF NOT EXISTS `research_reports` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `report_type` tinyint NOT NULL COMMENT '1:个股研报, 2:行业研报, 3:宏观/市场策略',
  `stock_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `stock_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `industry_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `industry_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `title` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `summary` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `content_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `content_json` json DEFAULT NULL,
  `rating` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `target_price` decimal(10,2) DEFAULT NULL,
  `current_price` decimal(10,2) DEFAULT NULL,
  `broker_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `analyst_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `publish_time` datetime NOT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `file_url` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `file_hash` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `page_count` int DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_publish_time` (`publish_time`),
  KEY `idx_broker` (`broker_name`),
  KEY `idx_industry` (`industry_code`),
  KEY `idx_type_time` (`report_type`,`publish_time`),
  KEY `idx_stock_code` (`stock_code`)
) ENGINE=InnoDB AUTO_INCREMENT=21236 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `scheduled_task` (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `func_module` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `func_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `args` json DEFAULT (json_array()),
  `kwargs` json DEFAULT (json_object()),
  `trigger_type` enum('cron','date') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'cron',
  `cron_expression` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `run_at` datetime DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `last_run_at` datetime DEFAULT NULL,
  `next_run_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `task_name` (`task_name`),
  CONSTRAINT `chk_trigger_cron` CHECK ((((`trigger_type` = _utf8mb4'cron') and (`cron_expression` is not null)) or ((`trigger_type` = _utf8mb4'date') and (`run_at` is not null))))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stock_financial_scores` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `code` varchar(12) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码',
  `roe` decimal(10,4) NOT NULL COMMENT 'ROE(%)',
  `profit_growth` decimal(12,4) NOT NULL COMMENT '净利润增长率(%)',
  `cash_quality` decimal(8,4) NOT NULL COMMENT '现金流质量',
  `pe` decimal(10,4) NOT NULL COMMENT '市盈率',
  `debt_ratio` decimal(8,4) NOT NULL COMMENT '资产负债率(%)',
  `roe_score` decimal(6,2) NOT NULL COMMENT 'ROE评分',
  `profit_growth_score` decimal(6,2) NOT NULL COMMENT '利润增长评分',
  `cash_quality_score` decimal(6,2) NOT NULL COMMENT '现金流质量评分',
  `pe_score` decimal(6,2) NOT NULL COMMENT 'PE评分',
  `debt_ratio_score` decimal(6,2) NOT NULL COMMENT '负债率评分',
  `composite_score` decimal(6,2) NOT NULL COMMENT '综合评分',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`),
  KEY `idx_composite_score` (`composite_score` DESC),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=168 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='股票财务评分表';

CREATE TABLE IF NOT EXISTS `stock_fundamentals` (
  `fundamental_id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `stock_code` varchar(10) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '股票代码',
  `date` datetime DEFAULT NULL COMMENT '数据日期',
  `open_price` float DEFAULT NULL COMMENT '开盘价',
  `close_price` float DEFAULT NULL COMMENT '收盘价',
  `high_price` float DEFAULT NULL COMMENT '最高价',
  `low_price` float DEFAULT NULL COMMENT '最低价',
  `volume` bigint DEFAULT NULL COMMENT '成交量',
  `pe_ratio` float DEFAULT NULL COMMENT '市盈率 PE',
  `pb_ratio` float DEFAULT NULL COMMENT '市净率 PB',
  `eps` float DEFAULT NULL COMMENT '每股收益 EPS',
  `dividend_yield` float DEFAULT NULL COMMENT '股息率',
  `created_at` datetime DEFAULT NULL COMMENT '入库时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`fundamental_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `stock_news` (
  `news_id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `stock_code` varchar(10) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '关联股票代码',
  `title` text COLLATE utf8mb4_bin COMMENT '新闻标题',
  `content` text COLLATE utf8mb4_bin COMMENT '新闻正文',
  `source` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '新闻来源',
  `publish_time` datetime DEFAULT NULL COMMENT '新闻发布时间',
  `created_at` datetime DEFAULT NULL COMMENT '入库时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`news_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `stocks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `symbol` varchar(25) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `name_en` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `area` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `exchange` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `industry` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `cnspell` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `market` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `act_name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `act_ent_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `securities_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'stock',
  `last_update` datetime DEFAULT NULL,
  `company_desc` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `pe_ratio` float DEFAULT NULL,
  `pb_ratio` float DEFAULT NULL,
  `concepts` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `monitoring` int DEFAULT '0',
  `monitor_by` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'user',
  `ohlc_last` json DEFAULT NULL,
  `setting` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uni_symbol` (`symbol`),
  KEY `idx_securities_type` (`securities_type`),
  KEY `idx_market` (`market`)
) ENGINE=InnoDB AUTO_INCREMENT=37348 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `stocks_fear_greed` (
  `trade_date` date NOT NULL,
  `index_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `close` decimal(18,4) NOT NULL,
  `fear_greed` decimal(5,2) NOT NULL,
  `vol_score` decimal(5,2) NOT NULL,
  `mom_score` decimal(5,2) NOT NULL,
  PRIMARY KEY (`trade_date`,`index_code`) USING BTREE,
  KEY `idx_trade_date` (`trade_date`) USING BTREE,
  KEY `idx_index_code` (`index_code`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `stocks_group` (
  `gid` int NOT NULL,
  `gname` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`gid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `strategy_group` (
  `group_id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `group_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '策略组名称',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `system_logs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `log_type` tinyint NOT NULL COMMENT '日志类型: 1-系统日志, 2-用户操作日志',
  `log_level` tinyint NOT NULL DEFAULT '1' COMMENT '日志级别: 1-DEBUG, 2-INFO, 3-WARN, 4-ERROR, 5-FATAL',
  `module` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '模块名称',
  `action` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '操作动作',
  `user_id` bigint unsigned DEFAULT NULL COMMENT '用户ID（用户操作日志必填）',
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '用户名（冗余存储，便于查询）',
  `ip_address` varchar(45) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT 'IP地址',
  `user_agent` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '用户代理',
  `request_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '请求追踪ID',
  `operation_time` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '操作时间',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '日志内容',
  `extra_data` json DEFAULT NULL COMMENT '扩展数据（JSON格式）',
  `status` tinyint DEFAULT '1' COMMENT '状态: 0-失败, 1-成功',
  `error_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '错误码',
  `error_message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '错误信息',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_status` (`status`),
  KEY `idx_operation_time` (`operation_time`),
  KEY `idx_log_type` (`log_type`),
  KEY `idx_module` (`module`),
  KEY `idx_request_id` (`request_id`),
  KEY `idx_log_level` (`log_level`)
) ENGINE=InnoDB AUTO_INCREMENT=1611 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='系统日志表';

CREATE TABLE IF NOT EXISTS `user_watchlist` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `stock_name` varchar(25) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `stock_code` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `topic` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `desc` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `from_ai` tinyint(1) DEFAULT '0',
  `created_at` datetime DEFAULT NULL,
  `price` float DEFAULT NULL,
  `diff` float DEFAULT NULL,
  `securities_type` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `索引 2` (`stock_code`)
) ENGINE=InnoDB AUTO_INCREMENT=332 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `username` varchar(50) COLLATE utf8mb4_bin NOT NULL COMMENT '登录用户名（唯一）',
  `password_hash` varchar(255) COLLATE utf8mb4_bin NOT NULL COMMENT '密码哈希（bcrypt/pbkdf2，不存明文）',
  `nickname` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '昵称',
  `email` varchar(100) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '邮箱',
  `role` varchar(20) COLLATE utf8mb4_bin NOT NULL COMMENT '角色：admin-管理员, user-普通用户',
  `is_active` int NOT NULL COMMENT '是否启用：0-禁用, 1-启用',
  `last_login_at` datetime DEFAULT NULL COMMENT '最后登录时间',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
