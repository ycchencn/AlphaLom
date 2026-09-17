"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy import Text, DateTime, BigInteger
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Enum, Numeric, Boolean, SmallInteger
from sqlalchemy import Float, DECIMAL, JSON
from sqlalchemy.sql import func
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from typing import Optional, Dict, Any

Base = declarative_base()

db = SQLAlchemy()


class TriggerType(str, Enum):
    CRON = "cron"
    DATE = "date"  # 一次性任务


class Stock(Base):
    __tablename__ = 'stocks'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    ts_code = Column(String(25), unique=True, comment='交易所标准代码，如 000001.SZ / 600519.SH')
    symbol = Column(String(25), comment='股票代码，如 000001 / 600519')
    name = Column(String(50), comment='股票名称')
    name_en = Column(String(50), comment='英文名称')
    area = Column(String(50), comment='地区')
    industry = Column(String(50), comment='所属行业')
    market = Column(String(10), default='cn', comment='市场：cn-沪深, hk-港股, us-美股')
    act_name = Column(String(50), comment='曾用名')
    act_ent_type = Column(String(50), comment='公司类型')
    last_update = Column(DateTime, comment='最后更新时间')
    exchange = Column(String(50), comment='交易所')
    pe_ratio = Column(Float(precision=2), comment='市盈率 PE')
    pb_ratio = Column(Float(precision=2), comment='市净率 PB')
    concepts = Column(Text, comment='概念板块标签（文本）')
    securities_type = Column(String(10), default='stock', comment='证券类型：stock/etf/fund 等')
    monitoring = Column(Integer, default=0, comment='是否纳入监控：0-否, 1-是')
    monitor_by = Column(String(50), comment='监控创建人/来源')
    setting = Column(JSON, default={}, comment='扩展设置（JSON）')
    ohlc_last = Column(JSON, default={}, comment='最近 OHLC 行情快照（JSON）')

    def __repr__(self):
        return f"<Stock(ts_code='{self.ts_code}', name='{self.name}')>"

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'symbol': self.symbol,
            'name': self.name,
            'name_en': self.name_en,
            'area': self.area,
            'industry': self.industry,
            'market': self.market,
            'act_name': self.act_name,
            'act_ent_type': self.act_ent_type,
            'concepts': self.concepts,
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
            'exchange': self.exchange,
            'pe_ratio': self.pe_ratio,
            'pb_ratio': self.pb_ratio,
            'securities_type': self.securities_type,
            'monitoring': self.monitoring,
            'monitor_by': self.monitor_by,
            'setting': self.setting,
            'ohlc_last': self.ohlc_last
        }


# 股票新闻表
class StockNews(db.Model):
    __tablename__ = 'stock_news'

    news_id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    stock_code = Column(String(10), comment='关联股票代码')
    title = Column(Text, comment='新闻标题')
    content = Column(Text, comment='新闻正文')
    source = Column(String(255), comment='新闻来源')
    publish_time = Column(DateTime, comment='新闻发布时间')
    created_at = Column(DateTime, default=datetime.now, comment='入库时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


# 股票基本面表
class StockFundamentals(db.Model):
    __tablename__ = 'stock_fundamentals'

    fundamental_id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    stock_code = Column(String(10), comment='股票代码')
    date = Column(DateTime, comment='数据日期')
    open_price = Column(Float(precision=2), comment='开盘价')
    close_price = Column(Float(precision=2), comment='收盘价')
    high_price = Column(Float(precision=2), comment='最高价')
    low_price = Column(Float(precision=2), comment='最低价')
    volume = Column(BigInteger, comment='成交量')
    pe_ratio = Column(Float(precision=2), comment='市盈率 PE')
    pb_ratio = Column(Float(precision=2), comment='市净率 PB')
    eps = Column(Float(precision=2), comment='每股收益 EPS')
    dividend_yield = Column(Float(precision=2), comment='股息率')
    created_at = Column(DateTime, default=datetime.now, comment='入库时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


# 自选股表
class UserWatchlist(db.Model):
    __tablename__ = 'user_watchlist'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    stock_code = Column(String(10), comment='股票代码')
    stock_name = Column(String(25), comment='股票名称')
    topic = Column(String(50), comment='所属主题/题材')
    desc = Column(String(255), comment='备注说明')
    from_ai = Column(Integer, default=0, comment='是否由 AI 推荐加入：0-否, 1-是')
    price = Column(Float(precision=2), default=0, comment='加入时价格')
    diff = Column(Float(precision=2), default=0, comment='涨跌幅（%）')
    created_at = Column(DateTime, default=datetime.now, comment='加入时间')
    securities_type = Column(String(50), comment='证券类型：stock/etf 等')

    def to_dict(self):
        """
        将对象的属性转换为字典
        :return: 包含对象所有属性的字典
        """
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'topic': self.topic,
            'desc': self.desc,
            'price': self.price,
            'diff': self.diff,
            'from_ai': self.from_ai,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'securities_type': self.securities_type
        }


# 策略组
class StrategyGroup(db.Model):
    __tablename__ = 'strategy_group'

    group_id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    group_name = Column(String(255), comment='策略组名称')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    def to_dict(self):
        return {
            'group_id': self.group_id,
            'group_name': self.group_name,
            'created_at': self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            'updated_at': self.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        }


class BacktestTask(db.Model):
    __tablename__ = 'backtest_tasks'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')  # 自增主键
    backtest_id = Column(String(64), comment='回测唯一ID')
    portfolio_id = Column(Integer, nullable=False, comment='投资组合编号')  # 投资组合编号
    stock_code = Column(String(20), nullable=False, comment='资产代码')  # 资产代码
    stock_name = Column(String(20), nullable=False, comment='资产名称')  # 资产名称
    securities_type = Column(String(20), nullable=False, comment='资产类型')  # 资产类型
    buy_volume = Column(Integer, nullable=False, comment='买入量')  # 买入量
    sell_volume = Column(Integer, nullable=False, comment='卖出量')  # 卖出量
    start_date = Column(Date, nullable=False, comment='开始日期')  # 开始日期
    end_date = Column(Date, nullable=False, comment='结束日期')  # 结束日期
    start_value = Column(DECIMAL(15, 2), nullable=False, comment='初始资金')  # 初始资金
    end_value = Column(DECIMAL(15, 2), nullable=False, comment='结束时的资金')  # 结束时的资金
    annualized_return = Column(DECIMAL(6, 4), comment='年化收益率')  # 年化收益率
    sharp_ratio = Column(DECIMAL(15, 2), comment='夏普比率')  # 夏普比率
    calmar_ratio = Column(DECIMAL(6, 4), comment='卡尔马比率')  # 卡尔马比率
    profit = Column(DECIMAL(15, 2), nullable=False, comment='净利润')  # 净利润
    max_drawdown = Column(DECIMAL(10, 8), comment='最大回撤')  # 最大回撤
    stock_trading_config = Column(JSON, nullable=False, comment='交易配置（JSON）')  # 交易配置，以JSON格式存储
    ai_audit_comment = Column(JSON, comment='AI 评估意见')  # AI 评估意见
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    trade_signal_match = Column(Integer, nullable=False, comment='是否触发当日信号：0-否, 1-是')  # 是否触发当日信号
    last_signal_date = Column(Date, default=None, comment='最近信号触发日期')  # 最近信号触发日期
    last_signal_trade_type = Column(String(32), nullable=False, comment='最近信号触发交易类型')  # 最近信号触发交易类型
    strategy_code = Column(String(32), nullable=True, comment='策略代码')  # 策略代码
    finished = Column(Integer, default=0, comment='回测是否完成：0-进行中, 1-已完成')

    def to_dict(self):
        """
        将对象的属性转换为字典
        :return: 包含对象所有属性的字典
        """
        return {
            'id': self.id,
            'backtest_id': self.backtest_id,
            'portfolio_id': self.portfolio_id,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'securities_type': self.securities_type,
            'buy_volume': self.buy_volume,
            'sell_volume': self.sell_volume,
            'start_date': str(self.start_date),
            'end_date': str(self.end_date),
            'start_value': float(self.start_value),
            'end_value': float(self.end_value),
            'annualized_return': float(self.annualized_return) if self.annualized_return is not None else None,
            'sharp_ratio': float(self.sharp_ratio) if self.sharp_ratio is not None else None,
            'calmar_ratio': float(self.calmar_ratio) if self.calmar_ratio is not None else None,
            'profit': float(self.profit),
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown is not None else None,
            'stock_trading_config': self.stock_trading_config,
            'ai_audit_comment': self.ai_audit_comment,
            'trade_signal_match': self.trade_signal_match,
            'last_signal_trade_type': self.last_signal_trade_type,
            'last_signal_date': self.last_signal_date.strftime('%Y-%m-%d') if self.last_signal_date else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'strategy_code': self.strategy_code
        }


class BacktestTrade(db.Model):
    __tablename__ = 'backtest_trades'

    id = Column(Integer, primary_key=True, comment='自增主键')
    backtest_id = Column(String(64), nullable=False, comment='关联回测ID')
    portfolio_id = Column(Integer, comment='投资组合编号')
    trade_type = Column(String(16), nullable=False, comment='交易类型：buy-买入, sell-卖出')  # 'buy' or 'sell'
    symbol = Column(String(16), nullable=False, comment='标的代码')
    size = Column(Float, nullable=False, comment='成交数量')
    price = Column(Float, nullable=False, comment='成交价格')
    created_at = Column(DateTime, default=datetime.now, comment='成交时间')

    def to_dict(self):
        """
        @brief 将对象的属性转换为字典

        @return: 包含对象所有属性的字典
        @rtype: dict

        @example:
            # 示例用法
            trade = BacktestTrade(...)
            trade_dict = trade.to_dict()
            print(trade_dict)
        """
        return {
            'id': self.id,
            'backtest_id': self.backtest_id,
            'portfolio_id': self.portfolio_id,
            'trade_type': self.trade_type,
            'symbol': self.symbol,
            'size': self.size,
            'price': self.price,
            'created_at': self.created_at if self.created_at else None
        }


class MarketDailyLimit(Base):
    __tablename__ = 'market_daily_limit'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    date = Column(Date, nullable=False, unique=True, comment='交易日期')
    rising = Column(Integer, nullable=False, comment='上涨家数')
    limit_up = Column(Integer, nullable=False, comment='涨停家数')
    falling = Column(Integer, nullable=False, comment='下跌家数')
    limit_down = Column(Integer, nullable=False, comment='跌停家数')
    flat = Column(BigInteger, nullable=False, comment='平盘家数')

    def to_dict(self):
        """将对象转换为字典格式"""
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'rising': self.rising,
            'limit_up': self.limit_up,
            'falling': self.falling,
            'limit_down': float(self.limit_down) if self.limit_down is not None else None,
            'flat': self.flat
        }


class InvestmentPortfolio(Base):
    __tablename__ = 'investment_portfolio'
    portfolio_id = Column(String(36), primary_key=True, comment='UUID组合唯一ID')
    name = Column(String(100), nullable=False, unique=True, comment='组合名称')
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
    portfolio_assets = relationship("PortfolioAssets", back_populates="portfolio")
    desc = Column(Text, comment='组合描述')
    enable = Column(Integer, nullable=False, default=1, comment='是否启用：0-停用, 1-启用')
    market = Column(String(50), nullable=False, default='cn', comment='市场：cn/hk/us 等')
    quantstat_json = Column(JSON, nullable=True, comment='量化绩效统计（JSON）')

    def to_dict(self):
        """将对象转换为字典格式"""
        return {
            'portfolio_id': self.portfolio_id,
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
    portfolio_id = Column(String(36), ForeignKey('investment_portfolio.portfolio_id'), comment='投资组合ID')
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
    portfolio = relationship("InvestmentPortfolio", back_populates="portfolio_assets")

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


class IndexConstituents(Base):
    __tablename__ = 'index_constituents'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    index_code = Column(String(50), nullable=False, default='0', comment='指数代码')
    stock_code = Column(String(50), nullable=True, comment='股票代码')
    stock_name = Column(String(50), nullable=True, comment='股票名称')
    add_date = Column(Date, nullable=True, comment='纳入日期')

    def to_dict(self):
        """
        @brief 将对象转换为字典格式，便于返回 JSON 数据
        @return: 包含指数成分股信息的字典
        @rtype: dict
        """
        return {
            'id': self.id,
            'index_code': self.index_code,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'add_date': self.add_date.isoformat() if self.add_date else None
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


class FuturesBasisWide(Base):
    __tablename__ = 'futures_basis'

    trade_date = Column(Date, primary_key=True, nullable=False, comment='交易日期，如 2025-12-19')
    index_name = Column(String(20), primary_key=True, nullable=False, comment='指数名称：沪深300 / 上证50 / 中证500')
    future_symbol = Column(String(20), nullable=False, comment='主力合约代码，如 IF2603')

    future_close = Column(DECIMAL(precision=18, scale=6), nullable=True, comment='期货收盘价')
    spot_close = Column(DECIMAL(precision=18, scale=6), nullable=True, comment='现货指数收盘价')
    basis = Column(DECIMAL(precision=18, scale=6), nullable=True, comment='贴水 = 期货 - 现货')
    basis_rate_pct = Column(DECIMAL(precision=18, scale=6), nullable=True, comment='贴水率（%）')

    source = Column(String(30), nullable=False, default='akshare_cffex', comment='数据来源')
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='最后更新时间')

    def to_dict(self):
        return {
            'trade_date': self.trade_date.isoformat() if self.trade_date else None,
            'index_name': self.index_name,
            'future_symbol': self.future_symbol,
            'future_close': float(self.future_close) if self.future_close is not None else None,
            'spot_close': float(self.spot_close) if self.spot_close is not None else None,
            'basis': float(self.basis) if self.basis is not None else None,
            'basis_rate_pct': float(self.basis_rate_pct) if self.basis_rate_pct is not None else None,
            'source': self.source,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }


class StockFearGreed(Base):
    __tablename__ = 'stocks_fear_greed'

    trade_date = Column(Date, primary_key=True, nullable=False, comment='交易日期')
    index_code = Column(String(20), nullable=False, comment='指数代码')
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


class LlmPrompt(Base):
    __tablename__ = 'llm_prompts'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    prompt_key = Column(String(128), nullable=False, index=True, comment='Prompt 唯一键，如 news_stock_relation')  # 如 'news_stock_relation'
    name = Column(String(255), nullable=False, comment='Prompt 名称')
    content = Column(Text, nullable=False, comment='Prompt 模板文本')  # Prompt 模板文本
    variables = Column(JSON, nullable=True, comment='模板变量列表（JSON 数组，如 ["content"]）')  # 存为 JSON 字符串，如: ["content"]
    output_format = Column(String(20), nullable=False, default='text', comment='输出格式：text/json_object/json_array')  # 'text' / 'json_object' / 'json_array'
    description = Column(Text, nullable=True, comment='描述说明')
    version = Column(Integer, nullable=False, default=1, comment='版本号')
    is_active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    created_at = Column(DateTime, default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='更新时间')

    def to_dict(self):
        return {
            "id": self.id,
            "prompt_key": self.prompt_key,
            "name": self.name,
            "content": self.content,
            "variables": self.variables,  # 已是 list 或 None（MySQL JSON 自动转 Python 对象）
            "output_format": self.output_format,
            "description": self.description,
            "version": self.version,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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


class SystemLog(Base):
    __tablename__ = 'system_logs'

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='自增主键')
    log_type = Column(SmallInteger, nullable=False, comment='日志类型: 1-系统日志, 2-用户操作日志')
    log_level = Column(SmallInteger, nullable=False, default=2,
                       comment='日志级别: 1-DEBUG, 2-INFO, 3-WARN, 4-ERROR, 5-FATAL')
    module = Column(String(50), nullable=False, comment='模块名称')
    action = Column(String(100), comment='操作动作')
    user_id = Column(BigInteger, comment='用户ID（用户操作日志必填）')
    username = Column(String(50), comment='用户名（冗余存储，便于查询）')
    ip_address = Column(String(45), comment='IP地址')
    user_agent = Column(String(500), comment='用户代理')
    request_id = Column(String(64), comment='请求追踪ID')
    operation_time = Column(DateTime, nullable=False, default=func.now(), comment='操作时间')
    content = Column(Text, comment='日志内容')
    extra_data = Column(JSON, comment='扩展数据（JSON格式）')
    status = Column(SmallInteger, default=1, comment='状态: 0-失败, 1-成功')
    error_code = Column(String(50), comment='错误码')
    error_message = Column(Text, comment='错误信息')
    created_at = Column(DateTime, nullable=False, default=func.now(), comment='创建时间')

    def __repr__(self):
        return f"<SystemLog(id={self.id}, type={self.log_type}, level={self.log_level}, module={self.module})>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "log_type": self.log_type,
            "log_level": self.log_level,
            "module": self.module,
            "action": self.action,
            "user_id": self.user_id,
            "username": self.username,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "operation_time": self.operation_time.isoformat() if self.operation_time else None,
            "content": self.content,
            "extra_data": self.extra_data,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
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


class ScheduledTask(Base):
    __tablename__ = 'scheduled_task'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    task_name = Column(String(100), nullable=False, unique=True, comment='任务名称（唯一）')
    func_module = Column(String(255), nullable=False, comment='函数所在模块路径')
    func_name = Column(String(100), nullable=False, comment='函数名')
    args = Column(JSON, default=[], comment='位置参数（JSON 数组）')
    kwargs = Column(JSON, default={}, comment='关键字参数（JSON 对象）')

    trigger_type = Column(Enum(), nullable=False, default=TriggerType.CRON, comment='触发类型：cron-定时, date-一次性')
    cron_expression = Column(String(100), comment='Cron 表达式（仅当 trigger_type == cron 时有效）')  # 仅当 trigger_type == 'cron' 时有效
    run_at = Column(DateTime, comment='执行时间（仅当 trigger_type == date 时有效）')  # 仅当 trigger_type == 'date' 时有效

    is_active = Column(Boolean, default=True, comment='是否启用')
    last_run_at = Column(DateTime, comment='上次执行时间')
    next_run_at = Column(DateTime, comment='下次执行时间')
    created_at = Column(DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')

    def __repr__(self):
        return f"<ScheduledTask(id={self.id}, task_name='{self.task_name}', type={self.trigger_type})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_name": self.task_name,
            "func_module": self.func_module,
            "func_name": self.func_name,
            "args": self.args or [],
            "kwargs": self.kwargs or {},
            "trigger_type": self.trigger_type,
            "cron_expression": self.cron_expression,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "is_active": self.is_active,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


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
