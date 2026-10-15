"""
 * @author Yc
 * 个股每日估值快照的读写（PE-TTM / PB），支撑个股详情页顶部报价与基本面走势图。

 * 数据来源：databull `get_stock_info` —— 返回 `pe_ttm / pb / valuation_date`
 * （**仅 A 股有效**，港股/美股/ETF 调用直接 500）。所以这张表天然只存 A 股，
 * 与「PE-TTM 只展示 A 股」的产品口径一致。
 *
 * 数据由日更任务 `job.job_update_stock_valuation_daily.job_update_stock_valuation_daily`
 * 盘后落库（逐日累积，像恐贪 / 板块快照一样）。接口侧只读。
"""

from datetime import date
import pandas as pd
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import Stock, StockDailyValuation
from models.database import db_session
from utils.logger import logger

# 走势图默认返回的交易日上限（≈ 两年半，足够看估值中枢回归）
DEFAULT_HISTORY_LIMIT = 600


def _to_float(v) -> Optional[float]:
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class StockValuationService:

    # ─────────────────────────── 写操作 ───────────────────────────

    @staticmethod
    def upsert_daily(symbol: str, trade_date, pe_ttm=None, pb=None, total_volume=None) -> bool:
        """写入某只 A 股某交易日的估值快照（幂等：已存在则更新数值字段）。

        ⚠️ 必须幂等：日更任务可能被重复触发（手动重跑 / 队列重投），
        按 (symbol, trade_date) 唯一键 upsert，避免 Duplicate 报错。
        """
        try:
            item = db_session.query(StockDailyValuation).filter(
                StockDailyValuation.symbol == symbol,
                StockDailyValuation.trade_date == trade_date,
            ).first()
            if item:
                item.pe_ttm = _to_float(pe_ttm)
                item.pb = _to_float(pb)
                item.total_volume = _to_float(total_volume)
            else:
                item = StockDailyValuation(
                    symbol=symbol,
                    trade_date=trade_date,
                    pe_ttm=_to_float(pe_ttm),
                    pb=_to_float(pb),
                    total_volume=_to_float(total_volume),
                )
                db_session.add(item)
            db_session.commit()
            return True
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"valuation upsert duplicate for {symbol} {trade_date}")
            return False
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"valuation upsert failed for {symbol} {trade_date}: {e}")
            return False

    @staticmethod
    def sync_latest_to_stocks(symbol: str, pe_ttm=None) -> bool:
        """把 PE-TTM **最新值**写回 `stocks.pe_ratio`（个股监控列表直接读这张表）。

        ⚠️ 为什么回写而不是列表时实时查估值表：
        列表接口（/stocks_monitored）一次返回几百只票，若对每只再查一次
        stock_daily_valuation 就是 N+1（列表已有恐贪/因子的 N+1 教训）。
        把最新值在日更时写进 stocks 表（pe_ratio 字段本就存在、从未被使用），
        列表接口读 `stocks.to_dict()` 就有 pe_ratio，零额外查询。

        只对 A 股调用（非 A 股上游无 PE-TTM，会写 null，列表据此不展示）。
        单条 UPDATE 语句，不加载整行 ORM 对象，全池几百只也只多几百次轻量 UPDATE。

        ⚠️ 写侧防御：pe_ttm **缺失或 <= 0 一律不写、不覆盖**。PE-TTM 物理恒为正，
        <= 0 必为无效值（上游当日未更新 / 暂缺 / 亏损股常返回 0 或负值）。历史版本
        曾把负值原样写进 stocks.pe_ratio，造成监控列表把脏值显示成「亏损」（详见
        commit a293bb2 的修复说明）。此处做最后一道闸：宁可不更新、保留上次有效值，
        也绝不让脏值进入列表数据源。
        """
        try:
            valid = _to_float(pe_ttm)
            if valid is None or valid <= 0:
                return False
            db_session.query(Stock).filter(Stock.symbol == symbol).update(
                {'pe_ratio': valid, 'last_update': func.now()},
                synchronize_session=False,
            )
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"valuation sync_to_stocks failed for {symbol}: {e}")
            return False

    # ─────────────────────────── 读操作 ───────────────────────────

    @staticmethod
    def get_latest(symbol: str) -> Optional[Dict[str, Any]]:
        """取某只 A 股**最新**一条估值快照（顶部报价用）；无数据返回 None。"""
        try:
            row = db_session.query(StockDailyValuation).filter(
                StockDailyValuation.symbol == symbol,
            ).order_by(StockDailyValuation.trade_date.desc()).first()
            return row.to_dict() if row else None
        except SQLAlchemyError as e:
            logger.error(f"valuation get_latest failed for {symbol}: {e}")
            return None

    @staticmethod
    def get_history(symbol: str, limit: int = DEFAULT_HISTORY_LIMIT) -> List[Dict[str, Any]]:
        """取某只 A 股的 PE-TTM / PB 序列（**最近** `limit` 个交易日，升序，走势图用）。

        ⚠️ 必须取「最近」而非「最早」：原实现 order_by(trade_date.asc()).limit(limit)
        返回的是该标的有记录以来**最早**的 limit 天，老股（历史 > limit）的走势图会
        退化成 2 年多以前的估值、latest 也变成窗口末尾的老值。改为按降序取最近 limit
        天再反转回升序，保证走势图与顶部报价都是「当前」数据。

        ⚠️ pe_ttm / pb <= 0 视为无效（上游当日未更新 / 亏损股常返回 0），置 None
        （前端断点），避免历史上误写入的 0 污染 PE-TTM 走势。
        """
        try:
            rows = db_session.query(StockDailyValuation).filter(
                StockDailyValuation.symbol == symbol,
            ).order_by(StockDailyValuation.trade_date.desc()).limit(limit).all()
            result = []
            for r in reversed(rows):  # 反转回升序，保持前端/ECharts 约定（x 轴递增）
                d = r.to_dict()
                if d['pe_ttm'] is not None and d['pe_ttm'] <= 0:
                    d['pe_ttm'] = None
                if d['pb'] is not None and d['pb'] <= 0:
                    d['pb'] = None
                result.append(d)
            return result
        except SQLAlchemyError as e:
            logger.error(f"valuation get_history failed for {symbol}: {e}")
            return []

    @staticmethod
    def get_history_frame(symbols, limit: int = DEFAULT_HISTORY_LIMIT) -> pd.DataFrame:
        """批量取多只 A 股 pe_ttm 历史，返回宽表：index=交易日(str 'YYYY-MM-DD')，columns=symbol，value=pe_ttm。

        用于「ETF 市盈率」因子：把成分股 PE 按交易日对齐后再加权。单只/全部无数据时返回空 DataFrame。
        pe_ttm 为 NULL 的行直接跳过（不进入宽表，对应位置保持 NaN）。
        """
        if not symbols:
            return pd.DataFrame()
        try:
            rows = (
                db_session.query(
                    StockDailyValuation.symbol,
                    StockDailyValuation.trade_date,
                    StockDailyValuation.pe_ttm,
                )
                .filter(StockDailyValuation.symbol.in_(symbols))
                .order_by(StockDailyValuation.trade_date)
                .all()
            )
            if not rows:
                return pd.DataFrame()
            data = {}
            for sym, td, pe in rows:
                if pe is None:
                    continue
                data.setdefault(sym, {})[td.strftime('%Y-%m-%d')] = float(pe)
            return pd.DataFrame(data)  # index=str date, columns=symbol
        except SQLAlchemyError as e:
            logger.error(f"valuation get_history_frame failed: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_last_trade_date() -> Optional[date]:
        """库里最新的估值交易日（判断数据新鲜度用）。"""
        try:
            row = db_session.query(StockDailyValuation).order_by(
                StockDailyValuation.trade_date.desc()).first()
            return row.trade_date if row else None
        except SQLAlchemyError as e:
            logger.error(f"valuation get_last_trade_date failed: {e}")
            return None
