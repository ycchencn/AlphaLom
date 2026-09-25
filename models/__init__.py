"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy import Text, DateTime, BigInteger
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Enum, Numeric, Boolean, SmallInteger
from sqlalchemy import Float, DECIMAL, JSON, UniqueConstraint
from sqlalchemy.sql import func
from datetime import datetime
from sqlalchemy.orm import declarative_base, relationship
from typing import Dict, Any

Base = declarative_base()


class TriggerType(str, Enum):
    CRON = "cron"
    DATE = "date"  # 一次性任务


class StockIndustry(Base):
    """股票→行业 权威映射表（持仓行业分布饼图用）。

    为什么单独建表而不是复用 `stocks.industry`：
    `stocks` 是监控股票池，只覆盖被加入监控的票；而投资组合的持仓可能包含
    池外票，导致 `stocks.industry` 关联不上、饼图一堆「其他」。
    本表以 symbol 为主键，覆盖池内+池外所有出现过的票，行业来源 databull 公司资料。
    """
    __tablename__ = 'stock_industry'

    symbol = Column(String(25), primary_key=True, comment='股票代码，如 000001 / 600519')
    industry = Column(String(100), comment='所属行业（证监会/国民经济行业分类）')
    market = Column(String(10), default='cn', comment='市场：cn-沪深, hk-港股, us-美股')
    source = Column(String(20), default='databull', comment='行业来源：databull / stocks')
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'mysql_engine': 'InnoDB'},
    )

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'industry': self.industry,
            'market': self.market,
            'source': self.source,
        }


class Stock(Base):
    __tablename__ = 'stocks'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    symbol = Column(String(25), unique=True, comment='股票代码，如 000001 / 600519（唯一标识）')
    name = Column(String(50), comment='股票名称')
    name_en = Column(String(50), comment='英文名称')
    province = Column(String(50), comment='省')
    city = Column(String(50), comment='市')
    district = Column(String(50), comment='区')
    industry = Column(String(50), comment='所属行业')
    market = Column(String(10), default='cn', comment='市场：cn-沪深, hk-港股, us-美股')
    last_update = Column(DateTime, comment='最后更新时间')
    pe_ratio = Column(Float(precision=2), comment='市盈率 PE')
    pb_ratio = Column(Float(precision=2), comment='市净率 PB')
    concepts = Column(Text, comment='概念板块标签（文本）')
    securities_type = Column(String(10), default='stock', comment='证券类型：stock/etf/fund 等')
    monitoring = Column(Integer, default=0, comment='是否纳入监控：0-否, 1-是')
    monitor_by = Column(String(50), comment='监控创建人/来源')
    setting = Column(JSON, default={}, comment='扩展设置（JSON）')
    ohlc_last = Column(JSON, default={}, comment='最近 OHLC 行情快照（JSON）')
    company_profile = Column(JSON, default={}, comment='公司信息')

    def __repr__(self):
        return f"<Stock(symbol='{self.symbol}', name='{self.name}')>"

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'name_en': self.name_en,
            'province': self.province,
            'city': self.city,
            'district': self.district,
            'industry': self.industry,
            'market': self.market,
            'concepts': self.concepts,
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
            'pe_ratio': self.pe_ratio,
            'pb_ratio': self.pb_ratio,
            'securities_type': self.securities_type,
            'monitoring': self.monitoring,
            'monitor_by': self.monitor_by,
            'setting': self.setting,
            'ohlc_last': self.ohlc_last,
            'company_profile': self.company_profile
        }


# 用户股票池（多用户隔离）：谁关注了哪只票。
#
# 原实现把「关注」直接记在 `stocks.monitoring` 标记位上，而 `stocks.symbol` 是**全局唯一**的
# —— 一只票只能有一个监控状态，两个用户没法各存各的池子。改成本关联表后职责是这样切的：
#   - `user_stock_pool` 是「用户私有」的唯一事实来源（谁加了什么票、什么时候加的）；
#   - `stocks.monitoring` 降级为**并集标记**（「至少有一个用户关注这只票」），
#     由写路径同步维护。日更任务仍按 `monitoring=1` 枚举要更新的标的，
#     **不必改任何 job** —— 这是这次改造风险最小的切法，千万别顺手把它删掉。
#
# ⚠️ 唯一约束必须是 (user_id, symbol) 复合：只给 symbol 加唯一键会让第二个用户
# 加同一只票时静默命中已有行（看起来「加成功了」，其实加到了别人的池子里）。
class UserStockPool(Base):
    __tablename__ = 'user_stock_pool'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户（users.id）')
    symbol = Column(String(25), nullable=False, index=True, comment='股票代码')
    market = Column(String(10), default='cn', comment='市场：cn/hk/us')
    monitor_by = Column(String(50), comment='加入来源标签（沿用原 stocks.monitor_by 的取值习惯）')
    # 分组名称：用户私有标签，NULL/空 = 未分组。分组本身不独立建表，
    # 只是 user_stock_pool 行上的一个标签，便于在股票池页按分组筛选/整理。
    group_name = Column(String(50), default=None, comment='分组名称，NULL/空=未分组')
    created_at = Column(DateTime, default=datetime.now, comment='加入时间')

    # ⚠️ 显式指定 charset/collate：库内历史表里 utf8mb4_bin / utf8mb4_unicode_ci /
    # utf8mb4_0900_ai_ci 三种混用，不指定就会随环境漂移，日后与 stocks JOIN 会撞
    # 1267 Illegal mix of collations。这里与 stocks 对齐用 unicode_ci。
    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', name='uniq_user_symbol'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'mysql_engine': 'InnoDB'},
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'market': self.market,
            'monitor_by': self.monitor_by,
            'group_name': self.group_name or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


# ETF 自选/监控列表（持久化，替代原静态 ETF_MONITOR_LIST）
class EtfWatchlist(Base):
    __tablename__ = 'etf_watchlist'

    # ⚠️ 主键 = 自增 id；唯一约束是 **(user_id, symbol) 复合**，不是 symbol 单列。
    # 原来 symbol 全局唯一 → 同一只 ETF 只能属于一个用户的清单，两个用户没法各存各的。
    # 改复合唯一后：同一用户不能重复加同一只（幂等靠它挡），不同用户互不影响。
    # 不要改成主键 —— 否则 ORM 身份映射在批量查询时会按该列去重。
    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    user_id = Column(Integer, nullable=True, index=True, comment='所属用户（users.id）')
    symbol = Column(String(25), nullable=False, index=True, comment='ETF代码，如 159901')
    name = Column(String(100), comment='ETF名称（加入时从 databull 取，可空）')
    created_at = Column(DateTime, default=datetime.now, comment='加入时间')

    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', name='uniq_user_symbol'),
        {'mysql_charset': 'utf8mb4', 'mysql_engine': 'InnoDB'}
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'name': self.name,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


# 系统配置表（通用 KV）：所有需要在线调整的系统参数都存这里，一张表容纳后续各类设置，
# 不必每加一类设置就建一张表。行内用 setting_group 分组（如 llm_model_setting），
# 同组一次读回；setting_key 全局唯一，形如 "<group>.<名称>"。
class SystemSetting(Base):
    __tablename__ = 'system_setting'

    # ⚠️ 显式指定 charset/collate：库默认虽是 utf8mb4_bin，但历史表里 utf8mb4_bin /
    # utf8mb4_unicode_ci / utf8mb4_0900_ai_ci 三种混用（见 install/database.sql），
    # 不显式指定就会随环境漂移，日后与别的表 JOIN 会撞 1267 Illegal mix of collations。
    # 配置键按精确匹配使用（区分大小写），bin 正合适。
    __table_args__ = (
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_bin', 'mysql_engine': 'InnoDB'}
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    setting_key = Column(String(120), nullable=False, unique=True, index=True,
                         comment='配置键（全局唯一），如 llm_model_setting.stock_dcf_analysis')
    setting_group = Column(String(60), nullable=False, index=True,
                           comment='配置分组，如 llm_model_setting')
    setting_value = Column(JSON, nullable=True,
                           comment='配置值（JSON，可存字符串/数字/布尔/对象/数组）')
    value_type = Column(String(20), nullable=False, default='json',
                        comment='值类型提示：json/string/int/float/bool（供前端渲染表单）')
    description = Column(String(255), nullable=True, comment='说明')
    updated_by = Column(String(50), nullable=True, comment='最后修改人')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    def __repr__(self):
        return f"<SystemSetting(key='{self.setting_key}', value={self.setting_value})>"

    def to_dict(self):
        return {
            'id': self.id,
            'setting_key': self.setting_key,
            'setting_group': self.setting_group,
            'setting_value': self.setting_value,
            'value_type': self.value_type,
            'description': self.description,
            'updated_by': self.updated_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class InvestmentPortfolio(Base):
    __tablename__ = 'investment_portfolio'

    # ⚠️ 线上真实主键是 `int AUTO_INCREMENT`，不是 UUID。
    # 这里原来声明成 String(36)，而 POST 路由生成 `str(uuid.uuid4())` 往里写 ——
    # 线上 sql_mode 为空（非严格模式），uuid 字符串被**静默截断成 0**：
    # 第一次新建落库 id=0（不报错），第二次必然主键冲突失败。
    # 声明 Integer + autoincrement、由数据库分配 id，才是与表结构一致的做法。
    portfolio_id = Column(Integer, primary_key=True, autoincrement=True, comment='组合唯一ID（自增）')
    # 多用户隔离：组合所属用户。DB 列名是历史遗留的 `uid`（早就有这列，只是代码从没读写过），
    # 这里映射成 user_id 便于阅读，**不改列名**（少一次线上 DDL 就少一份风险）。
    user_id = Column('uid', Integer, nullable=True, index=True, comment='所属用户（users.id）')
    # ⚠️ 唯一约束必须是 (user_id, name) 复合：原来 name 是全局唯一，
    # 两个用户不能有同名策略（如都叫「豆包操盘手」）。
    name = Column(String(100), nullable=False, comment='组合名称')
    strategy_type = Column(Integer, nullable=False, default=1, comment='策略类型')
    total_position_pct = Column(DECIMAL(5, 2), nullable=False, comment='总仓位百分比')
    base_currency = Column(String(10), default='USD', comment='基准货币')
    position_plan = Column(JSON, nullable=True, comment='仓位计划（JSON）')
    position_plan_reason = Column(Text, nullable=True, comment='仓位计划理由')
    init_cash = Column(DECIMAL(18, 2), nullable=False, comment='初始资金')
    current_cash = Column(DECIMAL(18, 2), nullable=False, comment='当前资金')
    create_time = Column(DateTime, default=datetime.now, comment='创建时间')
    update_time = Column(DateTime, onupdate=datetime.now, comment='更新时间')
    llm_prompt = Column(Text, default='', comment='大模型提示词')
    llm_setting = Column(JSON, nullable=True, comment='大模型配置（JSON）')
    desc = Column(Text, comment='组合描述')
    enable = Column(Integer, nullable=False, default=1, comment='是否启用：0-停用, 1-启用')
    market = Column(String(50), nullable=False, default='cn', comment='市场：cn/hk/us 等')
    quantstat_json = Column(JSON, nullable=True, comment='量化绩效统计（JSON）')

    __table_args__ = (
        UniqueConstraint(user_id, name, name='uniq_uid_name'),
        {'mysql_charset': 'utf8mb4', 'mysql_engine': 'InnoDB'}
    )

    def to_dict(self):
        """将对象转换为字典格式"""
        return {
            'portfolio_id': self.portfolio_id,
            'user_id': self.user_id,
            'name': self.name,
            'total_position_pct': float(self.total_position_pct) if self.total_position_pct is not None else None,
            'base_currency': self.base_currency,
            'position_plan': self.position_plan,
            'position_plan_reason': self.position_plan_reason,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
            'init_cash': float(self.init_cash) if self.init_cash is not None else None,
            'current_cash': float(self.current_cash) if self.current_cash is not None else None,
            'llm_prompt': self.llm_prompt,
            'llm_setting': self.llm_setting,
            'desc': self.desc,
            'enable': self.enable,
            'strategy_type': int(self.strategy_type),
            'market': self.market,
            'quantstat_json': self.quantstat_json
        }


class PortfolioAssets(Base):
    __tablename__ = 'portfolio_assets'
    asset_id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    # ⚠️ 这里**故意不声明 ForeignKey**：线上 `portfolio_assets.portfolio_id` 是 varchar(36)，
    # 而 `investment_portfolio.portfolio_id` 是 int —— 类型本就不兼容，且线上根本没有外键约束
    # （install/database.sql 里也没有）。保留 ForeignKey 声明会让「空库首次 create_all」
    # 去建一个 int PK ← varchar FK 的约束，MySQL 直接报 3780 无法创建。
    # 曾被两个 relationship() 引用，但那两处 relationship 在全仓从未被遍历使用，已一并删掉。
    portfolio_id = Column(String(36), comment='投资组合ID（与 investment_portfolio.portfolio_id 对应）')
    stock_code = Column(String(20), nullable=False, comment='股票/ETF标的代码')
    asset_name = Column(String(100), nullable=False, comment='标的名称')
    position_pct = Column(DECIMAL(5, 2), nullable=False, default=0.0, comment='标的仓位百分比')
    create_time = Column(DateTime, default=datetime.now, comment='创建时间')
    last_update = Column(DateTime, default=datetime.now, comment='更新时间')
    position_price = Column(Float, nullable=False, comment='最新价格')
    cost_price = Column(Float, nullable=False, comment='持仓价格（成本价）')
    position_size = Column(Integer, nullable=False, comment='持仓数量')
    position_beta = Column(Float, nullable=False, comment='Beta', default=0)
    base_rsi_threshold = Column(Integer, nullable=False, comment='RSI卖出阈值', default=0)
    stop_loss_percent = Column(Float, nullable=False, comment='止损线（%）', default=0)
    take_profit_percent = Column(Float, nullable=False, comment='止盈线（%）', default=0)
    remark = Column(Text, comment='备注')

    def to_dict(self):
        """将对象转换为字典格式"""
        return {
            'asset_id': self.asset_id,
            'portfolio_id': self.portfolio_id,
            # 'code': self.stock_code,
            'name': self.asset_name,
            'stock_code': self.stock_code,
            'asset_name': self.asset_name,
            'position_price': self.position_price,
            'cost_price': self.cost_price,
            'position_size': self.position_size,
            'position_pct': float(self.position_pct) if self.position_pct is not None else None,
            'position_beta': self.position_beta,
            'base_rsi_threshold': self.base_rsi_threshold,
            'stop_loss_percent': self.stop_loss_percent,
            'take_profit_percent': self.take_profit_percent,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'last_update': self.last_update.isoformat() if self.last_update else None,
        }


class MarketNews(Base):
    __tablename__ = 'market_news'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    digest = Column(Text, nullable=False, comment='新闻摘要')
    tags = Column(JSON, nullable=False, default=list, comment='标签列表')
    relation_level = Column(Integer, comment='关联程度等级')
    bullish_level = Column(Integer, nullable=False, default=False, comment='是否看涨')
    relations_stocks = Column(JSON, nullable=False, default=list,
                              comment='关联股票列表，格式为 [{"code": "...", "name": "..."}]')
    relations_imported = Column(Integer, comment='是否已导入个股监控', default=0)
    news_time = Column(DateTime, nullable=False, comment='新闻发布时间')
    news_type = Column(String(50), comment='新闻类型')
    news_md5 = Column(String(50), comment='新闻唯一哈希值')
    sources = Column(String(50), comment='新闻来源')
    url = Column(String(255), comment='新闻来源url')

    def to_dict(self):
        """
        @brief 将对象转换为字典格式，便于返回 JSON 数据
        @return: 包含新闻信息的字典
        @rtype: dict
        """
        return {
            'id': self.id,
            'digest': self.digest,
            'tags': self.tags or [],
            'relation_level': self.relation_level,
            'bullish_level': self.bullish_level,
            'relations_stocks': self.relations_stocks or [],
            'relations_imported': self.relations_imported,
            'news_time': self.news_time.isoformat() if self.news_time else None,
            'news_type': self.news_type,
            'news_md5': self.news_md5,
            'sources': self.sources,
            'url': self.url
        }


class FactorValue(Base):
    __tablename__ = 'factor_values'

    # 联合主键字段（SQLAlchemy 中通过 primary_key=True 定义）
    trade_date = Column(Date, primary_key=True, nullable=False, comment='交易日期，如 2024-12-01')
    ticker = Column(String(20), primary_key=True, nullable=False, comment='股票代码，如 000001.SZ、600519.SH')
    factor_name = Column(String(50), primary_key=True, nullable=False,
                         comment='因子名称，如 pe_ttm, roe_q, momentum_20d')
    value = Column(DECIMAL(precision=18, scale=6), nullable=True, comment='因子值，支持高精度浮点')
    source = Column(String(30), nullable=False, default='custom', comment='数据来源，如 wind, tushare, custom')
    update_time = Column(DateTime, default=datetime.now, comment='执行时间')

    def to_dict(self):
        """
        @brief 将对象转换为字典格式，便于返回 JSON 数据
        @return: 包含因子信息的字典
        @rtype: dict
        """
        return {
            'trade_date': self.trade_date.isoformat() if self.trade_date else None,
            'ticker': self.ticker,
            'factor_name': self.factor_name,
            'value': float(self.value) if self.value is not None else None,
            'source': self.source,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class StockFearGreed(Base):
    __tablename__ = 'stocks_fear_greed'

    # ⚠️ 主键必须是 (trade_date, index_code) 复合主键 —— 与数据库中的 PRIMARY KEY 一致。
    # 曾经只声明 trade_date 为 primary_key，导致 ORM 身份映射把「同一交易日、不同 index_code」
    # 的多行当成同一个对象：一次查出多行时 SQLAlchemy 会按主键去重，静默只保留第一行。
    # 单条查询（filter_by(index_code=...)）恰好只命中一行所以一直没暴露，
    # 直到做批量查询（一次取多个 index_code 的最新值）才表现为「只返回一只票的数据」。
    trade_date = Column(Date, primary_key=True, nullable=False, comment='交易日期')
    index_code = Column(String(20), primary_key=True, nullable=False, comment='指数代码')
    close = Column(Numeric(precision=18, scale=4), nullable=False, comment='收盘点位')
    fear_greed = Column(Numeric(precision=5, scale=2), nullable=False, comment='恐惧贪婪综合指数')
    vol_score = Column(Numeric(precision=5, scale=2), nullable=False, comment='波动率分项得分')
    mom_score = Column(Numeric(precision=5, scale=2), nullable=False, comment='动量分项得分')

    def to_dict(self):
        return {
            "trade_date": self.trade_date.isoformat(),
            "index_code": self.index_code,
            "close": float(self.close),
            "fear_greed": float(self.fear_greed),
            "vol_score": float(self.vol_score),
            "mom_score": float(self.mom_score)
        }


class DailyPnLRecord(Base):
    __tablename__ = 'daily_pnl_records'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    date = Column(Date, nullable=False, index=True, comment='交易日期')  # 交易日期
    portfolio_id = Column(String(50), nullable=False, index=True, comment='组合ID')  # 组合ID
    stock_code = Column(String(20), nullable=False, index=True, comment='股票代码')  # 股票代码
    stock_name = Column(String(50), nullable=True, comment='股票名称')  # 股票名称
    position_size = Column(Integer, nullable=True, comment='持仓数量')  # 持仓数量
    cost_price = Column(DECIMAL(12, 4), nullable=True, comment='成本价')  # 成本价
    close_price = Column(DECIMAL(12, 4), nullable=True, comment='当日收盘价')  # 当日收盘价
    market_value = Column(DECIMAL(18, 2), nullable=True, comment='市值 = size * close')  # 市值 = size * close
    unrealized_pnl = Column(DECIMAL(18, 2), nullable=True, comment='浮动盈亏金额')  # 浮动盈亏金额
    pnl_pct = Column(DECIMAL(10, 4), nullable=True, comment='浮动盈亏百分比（%）')  # 浮动盈亏百分比（%）
    total_assets = Column(DECIMAL(18, 2), nullable=True, comment='组合总资产（冗余）')  # 组合总资产（冗余）
    cash_balance = Column(DECIMAL(18, 2), nullable=True, comment='现金余额')  # 现金余额

    created_at = Column(DateTime, default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='更新时间')

    # 唯一约束（防止同一天重复插入）
    __table_args__ = (
        # MySQL 支持命名唯一索引
        {'mysql_charset': 'utf8mb4', 'mysql_engine': 'InnoDB'}
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "portfolio_id": self.portfolio_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "position_size": self.position_size,
            "cost_price": float(self.cost_price) if self.cost_price is not None else None,
            "close_price": float(self.close_price) if self.close_price is not None else None,
            "market_value": float(self.market_value) if self.market_value is not None else None,
            "unrealized_pnl": float(self.unrealized_pnl) if self.unrealized_pnl is not None else None,
            "pnl_pct": float(self.pnl_pct) if self.pnl_pct is not None else None,
            "total_assets": float(self.total_assets) if self.total_assets is not None else None,
            "cash_balance": float(self.cash_balance) if self.cash_balance is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PortfolioDailySummary(Base):
    __tablename__ = 'portfolio_daily_summary'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    date = Column(Date, nullable=False, unique=True, index=True, comment='交易日期（组合级唯一）')  # 交易日期（组合级唯一）
    portfolio_id = Column(String(50), nullable=False, index=True, comment='组合ID')  # 组合ID
    total_assets = Column(DECIMAL(18, 2), nullable=False, comment='总资产')  # 总资产
    total_unrealized_pnl = Column(DECIMAL(18, 2), nullable=False, comment='总浮动盈亏')  # 总浮动盈亏
    total_pnl_pct = Column(DECIMAL(10, 4), nullable=False, comment='总盈亏%')  # 总盈亏%
    position_ratio = Column(DECIMAL(5, 4), nullable=False, comment='仓位比例（0~1）')  # 仓位比例（0～1）
    cash_balance = Column(DECIMAL(18, 2), nullable=False, comment='现金余额')  # 现金余额
    daily_pnl_change = Column(Float, default=0.0, comment='相对前一日的变化')  # 相对于前一日的变化
    cumulative_realized_pnl = Column(Float, default=0.0, comment='累计已实现盈亏')
    created_at = Column(DateTime, default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='更新时间')

    __table_args__ = (
        {'mysql_charset': 'utf8mb4', 'mysql_engine': 'InnoDB'}
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "portfolio_id": self.portfolio_id,
            "total_assets": float(self.total_assets),
            "total_unrealized_pnl": float(self.total_unrealized_pnl),
            "total_pnl_pct": float(self.total_pnl_pct),
            "position_ratio": float(self.position_ratio),
            "cash_balance": float(self.cash_balance),
            "daily_pnl_change": float(self.daily_pnl_change),
            "cumulative_realized_pnl": self.cumulative_realized_pnl,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PortfolioTransaction(Base):
    __tablename__ = 'portfolio_transaction'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    date = Column(Date, nullable=False, comment='交易日期')
    action = Column(Enum('BUY', 'SELL', name='action_type'), nullable=False, comment='交易动作：BUY-买入, SELL-卖出')
    code = Column(String(20), nullable=False, comment='标的代码')
    name = Column(String(100), nullable=False, comment='标的名称')
    qty = Column(Integer, nullable=False, comment='成交数量')
    price = Column(Numeric(precision=15, scale=4), nullable=False, comment='成交价格')
    amount = Column(Numeric(precision=18, scale=2), nullable=False, comment='成交金额')
    realized_pnl = Column(Numeric(precision=18, scale=2), default=0.00, comment='已实现盈亏')
    portfolio_id = Column(Integer, nullable=False, comment='投资组合编号')
    created_at = Column(DateTime, default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return f"<PortfolioTransaction(code={self.code}, action={self.action}, qty={self.qty})>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "action": self.action,
            "code": self.code,
            "name": self.name,
            "qty": self.qty,
            "price": float(self.price),
            "amount": float(self.amount),
            "realized_pnl": float(self.realized_pnl),
            "portfolio_id": self.portfolio_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchReport(Base):
    __tablename__ = 'research_reports'

    # === 主键 ===
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='自增主键')

    # === 核心分类 ===
    # 1:个股研报, 2:行业研报, 3:宏观/市场策略
    report_type = Column(SmallInteger, nullable=False, comment='研报类型: 1-个股, 2-行业, 3-宏观/策略')

    # 标的信息 (个股研报必填，其他为null)
    stock_code = Column(String(20), nullable=True, index=True, comment='股票代码 (如: 600519.SH)')
    stock_name = Column(String(100), nullable=True, comment='股票名称')

    # 行业信息
    industry_code = Column(String(20), nullable=True, index=True, comment='行业代码 (申万/中信)')
    industry_name = Column(String(100), nullable=True, comment='行业名称')

    # === 内容元数据 ===
    title = Column(String(500), nullable=False, comment='研报标题')
    summary = Column(Text, nullable=True, comment='摘要/核心观点')
    content_text = Column(Text, nullable=True, comment='全文内容 (用于检索)')
    content_json = Column(JSON, nullable=True, comment='结构化内容（JSON，如估值/图表数据）')

    # 评级与目标价
    rating = Column(String(50), nullable=True, comment='投资评级 (买入/增持/中性/卖出)')
    target_price = Column(DECIMAL(10, 2), nullable=True, comment='目标价格')
    current_price = Column(DECIMAL(10, 2), nullable=True, comment='发布时股价')

    # === 来源与作者 ===
    broker_name = Column(String(100), nullable=False, comment='券商机构名称')
    analyst_name = Column(String(100), nullable=True, comment='分析师姓名 (多人逗号分隔)')

    # 时间
    publish_time = Column(DateTime, nullable=False, comment='研报发布时间')
    created_at = Column(DateTime, nullable=False, default=func.now(), comment='入库时间')

    def __repr__(self):
        return f"<ResearchReport(id={self.id}, type={self.report_type}, stock={self.stock_code}, broker={self.broker_name})>"

    def to_dict(self) -> Dict[str, Any]:
        """
        将模型对象转换为字典，处理 datetime 和 DECIMAL 类型序列化
        """
        return {
            "id": self.id,
            "report_type": self.report_type,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "industry_code": self.industry_code,
            "industry_name": self.industry_name,
            "title": self.title,
            "summary": self.summary,
            # content_text 可能很大，按需决定是否放入字典
            "content_text": self.content_text,
            "content_json": self.content_json,
            "rating": self.rating,
            "target_price": float(self.target_price) if self.target_price else None,
            "current_price": float(self.current_price) if self.current_price else None,
            "broker_name": self.broker_name,
            "analyst_name": self.analyst_name,
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    # === 辅助属性 ===
    @property
    def is_stock_report(self) -> bool:
        return self.report_type == 1

    @property
    def is_market_report(self) -> bool:
        return self.report_type in [2, 3]


class LlmConversationContext(Base):
    __tablename__ = 'llm_conversation_context'
    # 表级别字符集与排序规则（对应原来的 COLLATE utf8mb4_bin）
    __table_args__ = {
        'mysql_charset': 'utf8mb4',
        'mysql_collate': 'utf8mb4_bin',
    }

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    chat_id = Column(String(50, collation='utf8mb4_bin'), nullable=True, default=None, comment='会话ID')
    chat_context = Column(Text, nullable=True, default=None, comment='会话上下文内容')
    created_at = Column(DateTime, nullable=True, default=None, comment='创建时间')
    updated_at = Column(DateTime, nullable=True, default=None, comment='更新时间')

    def __repr__(self):
        return f"<LlmConversationContext(id={self.id}, chat_id='{self.chat_id}')>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "chat_context": self.chat_context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AppLog(Base):
    __tablename__ = 'app_logs'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    timestamp = Column(DateTime, nullable=False, index=True, comment='日志时间戳')
    level = Column(String(16), nullable=False, index=True, comment='日志级别')
    logger = Column(String(64), comment='logger 名称')
    message = Column(Text, comment='日志消息')
    module = Column(String(64), comment='模块名')
    func = Column(String(64), comment='函数名')
    line = Column(Integer, comment='行号')
    created_at = Column(DateTime, comment='入库时间')  # SQLAlchemy 里可以 server_default 或手动填

    def __repr__(self):
        return f"<AppLog(id={self.id}, level={self.level}, message={self.message[:30]})>"

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'level': self.level,
            'logger': self.logger,
            'message': self.message,
            'module': self.module,
            'func': self.func,
            'line': self.line,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'level': self.level,
            'logger': self.logger,
            'message': self.message,
            'module': self.module,
            'func': self.func,
            'line': self.line,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'level': self.level,
            'logger': self.logger,
            'message': self.message,
            'module': self.module,
            'func': self.func,
            'line': self.line,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'level': self.level,
            'logger': self.logger,
            'message': self.message,
            'module': self.module,
            'func': self.func,
            'line': self.line,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'level': self.level,
            'logger': self.logger,
            'message': self.message,
            'module': self.module,
            'func': self.func,
            'line': self.line,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class StockFinancialScore(Base):
    __tablename__ = 'stock_financial_scores'

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='自增主键')
    code = Column(String(12), nullable=False, unique=True, index=True, comment='股票代码')
    roe = Column(DECIMAL(10, 4), nullable=False, comment='净资产收益率 ROE（原始值）')
    profit_growth = Column(DECIMAL(12, 4), nullable=False, comment='利润增长率（原始值，%）')
    cash_quality = Column(DECIMAL(8, 4), nullable=False, comment='现金流质量（原始值）')
    pe = Column(DECIMAL(10, 4), nullable=False, comment='市盈率 PE（原始值）')
    debt_ratio = Column(DECIMAL(8, 4), nullable=False, comment='资产负债率（原始值，%）')
    roe_score = Column(DECIMAL(6, 2), nullable=False, comment='ROE 维度得分')
    profit_growth_score = Column(DECIMAL(6, 2), nullable=False, comment='利润增长维度得分')
    cash_quality_score = Column(DECIMAL(6, 2), nullable=False, comment='现金流质量维度得分')
    pe_score = Column(DECIMAL(6, 2), nullable=False, comment='估值（PE）维度得分')
    debt_ratio_score = Column(DECIMAL(6, 2), nullable=False, comment='负债率维度得分')
    composite_score = Column(DECIMAL(6, 2), nullable=False, index=True, comment='综合得分')
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return (f"<StockFinancialScore(id={self.id}, code={self.code}, "
                f"composite_score={self.composite_score})>")

    def to_dict(self):
        """转为 dict，方便 JSON 序列化"""
        return {
            'id': self.id,
            'code': self.code,
            'roe': float(self.roe),
            'profit_growth': float(self.profit_growth),
            'cash_quality': float(self.cash_quality),
            'pe': float(self.pe),
            'debt_ratio': float(self.debt_ratio),
            'roe_score': float(self.roe_score),
            'profit_growth_score': float(self.profit_growth_score),
            'cash_quality_score': float(self.cash_quality_score),
            'pe_score': float(self.pe_score),
            'debt_ratio_score': float(self.debt_ratio_score),
            'composite_score': float(self.composite_score),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# 用户表（登录认证）
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    username = Column(String(50), nullable=False, unique=True, comment='登录用户名（唯一）')
    password_hash = Column(String(255), nullable=False, comment='密码哈希（bcrypt/pbkdf2，不存明文）')
    nickname = Column(String(50), nullable=True, comment='昵称')
    email = Column(String(100), nullable=True, comment='邮箱')
    role = Column(String(20), nullable=False, default='user', comment='角色：admin-管理员, user-普通用户')
    is_active = Column(Integer, nullable=False, default=1, comment='是否启用：0-禁用, 1-启用')
    last_login_at = Column(DateTime, nullable=True, comment='最后登录时间')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    # ⚠️ email 上有唯一索引：邮箱也是登录凭证（`UserService.find_by_identifier` 会
    # 在用户名没命中时按邮箱查），重复邮箱会让「邮箱登录」退化成随机进某个账号。
    # MySQL 唯一索引允许多个 NULL，所以「不填邮箱」不受影响 —— 写入时统一把空值
    # 归一化成 NULL（`UserService.normalize_email`），别写空串。
    __table_args__ = (
        UniqueConstraint('email', name='uniq_email'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_bin', 'mysql_engine': 'InnoDB'},
    )

    def to_dict(self):
        """转为字典，隐藏密码哈希等敏感字段"""
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SectorDailyStat(Base):
    """申万行业每日涨跌快照（支撑板块轮动图）。

    数据源：上游 `/cn/market/sector_data/{sw1|sw2|sw3}`。

    ⚠️ 上游**只返回最新一个交易日**（实测三个级别返回的 stat_date 全部相同），没有
    「按日期取历史」的接口，因此本表的历史只能靠日更任务逐日累积 —— 越早开始跑，
    轮动图的回溯窗口越长。不要试图用某次请求「补齐」历史，上游给不出。

    ⚠️ 主键必须是 (stat_date, sector_type, sector_name) 复合主键：
      - 只声明 stat_date 做 primary_key 会让 ORM 身份映射把「同一天不同板块」当成
        同一行，一次查出多行时静默去重只剩第一行（`stocks_fear_greed` 上踩过一模一样的坑）。
      - `sector_type` 必须进主键，因为 sw1/sw2/sw3 的板块名理论上可能重名（如「银行」
        既可能是一级也可能出现在二级）。
    """

    __tablename__ = 'sector_daily_stats'

    stat_date = Column(Date, primary_key=True, nullable=False, comment='统计日期（上游 stat_date）')
    sector_type = Column(String(10), primary_key=True, nullable=False, comment='板块级别：SW1/SW2/SW3')
    sector_name = Column(String(50), primary_key=True, nullable=False, comment='申万板块名称')

    change_pct = Column(Numeric(precision=10, scale=2), comment='涨跌幅（%）')
    stock_count = Column(Integer, comment='成分股数量')
    up_count = Column(Integer, comment='上涨家数')
    down_count = Column(Integer, comment='下跌家数')
    flat_count = Column(Integer, comment='平盘家数')
    # ⚠️ 上游的 up_down_ratio 语义不稳定：当 down_count=0 时它直接给 100.0（sw2 实测），
    # 而当涨跌家数都极小时又会给出正常比值。落库时**原样存**，做轮动图要自己重算，
    # 不要把这个字段当成可靠的「涨跌比」。
    up_down_ratio = Column(Numeric(precision=10, scale=2), comment='涨跌比（上游原值，down=0 时为 100）')
    top_stock = Column(String(50), comment='领涨股名称')
    top_stock_pct = Column(Numeric(precision=10, scale=2), comment='领涨股涨跌幅（%）')
    bottom_stock = Column(String(50), comment='领跌股名称')
    bottom_stock_pct = Column(Numeric(precision=10, scale=2), comment='领跌股涨跌幅（%）')
    total_trade_amount = Column(Numeric(precision=20, scale=2), comment='总成交额（亿）')
    # ⚠️ 上游 total_market_cap / avg_turnover 实测**恒为 0.0**，落库无意义，故不建列。
    update_time = Column(DateTime, default=datetime.now, comment='入库时间')

    def to_dict(self):
        def _f(v):
            return float(v) if v is not None else None

        return {
            'stat_date': self.stat_date.isoformat() if self.stat_date else None,
            'sector_type': self.sector_type,
            'sector_name': self.sector_name,
            'change_pct': _f(self.change_pct),
            'stock_count': self.stock_count,
            'up_count': self.up_count,
            'down_count': self.down_count,
            'flat_count': self.flat_count,
            'up_down_ratio': _f(self.up_down_ratio),
            'top_stock': self.top_stock,
            'top_stock_pct': _f(self.top_stock_pct),
            'bottom_stock': self.bottom_stock,
            'bottom_stock_pct': _f(self.bottom_stock_pct),
            'total_trade_amount': _f(self.total_trade_amount),
            'update_time': self.update_time.isoformat() if self.update_time else None,
        }


class LlmAgent(Base):
    """用户自定义智能体（对话配置）。

    每个用户可自由增删智能体，同用户下 name 唯一。
    platform/model 用于运行时对接下游 LLM，system_prompt 作为对话的 system message。
    """
    __tablename__ = 'llm_agent'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户（users.id）')
    name = Column(String(64), nullable=False, default='', comment='智能体名称')
    emoji = Column(String(8), nullable=False, default='🤖', comment='头像 emoji')
    platform = Column(String(32), nullable=False, default='', comment='大模型平台标识')
    model = Column(String(128), nullable=False, default='', comment='模型名称')
    system_prompt = Column(Text, nullable=False, default='', comment='系统提示词')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uniq_user_name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'mysql_engine': 'InnoDB'},
    )

    def __repr__(self):
        return f"<LlmAgent(id={self.id}, user_id={self.user_id}, name='{self.name}')>"

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'emoji': self.emoji,
            'platform': self.platform,
            'model': self.model,
            'system_prompt': self.system_prompt,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class LlmTokenUsage(Base):
    """每次 LLM 调用的 token 消耗与对话输入输出明细。

    接入点：LLMBase / LLMBaseAsync 的各 create_completion 调用处（见 llms/llm_base.py、
    llms/usage_recorder.py）。记录粒度 = 单次 LLM API 调用（工具调用多轮会记多条）。
    user_id 来自请求级 ContextVar（后台 job 无请求上下文则为 NULL）；
    scene/platform 来自 get_model_by_setting 写入实例的属性。
    """

    __tablename__ = 'llm_token_usage'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    user_id = Column(Integer, nullable=True, index=True, comment='调用者用户（users.id）；后台任务为 NULL')
    scene = Column(String(50), nullable=True, index=True, comment='业务场景/LLM 配置名，如 stock_dcf_analysis / chat')
    platform = Column(String(32), nullable=True, comment='平台标识：deepseek/volcengine/siliconflow/aliyun/zhipu')
    model = Column(String(128), nullable=False, comment='模型名称')
    prompt_tokens = Column(Integer, default=0, comment='输入 token 数')
    completion_tokens = Column(Integer, default=0, comment='输出 token 数')
    total_tokens = Column(Integer, default=0, comment='总 token 数')
    input_text = Column(Text, nullable=True, comment='对话输入（messages 拼接，截断到 6000 字）')
    output_text = Column(Text, nullable=True, comment='模型输出文本（截断到 6000 字）')
    created_at = Column(DateTime, default=datetime.now, index=True, comment='调用时间')

    __table_args__ = (
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'mysql_engine': 'InnoDB'},
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'scene': self.scene,
            'platform': self.platform,
            'model': self.model,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'input_text': self.input_text,
            'output_text': self.output_text,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
