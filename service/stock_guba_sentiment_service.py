"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股散户情绪（股吧文本语义）的读写服务。

设计要点：
  1. 情绪分由**后端公式**计算，不由模型直接给分 —— 模型负责理解文本（输出三分类占比），
     算术交给代码。这样同一份文本换模型重跑，历史序列不会突然跳档。
  2. 写入走 (symbol, trade_date) 唯一键 upsert，重复执行安全（job 是至少一次语义）。
"""

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from models import StockGubaSentiment
from models.database import db_session
from utils.logger import logger


class StockGubaSentimentService:

    # ---------- 打分 ----------

    @staticmethod
    def compute_score(bullish: float, neutral: float, bearish: float) -> float:
        """三分类占比 → 0~100 情绪分（50 = 中性）。

        公式等价于把三档按 看多=100 / 中性=50 / 看空=0 加权平均：
            score = 0.5 + (bullish - bearish) / 200
        占比之和为 100 时，该式与加权平均完全一致（0.27/0.60/0.13 → 57.0）。

        用「看多 - 看空」而不是直接加权，是因为中性占比会随话题热度稀释分母，
        差值形式对中性占比的波动更稳健。
        """
        try:
            b = float(bullish or 0)
            r = float(bearish or 0)
        except (TypeError, ValueError):
            return 50.0
        score = 0.5 + (b - r) / 200.0
        return round(max(0.0, min(1.0, score)) * 100, 2)

    @staticmethod
    def derive_heat_level(post_count: int) -> str:
        """按 24h 帖子数粗分活跃度（阈值来自 2026-10 实测：
        冷门股 0~10 条、中热 30~60 条、热门股 120+ 条）。"""
        try:
            n = int(post_count or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 10:
            return '冷清'
        if n < 60:
            return '正常'
        if n < 200:
            return '活跃'
        return '过热'

    # ---------- 写 ----------

    @staticmethod
    def upsert(symbol: str, trade_date: date, payload: Dict[str, Any]) -> bool:
        """按 (symbol, trade_date) 幂等写入。存在则更新，不存在则插入。"""
        if not symbol or not trade_date:
            logger.warning('upsert called without symbol/trade_date')
            return False
        try:
            row = db_session.query(StockGubaSentiment).filter(
                and_(
                    StockGubaSentiment.symbol == symbol,
                    StockGubaSentiment.trade_date == trade_date,
                )
            ).first()

            if row is None:
                row = StockGubaSentiment(symbol=symbol, trade_date=trade_date)
                db_session.add(row)

            for field, value in payload.items():
                if hasattr(row, field):
                    setattr(row, field, value)

            db_session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f'[guba_sentiment] upsert {symbol} {trade_date} 失败: {e}')
            db_session.rollback()
            return False
        except Exception as e:  # noqa: BLE001
            logger.error(f'[guba_sentiment] upsert {symbol} {trade_date} 异常: {e}')
            db_session.rollback()
            return False

    # ---------- 读 ----------

    @staticmethod
    def get_history(symbol: str, limit: int = 60) -> List[Dict[str, Any]]:
        """按日期倒序取最近 N 条。"""
        try:
            rows = db_session.query(StockGubaSentiment).filter(
                StockGubaSentiment.symbol == symbol
            ).order_by(StockGubaSentiment.trade_date.desc()).limit(limit).all()
            return [r.to_dict() for r in rows] if rows else []
        except Exception as e:  # noqa: BLE001
            logger.error(f'[guba_sentiment] get_history {symbol} 失败: {e}')
            return []

    @staticmethod
    def get_latest(symbol: str) -> Optional[Dict[str, Any]]:
        try:
            row = db_session.query(StockGubaSentiment).filter(
                StockGubaSentiment.symbol == symbol
            ).order_by(StockGubaSentiment.trade_date.desc()).first()
            return row.to_dict() if row else None
        except Exception as e:  # noqa: BLE001
            logger.error(f'[guba_sentiment] get_latest {symbol} 失败: {e}')
            return None

    @staticmethod
    def get_latest_by_symbols(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量取多只股票的最新一条（避免 N+1）。

        用「一次查出全部再在内存里按 symbol 取首条」而不是逐只查询：
        本表每个 symbol 的记录数等同上线的交易日数，量级很小（单股 ≤ 数百行），
        先按 symbol IN (...) 过滤、再按日期倒序，内存取首条是安全的。
        """
        if not symbols:
            return {}
        try:
            rows = db_session.query(StockGubaSentiment).filter(
                StockGubaSentiment.symbol.in_(symbols)
            ).order_by(StockGubaSentiment.symbol, StockGubaSentiment.trade_date.desc()).all()
            latest: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                if r.symbol not in latest:
                    latest[r.symbol] = r.to_dict()
            return latest
        except Exception as e:  # noqa: BLE001
            logger.error(f'[guba_sentiment] get_latest_by_symbols 失败: {e}')
            return {}
