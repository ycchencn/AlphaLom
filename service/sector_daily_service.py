"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 申万行业每日快照的读写（支撑板块轮动图）。

 数据由日更任务 `job.job_update_sector_daily.job_update_sector_daily` 落库，
  `/market/sectors` 优先从这里读、读不到再回退上游。
"""

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import SectorDailyStat
from models.database import db_session
from utils.logger import logger

# 上游 sector_type 是 SW1/SW2/SW3（大写），入参习惯用小写 sw1/sw2/sw3
SECTOR_TYPES = ('sw1', 'sw2', 'sw3')


def normalize_sector_type(sector_type: str) -> Optional[str]:
    """把 sw1 / SW1 / Sw1 统一成 DB 里存的 SW1；非法值返回 None。"""
    if not sector_type:
        return None
    t = str(sector_type).strip().lower()
    return t.upper() if t in SECTOR_TYPES else None


def _to_float(v) -> Optional[float]:
    """上游偶尔给字符串或 None，统一转 float；转不动就返回 None（不抛）。"""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> Optional[int]:
    f = _to_float(v)
    return int(f) if f is not None else None


class SectorDailyService:

    # ─────────────────────────── 写操作 ───────────────────────────

    @staticmethod
    def upsert_daily(rows: List[Dict[str, Any]]) -> int:
        """写入某一天的板块快照，返回成功写入的行数。

        ⚠️ **必须幂等**：队列（Redis Stream，prefetch=1）的失败重投语义是
        「至少一次」，同一个 job 可能被投递两次。这里按复合主键
        (stat_date, sector_type, sector_name) 做 upsert —— 已存在则更新数值字段、
        不存在则插入。**不要改成 bulk_insert_mappings**：那会撞主键报错并让同一
        工作日重跑时整批失败。
        """
        if not rows:
            logger.warning('upsert_daily called with empty rows')
            return 0

        written = 0
        try:
            for row in rows:
                stat_date = row.get('stat_date')
                sector_type = row.get('sector_type')
                sector_name = row.get('sector_name')
                if not (stat_date and sector_type and sector_name):
                    logger.warning(f'跳过字段不完整的一行: {row}')
                    continue

                existing = db_session.query(SectorDailyStat).filter(
                    SectorDailyStat.stat_date == stat_date,
                    SectorDailyStat.sector_type == sector_type,
                    SectorDailyStat.sector_name == sector_name,
                ).first()

                payload = {k: v for k, v in row.items()
                           if k in ('change_pct', 'stock_count', 'up_count', 'down_count',
                                    'flat_count', 'up_down_ratio', 'top_stock', 'top_stock_pct',
                                    'bottom_stock', 'bottom_stock_pct', 'total_trade_amount')}

                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    db_session.add(SectorDailyStat(
                        stat_date=stat_date, sector_type=sector_type,
                        sector_name=sector_name, **payload
                    ))
                written += 1

            db_session.commit()
            logger.info(f'✅ 板块日快照写入 {written} 行')
            return written
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f'upsert_daily IntegrityError: {e}')
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'upsert_daily SQLAlchemyError: {e}')
        except Exception as e:
            db_session.rollback()
            logger.error(f'upsert_daily 未预期错误: {e}')
        return 0

    @staticmethod
    def delete_by_date(stat_date: date, sector_type: Optional[str] = None) -> int:
        """删除某日（可限定级别）的快照，返回删除行数。回填/重跑时清理脏数据用。"""
        try:
            q = db_session.query(SectorDailyStat).filter(SectorDailyStat.stat_date == stat_date)
            if sector_type:
                q = q.filter(SectorDailyStat.sector_type == sector_type)
            n = q.delete(synchronize_session=False)
            db_session.commit()
            logger.info(f'🗑️ 删除 {stat_date} 板块快照 {n} 行')
            return n
        except Exception as e:
            db_session.rollback()
            logger.error(f'delete_by_date 失败: {e}')
            return 0

    # ─────────────────────────── 读操作 ───────────────────────────

    @staticmethod
    def get_latest_date(sector_type: Optional[str] = None) -> Optional[date]:
        """库里最新有数据的交易日；空表返回 None。"""
        try:
            q = db_session.query(func.max(SectorDailyStat.stat_date))
            st = normalize_sector_type(sector_type) if sector_type else None
            if st:
                q = q.filter(SectorDailyStat.sector_type == st)
            return q.scalar()
        except Exception as e:
            logger.error(f'get_latest_date 失败: {e}')
            return None

    @staticmethod
    def get_by_date(stat_date: date, sector_type: str) -> List[Dict[str, Any]]:
        """取某交易日、某级别的全部板块（按涨跌幅降序，与上游返回顺序无关）。"""
        st = normalize_sector_type(sector_type)
        if not st:
            logger.error(f'get_by_date: 非法 sector_type={sector_type}')
            return []
        try:
            rows = db_session.query(SectorDailyStat).filter(
                SectorDailyStat.stat_date == stat_date,
                SectorDailyStat.sector_type == st,
            ).order_by(SectorDailyStat.change_pct.desc()).all()
            return [r.to_dict() for r in rows]
        except Exception as e:
            logger.error(f'get_by_date 失败: {e}')
            return []

    @staticmethod
    def get_latest(sector_type: str) -> List[Dict[str, Any]]:
        """取最新交易日的某级别全部板块。空表返回 []。"""
        latest = SectorDailyService.get_latest_date(sector_type)
        if not latest:
            return []
        return SectorDailyService.get_by_date(latest, sector_type)

    @staticmethod
    def get_history(sector_type: str, limit_days: int = 250,
                    sector_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """取最近 N 个交易日的板块快照（板块轮动图用）。

        ⚠️ `limit_days` 是**交易日个数**不是自然日：库里只存有数据的交易日，
        所以直接对 `stat_date` 去重后倒序取 N 个即可，无需日历推算。

        :param sector_names: 可选，只取这些板块（轮动图通常只看少数几条线）
        """
        st = normalize_sector_type(sector_type)
        if not st:
            logger.error(f'get_history: 非法 sector_type={sector_type}')
            return []
        try:
            # 先取最近 N 个交易日（去重），再按这些日期取明细
            date_q = db_session.query(SectorDailyStat.stat_date).filter(
                SectorDailyStat.sector_type == st
            ).distinct().order_by(SectorDailyStat.stat_date.desc()).limit(limit_days).all()
            dates = [d[0] for d in date_q]
            if not dates:
                return []

            q = db_session.query(SectorDailyStat).filter(
                SectorDailyStat.sector_type == st,
                SectorDailyStat.stat_date.in_(dates),
            )
            if sector_names:
                q = q.filter(SectorDailyStat.sector_name.in_(sector_names))
            rows = q.order_by(SectorDailyStat.stat_date.asc()).all()
            return [r.to_dict() for r in rows]
        except Exception as e:
            logger.error(f'get_history 失败: {e}')
            return []

    @staticmethod
    def get_rotation_ranks(sector_type: str, limit_days: int = 60) -> List[Dict[str, Any]]:
        """按交易日返回「板块 -> 当日涨跌幅排名」的矩阵，直接喂给轮动图。

        返回 [{trade_date, ranks: [{sector_name, change_pct, rank}]}]，按日期升序。
        排名从 1 开始（1 = 当日最强板块）。
        """
        rows = SectorDailyService.get_history(sector_type, limit_days=limit_days)
        if not rows:
            return []

        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_date.setdefault(r['stat_date'], []).append(r)

        out = []
        for d in sorted(by_date.keys()):
            day = sorted(by_date[d], key=lambda x: (x['change_pct'] is None, -(x['change_pct'] or 0)))
            out.append({
                'trade_date': d,
                'ranks': [
                    {'sector_name': it['sector_name'], 'change_pct': it['change_pct'], 'rank': i + 1}
                    for i, it in enumerate(day)
                ],
            })
        return out

    @staticmethod
    def count_by_date(stat_date: date) -> int:
        """某日已入库行数，日更任务用它判断「是否是空跑」。"""
        try:
            return db_session.query(func.count(SectorDailyStat.stat_date)).filter(
                SectorDailyStat.stat_date == stat_date
            ).scalar() or 0
        except Exception as e:
            logger.error(f'count_by_date 失败: {e}')
            return 0
