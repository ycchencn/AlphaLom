"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 新闻流 AI 速览（`news_digest` 表）的读写，以及「下一轮刷新时间」的计算。

 与 `MarketNewsService` 的分工：
 - `MarketNewsService` 管**单条新闻**（AI 摘要 + 关联标的 + 情绪）；
 - 本模块管**批量速览**（把一小时内的新闻压成三条头条），
   生成逻辑在 `job/job_news_digest.py`，本层只负责「怎么存、怎么取、什么时候该刷新」。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from models import NewsDigest
from models.database import db_session
from utils.logger import logger

# MARK: - 调度常量（单一真源）------------------------------------------------
# ⚠️ 这三处都读这里的值，改调度只改本处：
#   1. job/news_server.py 的 cron（hour=REFRESH_HOUR_START-REFRESH_HOUR_END, minute=REFRESH_MINUTE）
#   2. 本模块 next_refresh_at() —— 接口返回给前端「下一轮几点刷新」
#   3. 前端只展示后端给的时间，不再自己算 cron
# 只在活跃时段跑（凌晨没有新闻流，跑了纯烧 token）。
REFRESH_MINUTE = 30
REFRESH_HOUR_START = 7
REFRESH_HOUR_END = 23

# 卡片只置顶三条；模型多给的一律截断
MAX_HEADLINES = 3
# 历史保留天数：只为排障回看，不需要长期留
KEEP_DAYS = 30


class NewsDigestService:

    # MARK: - 写入 ---------------------------------------------------------
    @staticmethod
    def create(
        headlines: List[Dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        news_count: int = 0,
        title: str = None,
        highlights: List[str] = None,
        model: str = None,
        trigger_type: str = 'auto',
        generated_at: datetime = None,
    ) -> Optional[Dict[str, Any]]:
        """
        落库一条速览快照。

        :param headlines: [{"topic": "市场焦点", "keywords": [...], "summary": "..."}]，最多取 MAX_HEADLINES 条
        :param window_start / window_end: 本次统计的新闻时间窗口（闭区间）
        :param news_count: 参与总结的新闻条数（供页面显示「基于 N 条新闻」）
        :param highlights: 次要要点，每条一句话
        :param trigger_type: auto-定时任务 / manual-页面手动刷新
        :return: 落库后的 dict（含自增 id），失败返回 None
        """
        if not headlines:
            logger.warning('news_digest: headlines 为空，跳过落库')
            return None

        try:
            row = NewsDigest(
                generated_at=generated_at or datetime.now(),
                window_start=window_start,
                window_end=window_end,
                news_count=int(news_count or 0),
                title=title,
                headlines=headlines[:MAX_HEADLINES],
                highlights=highlights or [],
                model=model,
                trigger_type=trigger_type,
            )
            db_session.add(row)
            db_session.commit()
            db_session.refresh(row)
            logger.info(
                f"📰 新闻速览已落库：id={row.id}, 覆盖 {row.news_count} 条新闻, "
                f"头条 {len(row.headlines)} 条, 窗口 {window_start:%m-%d %H:%M}~{window_end:%m-%d %H:%M}"
            )
            return row.to_dict()
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'news_digest 落库失败：{e}')
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f'news_digest 落库异常：{e}')
            return None

    # MARK: - 读取 ---------------------------------------------------------
    @staticmethod
    def get_latest() -> Optional[Dict[str, Any]]:
        """
        取最新一条速览（页面顶部置顶卡片用）。

        表还没建（新库/服务未重启）或查询失败时返回 None，由调用方渲染空态 ——
        这里绝不能抛，否则一个可选功能会把事件驱动页整页带崩。
        """
        try:
            row = (
                db_session.query(NewsDigest)
                .order_by(NewsDigest.generated_at.desc(), NewsDigest.id.desc())
                .first()
            )
            return row.to_dict() if row else None
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'news_digest 查询失败：{e}')
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f'news_digest 查询异常：{e}')
            return None

    @staticmethod
    def get_recent(limit: int = 24) -> List[Dict[str, Any]]:
        """取最近 N 条速览（按时间倒序），供回看/排障。"""
        try:
            rows = (
                db_session.query(NewsDigest)
                .order_by(NewsDigest.generated_at.desc(), NewsDigest.id.desc())
                .limit(max(1, min(int(limit or 24), 200)))
                .all()
            )
            return [r.to_dict() for r in rows]
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'news_digest 历史查询失败：{e}')
            return []
        except Exception as e:
            db_session.rollback()
            logger.error(f'news_digest 历史查询异常：{e}')
            return []

    # MARK: - 维护 ---------------------------------------------------------
    @staticmethod
    def prune(keep_days: int = KEEP_DAYS) -> int:
        """删除 keep_days 天前的历史快照，返回删除行数。"""
        deadline = datetime.now() - timedelta(days=max(1, int(keep_days)))
        try:
            deleted = (
                db_session.query(NewsDigest)
                .filter(NewsDigest.generated_at < deadline)
                .delete(synchronize_session=False)
            )
            db_session.commit()
            if deleted:
                logger.info(f'🧹 清理 {deleted} 条过期新闻速览（早于 {deadline:%Y-%m-%d}）')
            return int(deleted or 0)
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'news_digest 清理失败：{e}')
            return 0

    # MARK: - 调度口径 -----------------------------------------------------
    @staticmethod
    def next_refresh_at(now: datetime = None) -> datetime:
        """
        下一次自动刷新的时间点（北京时间）。

        口径必须与 job/news_server.py 里的 cron 一致（都取自本模块顶部的常量）：
        每天 REFRESH_HOUR_START~REFRESH_HOUR_END 之间的第 REFRESH_MINUTE 分。

        :param now: 便于单测注入「当前时间」
        """
        now = now or datetime.now()
        candidate = now.replace(minute=REFRESH_MINUTE, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)

        if candidate.hour > REFRESH_HOUR_END:
            # 收市后的最后一个点已过 → 次日首个活跃点
            candidate = (candidate + timedelta(days=1)).replace(hour=REFRESH_HOUR_START)
        elif candidate.hour < REFRESH_HOUR_START:
            # 凌晨 → 当天首个活跃点
            candidate = candidate.replace(hour=REFRESH_HOUR_START)
        return candidate
