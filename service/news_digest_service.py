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
from utils.timezone_util import A_SHARE_TZ_NAME
from utils.timezone_util import now_naive as tz_now
from utils.timezone_util import now_naive
from utils.timezone_util import to_utc_naive, utc_naive_to_local

# 速览时间列的**存储时区**。
# ⚠️ 存 UTC 而不是存某个本地时区：展示时区是可配置的，若把「展示时区的墙上时间」
#    直接写进库，用户改一次时区，所有历史行的时间含义就跟着变了（无法自洽）。
#    存 UTC 则「落库」与「展示」解耦：改展示时区时只是读出后换算，
#    历史数据语义恒定，也能随时切回。
#    库里既有数据（2026-09-29 之前）是按「服务器本地时区」naive 落的，
#    已由 install/fix_news_digest_timezone.py 统一订正为 UTC 口径。
STORAGE_TZ_NAME = 'UTC'


def _to_storage(dt: datetime) -> datetime:
    """把「配置时区的墙上时间」转成存储用的 UTC naive 值。"""
    if dt is None:
        return None
    return to_utc_naive(dt)


def _from_storage(dt: datetime) -> datetime:
    """
    把库里的 UTC naive 值转成**当前展示时区**的墙上时间（仍是 naive）。

    页面直接展示这个值即可 —— 它是「展示时区的墙上时间」，不带时区后缀。
    """
    if dt is None:
        return None
    return utc_naive_to_local(dt)

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
        :param window_start / window_end: 本次统计的新闻时间窗口（闭区间，**当前展示时区的墙上时间**）
        :param news_count: 参与总结的新闻条数（供页面显示「基于 N 条新闻」）
        :param highlights: 次要要点，每条一句话
        :param trigger_type: auto-定时任务 / manual-页面手动刷新
        :return: 落库后的 dict（含自增 id），失败返回 None

        ⚠️ 入参是「展示时区的墙上时间」，**写库前统一转成 UTC**（见 STORAGE_TZ_NAME）：
        展示时区是可配置的，存本地时间会让历史行随配置变化而失去自洽性。
        """
        if not headlines:
            logger.warning('news_digest: headlines 为空，跳过落库')
            return None

        try:
            row = NewsDigest(
                # 落库一律 UTC：展示时区可配，存 UTC 才能与展示解耦
                generated_at=_to_storage(generated_at or tz_now()),
                window_start=_to_storage(window_start),
                window_end=_to_storage(window_end),
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
            return NewsDigestService._view(row.to_dict())
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'news_digest 落库失败：{e}')
            return None
        except Exception as e:
            db_session.rollback()
            logger.error(f'news_digest 落库异常：{e}')
            return None

    # MARK: - 读写时的时区换算 ---------------------------------------------
    @staticmethod
    def _view(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        把落库 dict 里的三个时间字段从 UTC 换算成**当前展示时区**的墙上时间。

        页面拿到后直接展示，不必也不该再做时区推断。
        """
        if not d:
            return d
        for key in ('generated_at', 'window_start', 'window_end'):
            raw = d.get(key)
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace(' ', 'T'))
            except Exception:
                continue
            local = _from_storage(dt)
            if local is not None:
                d[key] = local.isoformat()
        return d

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
            return NewsDigestService._view(row.to_dict()) if row else None
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
            return [NewsDigestService._view(r.to_dict()) for r in rows]
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
        """
        删除 keep_days 天前的历史快照，返回删除行数。

        ⚠️ 比较基准用 **UTC**（与列里存的口径一致）：
        generated_at 存的是 UTC，拿本地时间当阈值会因时区差而多删/少删几小时的数据。
        """
        deadline = to_utc_naive(tz_now()) - timedelta(days=max(1, int(keep_days)))
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
        下一次自动刷新的时间点（**当前展示时区**的墙上时间）。

        ⚠️ 两步走，别把「调度时刻」和「展示时刻」搞混：
        1. 先在**调度时区**（A 股业务时区 Asia/Shanghai）算出下一次触发时刻 ——
           它必须与 job/news_server.py 的 cron 对齐，而 cron 固定按 A_SHARE_TZ_NAME 触发，
           用户改展示时区**不会**让任务改点；
        2. 再把这个绝对时刻**换算成展示时区**的墙上时间返回给页面 ——
           用户看到的是「以我的时区算，下一轮是几点」。

        :param now: 便于单测注入「当前时间」（naive，视为调度时区的墙上时间）
        """
        if now is None:
            now = now_naive(A_SHARE_TZ_NAME)
        candidate = now.replace(minute=REFRESH_MINUTE, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)

        if candidate.hour > REFRESH_HOUR_END:
            # 收市后的最后一个点已过 → 次日首个活跃点
            candidate = (candidate + timedelta(days=1)).replace(hour=REFRESH_HOUR_START)
        elif candidate.hour < REFRESH_HOUR_START:
            # 凌晨 → 当天首个活跃点
            candidate = candidate.replace(hour=REFRESH_HOUR_START)

        # 调度时区墙上时间 → 展示时区墙上时间
        from utils.timezone_util import get_timezone_name
        display_tz = get_timezone_name()
        if display_tz != A_SHARE_TZ_NAME:
            candidate = utc_naive_to_local(
                to_utc_naive(candidate, A_SHARE_TZ_NAME), display_tz
            )
        return candidate
