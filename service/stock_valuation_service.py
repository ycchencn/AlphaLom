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
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import StockDailyValuation
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
        """取某只 A 股的 PE-TTM / PB 序列（按交易日升序，走势图用）。"""
        try:
            rows = db_session.query(StockDailyValuation).filter(
                StockDailyValuation.symbol == symbol,
            ).order_by(StockDailyValuation.trade_date.asc()).limit(limit).all()
            return [r.to_dict() for r in rows]
        except SQLAlchemyError as e:
            logger.error(f"valuation get_history failed for {symbol}: {e}")
            return []

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
