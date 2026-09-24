/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

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
) ENGINE=InnoDB AUTO_INCREMENT=25704 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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
) ENGINE=InnoDB AUTO_INCREMENT=15563 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `etf_watchlist` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `symbol` varchar(25) NOT NULL COMMENT 'ETF代码，如 159901',
  `name` varchar(100) DEFAULT NULL COMMENT 'ETF名称（加入时从 databull 取，可空）',
  `created_at` datetime DEFAULT NULL COMMENT '加入时间',
  `user_id` int DEFAULT NULL COMMENT '所属用户（users.id）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_symbol` (`user_id`,`symbol`),
  KEY `ix_etf_watchlist_user_id` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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

CREATE TABLE IF NOT EXISTS `index_daily_data` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `symbol` varchar(10) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '指数代码',
  `open` float DEFAULT NULL COMMENT '开盘价',
  `close` float DEFAULT NULL COMMENT '收盘价',
  `high` float DEFAULT NULL COMMENT '最高价',
  `low` float DEFAULT NULL COMMENT '最低价',
  `amplitude` float DEFAULT NULL COMMENT '振幅(%)',
  `chg_pct` float DEFAULT NULL COMMENT '涨跌幅(%)',
  `rfa_amount` float DEFAULT NULL COMMENT '复权成交额',
  `turnover_rate` float DEFAULT NULL COMMENT '换手率(%)',
  `turnover` float DEFAULT NULL COMMENT '成交额',
  `volume` float DEFAULT NULL COMMENT '成交量',
  `date` date DEFAULT NULL COMMENT '交易日期',
  `market` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '市场来源',
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
  UNIQUE KEY `uniq_uid_name` (`uid`,`name`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='投资组合管理表';

CREATE TABLE IF NOT EXISTS `investment_portfolio_copy` (
  `portfolio_id` int NOT NULL AUTO_INCREMENT COMMENT 'UUID组合唯一ID',
  `uid` int DEFAULT NULL,
  `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '组合名称',
  `strategy_type` int DEFAULT '1',
  `total_position_pct` decimal(5,2) NOT NULL,
  `base_currency` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'USD' COMMENT '基准货币',
  `create_time` datetime DEFAULT (now()),
  `update_time` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `position_plan` json DEFAULT NULL,
  `position_plan_reason` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `init_cash` float DEFAULT '1000000',
  `current_cash` float DEFAULT '1000000',
  `llm_base` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'doubao',
  `llm_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `llm_prompt` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `llm_setting` json DEFAULT NULL,
  `desc` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `enable` int DEFAULT '1',
  `market` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'cn',
  `quantstat_json` json DEFAULT NULL,
  PRIMARY KEY (`portfolio_id`) USING BTREE,
  UNIQUE KEY `name` (`name`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=20 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='投资组合管理表';

CREATE TABLE IF NOT EXISTS `llm_conversation_context` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `chat_context` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

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
) ENGINE=InnoDB AUTO_INCREMENT=90445 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

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
) ENGINE=InnoDB AUTO_INCREMENT=1263 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='组合标的持仓记录表';

CREATE TABLE IF NOT EXISTS `portfolio_assets_copy` (
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
  `create_time` datetime DEFAULT (now()),
  `remark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`asset_id`) USING BTREE,
  UNIQUE KEY `uni` (`stock_code`,`portfolio_id`) USING BTREE,
  KEY `portfolio_id` (`portfolio_id`) USING BTREE,
  KEY `stock_code` (`stock_code`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1263 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC COMMENT='组合标的持仓记录表';

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
) ENGINE=InnoDB AUTO_INCREMENT=1324 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `portfolio_daily_summary_copy` (
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
  `created_at` timestamp NULL DEFAULT (now()),
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_date_portfolio` (`date`,`portfolio_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1324 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

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
) ENGINE=InnoDB AUTO_INCREMENT=4367 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='投资组合交易记录表';

CREATE TABLE IF NOT EXISTS `portfolio_transaction_copy` (
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
  `created_at` timestamp NULL DEFAULT (now()),
  `updated_at` timestamp NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `idx_uni` (`date`,`code`,`portfolio_id`) USING BTREE,
  KEY `idx_code` (`code`) USING BTREE,
  KEY `idx_date` (`date`) USING BTREE,
  KEY `idx_portfolio_id` (`portfolio_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=4367 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='投资组合交易记录表';

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
) ENGINE=InnoDB AUTO_INCREMENT=21981 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `sector_daily_stats` (
  `stat_date` date NOT NULL COMMENT '统计日期（上游 stat_date）',
  `sector_type` varchar(10) COLLATE utf8mb4_bin NOT NULL COMMENT '板块级别：SW1/SW2/SW3',
  `sector_name` varchar(50) COLLATE utf8mb4_bin NOT NULL COMMENT '申万板块名称',
  `change_pct` decimal(10,2) DEFAULT NULL COMMENT '涨跌幅（%）',
  `stock_count` int DEFAULT NULL COMMENT '成分股数量',
  `up_count` int DEFAULT NULL COMMENT '上涨家数',
  `down_count` int DEFAULT NULL COMMENT '下跌家数',
  `flat_count` int DEFAULT NULL COMMENT '平盘家数',
  `up_down_ratio` decimal(10,2) DEFAULT NULL COMMENT '涨跌比（上游原值，down=0 时为 100）',
  `top_stock` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '领涨股名称',
  `top_stock_pct` decimal(10,2) DEFAULT NULL COMMENT '领涨股涨跌幅（%）',
  `bottom_stock` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '领跌股名称',
  `bottom_stock_pct` decimal(10,2) DEFAULT NULL COMMENT '领跌股涨跌幅（%）',
  `total_trade_amount` decimal(20,2) DEFAULT NULL COMMENT '总成交额（亿）',
  `update_time` datetime DEFAULT NULL COMMENT '入库时间',
  PRIMARY KEY (`stat_date`,`sector_type`,`sector_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `stock_community_sentiment` (
  `sentiment_id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `stock_code` varchar(10) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '标的代码',
  `platform` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '来源平台',
  `post_content` text COLLATE utf8mb4_bin COMMENT '帖文内容',
  `sentiment_score` float DEFAULT NULL COMMENT '情感得分，范围 -1（极度看空）到 1（极度看多）',
  `user_count` int DEFAULT NULL COMMENT '参与人数',
  `post_time` datetime DEFAULT NULL COMMENT '帖文发布时间',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`sentiment_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

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
) ENGINE=InnoDB AUTO_INCREMENT=172 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='股票财务评分表';

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

CREATE TABLE IF NOT EXISTS `stocks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `symbol` varchar(25) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `name_en` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `province` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL,
  `city` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL,
  `district` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `industry` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `market` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `securities_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'stock',
  `last_update` datetime DEFAULT NULL,
  `pe_ratio` float DEFAULT NULL,
  `pb_ratio` float DEFAULT NULL,
  `concepts` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `company_profile` json DEFAULT NULL,
  `monitoring` int DEFAULT '0',
  `monitor_by` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'user',
  `ohlc_last` json DEFAULT NULL,
  `setting` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uni_symbol` (`symbol`),
  KEY `idx_securities_type` (`securities_type`),
  KEY `idx_market` (`market`)
) ENGINE=InnoDB AUTO_INCREMENT=42770 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `stocks_daily_data` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `symbol` varchar(10) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '标的代码',
  `open` float DEFAULT NULL COMMENT '开盘价',
  `close` float DEFAULT NULL COMMENT '收盘价',
  `high` float DEFAULT NULL COMMENT '最高价',
  `low` float DEFAULT NULL COMMENT '最低价',
  `amplitude` float DEFAULT NULL COMMENT '振幅(%)',
  `chg_pct` float DEFAULT NULL COMMENT '涨跌幅(%)',
  `rfa_amount` float DEFAULT NULL COMMENT '复权成交额',
  `change_amount` float DEFAULT NULL COMMENT '涨跌额',
  `turnover_rate` float DEFAULT NULL COMMENT '换手率(%)',
  `pe_ratio` float DEFAULT NULL COMMENT '市盈率',
  `pb_ratio` float DEFAULT NULL COMMENT '市净率',
  `turnover` float DEFAULT NULL COMMENT '成交额',
  `volume` float DEFAULT NULL COMMENT '成交量',
  `date` date DEFAULT NULL COMMENT '交易日期',
  `market` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '市场来源',
  `securities_type` varchar(20) COLLATE utf8mb4_bin NOT NULL COMMENT '资产类型',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

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
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS `user_stock_pool` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` int NOT NULL COMMENT '所属用户（users.id）',
  `symbol` varchar(25) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '股票代码',
  `market` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '市场：cn/hk/us',
  `monitor_by` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '加入来源标签（沿用原 stocks.monitor_by 的取值习惯）',
  `created_at` datetime DEFAULT NULL COMMENT '加入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_symbol` (`user_id`,`symbol`),
  KEY `ix_user_stock_pool_symbol` (`symbol`),
  KEY `ix_user_stock_pool_user_id` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=130 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `username` varchar(50) COLLATE utf8mb4_bin NOT NULL COMMENT '登录用户名（唯一）',
  `password_hash` varchar(255) COLLATE utf8mb4_bin NOT NULL COMMENT '密码哈希（bcrypt/pbkdf2，不存明文）',
  `nickname` varchar(50) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '昵称',
  `email` varchar(100) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '邮箱（唯一；也是登录账号）',
  `role` varchar(20) COLLATE utf8mb4_bin NOT NULL COMMENT '角色：admin-管理员, user-普通用户',
  `is_active` int NOT NULL COMMENT '是否启用：0-禁用, 1-启用',
  `last_login_at` datetime DEFAULT NULL COMMENT '最后登录时间',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `uniq_email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
