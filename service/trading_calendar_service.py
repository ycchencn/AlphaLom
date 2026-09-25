"""
交易日历服务：统一从 databull 的 `get_trading_calendar` 接口取数，并缓存到 Redis。

设计：
- 日更任务（scheduler 每天 00:05）调用 `refresh_trading_calendar` 拉取交易日历写入 Redis，
  key = `alphalom:trading_calendar:{market}`，value = 排序去重后的 ISO 日期字符串数组，TTL 2 天
  （日更覆盖；单日 databull 抖动时旧值仍可用，不会击穿成整站无交易日判断）。
- `is_trading_day` / `get_latest_trading_date` 优先读 Redis 缓存；缓存缺失时实时回退
  databull 查询并把结果写回缓存（保证首次调用 / 缓存过期后也能正常工作）。

迁移说明：原先 `FactorValueService.is_trading_day` 依赖 `FactorValue` 表里 `cn_trading_date`
因子（value='1.0' 表示交易日）。本模块是新的数据来源，已由 `factor_service` 的两个同名方法
转调，调用方（job / 策略）无需改动。
"""
import json
from datetime import date, datetime
from typing import List, Optional

from databull import DataBullError
from utils.data_loader import databull
from utils.redis_obj import redis_obj
from utils.logger import logger

CALENDAR_KEY_PREFIX = "alphalom:trading_calendar"
# 2 天：日更刷新覆盖；单日拉取失败时旧值仍可用
CALENDAR_TTL = 2 * 24 * 3600


def _calendar_key(market: str) -> str:
    return f"{CALENDAR_KEY_PREFIX}:{market}"


def _years_to_cache() -> List[int]:
    """缓存范围：去年 / 今年 / 明年。
    覆盖「最新交易日 <= 今天」(可能在去年) 与近期判断所需范围，又不会无限膨胀。"""
    y = date.today().year
    return [y - 1, y, y + 1]


def _normalize(raw) -> List[str]:
    """把 databull 返回的交易日历归一化为 ISO 日期字符串数组。
    接口文档说返回 ISO 字符串数组，这里对 date/datetime/字符串都做防御性处理。"""
    out: List[str] = []
    if not raw:
        return out
    for x in raw:
        if isinstance(x, (datetime, date)):
            out.append(x.strftime('%Y-%m-%d'))
        elif isinstance(x, str):
            out.append(x[:10])
        elif isinstance(x, dict):
            # 极端兜底：个别实现可能返回 {date: ...}
            v = x.get('date') or x.get('trade_date') or x.get('trading_date')
            if v:
                out.append(str(v)[:10])
    return out


def _fetch_year(market: str, year: int) -> List[str]:
    """从 databull 拉取某年交易日历（ISO 字符串数组）。"""
    return _normalize(databull.get_trading_calendar(market=market, year=year))


def refresh_trading_calendar(market: str = 'cn') -> int:
    """
    每天调用一次：拉取交易日历写入 Redis。返回本次缓存的交易日总数。
    若全部拉取失败则不覆盖旧缓存（避免把可用缓存清空成空）。
    """
    all_days: List[str] = []
    for y in _years_to_cache():
        try:
            days = _fetch_year(market, y)
            if days:
                all_days.extend(days)
        except DataBullError as e:
            logger.warning(f"[trading_calendar] databull 拉取 {market} {y} 失败: {e}")
        except Exception as e:
            logger.warning(f"[trading_calendar] 拉取 {market} {y} 异常: {e}")

    all_days = sorted(set(all_days))
    if all_days:
        redis_obj.set(_calendar_key(market), json.dumps(all_days), ex=CALENDAR_TTL)
        logger.info(f"[trading_calendar] 已刷新 {market} 交易日历，共 {len(all_days)} 天")
    else:
        logger.warning(f"[trading_calendar] {market} 拉取结果为空，保留旧缓存")
    return len(all_days)


def _get_cached_days(market: str) -> Optional[List[str]]:
    raw = redis_obj.get(_calendar_key(market))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _ensure_days(market: str) -> List[str]:
    """优先 Redis 缓存；缓存缺失则实时兜底（全量拉取并回写缓存）。"""
    days = _get_cached_days(market)
    if days:
        return days
    try:
        refresh_trading_calendar(market)
        days = _get_cached_days(market)
        if days:
            return days
    except Exception as e:
        logger.warning(f"[trading_calendar] 兜底刷新失败: {e}")
    return []


def is_trading_day(check_date: Optional[date] = None, market: str = 'cn') -> bool:
    """
    判断指定日期（默认今天）是否为交易日。
    优先读 Redis 缓存的交易日历，缺失时实时查询 databull。
    """
    d = check_date or date.today()
    ds = d.strftime('%Y-%m-%d')
    days = _ensure_days(market)
    return ds in set(days)


def get_latest_trading_date(market: str = 'cn') -> Optional[date]:
    """
    返回 <= 今天 的最近交易日；无数据返回 None。
    优先读 Redis 缓存，缺失时实时查询。
    """
    today = date.today()
    days = _ensure_days(market)
    latest: Optional[date] = None
    for ds in days:
        try:
            dd = datetime.strptime(ds, '%Y-%m-%d').date()
        except Exception:
            continue
        if dd <= today and (latest is None or dd > latest):
            latest = dd
    return latest
