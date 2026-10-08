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

# 强制刷新的冷却锁（防并发风暴）：长假后首日多个任务同时判 is_trading_day，
# 不能让它们同时打上游 —— NX 键拿到锁的才刷，其余等锁过期后读新缓存。
REFRESH_COOLDOWN_KEY_PREFIX = "alphalom:trading_calendar:refresh_cooldown"
REFRESH_COOLDOWN_SEC = 600  # 10 分钟

# 缓存「明显滞后」阈值（自然日）。
# 缓存末尾 = 最近有数据的交易日。普通周末：今天 - 末尾 <= 2；周一：<= 3；
# 长假（>=4 天）必然 > 3。取 3 既能覆盖「普通周末 + 周一」不误触发，
# 又能保证长假后首日 100% 触发强制刷新。
STALE_GAP_DAYS = 3


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

    ⚠️ **防「回退」覆盖**（2026-10-08 长假 bug）：长假期间上游日历只到节前最后交易日，
    若直接用新拉的 `all_days` 覆盖现有缓存，会把「已含 10-08」的完整缓存**换回更短的**。
    所以这里与现有缓存做**并集**：新值必须 >= 旧值（覆盖范围只增不减），
    绝不因为上游某天/某年没数据而让缓存变短。
    """
    # 先取现有缓存（写前留底，防止「上游缺一段 -> 并集后反而缩水」）
    existing = _get_cached_days(market) or []
    existing_set = set(existing)

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

    # ⚠️ 与现有缓存并集：宁可保留「旧但有」的天数，也不要让缓存覆盖范围变短
    merged = sorted(set(all_days) | existing_set)
    if not merged:
        logger.warning(f"[trading_calendar] {market} 拉取结果为空且无旧缓存，保留空")
        return 0

    redis_obj.set(_calendar_key(market), json.dumps(merged), ex=CALENDAR_TTL)
    # 日志里区分「上游新给」与「并集后」：方便排查上游缺年/缺段
    fresh = len(set(all_days))
    added = len(set(all_days) - existing_set)
    logger.info(f"[trading_calendar] 已刷新 {market} 交易日历：上游 {fresh} 天"
                f"{'(新增 ' + str(added) + ' 天)' if added else ''}，合并后共 {len(merged)} 天")
    return len(merged)


def _get_cached_days(market: str) -> Optional[List[str]]:
    raw = redis_obj.get(_calendar_key(market))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _is_stale(days: List[str], market: str) -> bool:
    """缓存是否「明显滞后于今天」= 缓存里最新日期比今天晚超过 STALE_GAP_DAYS 天。

    - 普通周末/周一：今天 - 缓存末尾 <= 3 → 不滞后；
    - 长假（>=4 天，如国庆/春节）：今天 - 缓存末尾 > 3 → 滞后，需要强制刷新。

    上游在长假期间**只给到节前**，所以「缓存滞后」是长假后首日的必然特征；
    此时不能信缓存里的 False（is_trading_day 会误判），要主动去上游拉一次。
    """
    if not days:
        return True  # 空缓存也算滞后（反正要刷）
    try:
        last = max(datetime.strptime(d, '%Y-%m-%d').date() for d in days)
    except Exception:
        return False
    return (date.today() - last).days > STALE_GAP_DAYS


def _ensure_days(market: str) -> List[str]:
    """优先 Redis 缓存；缓存缺失或**明显滞后**则实时兜底（全量拉取并回写缓存）。

    修复（2026-10-08 长假 bug）：
    - 旧实现只判「缓存有没有」，长假后缓存末尾是节前（09-30），is_trading_day(10-08)
      直接命中旧缓存返回 False，所有依赖它的日更任务被整体跳过。
    - 现在：缓存缺失 → 直接刷新；缓存滞后（长假期特征）→ 带冷却锁强制刷新一次；
      刷新完再读缓存，仍为空才返回 []。
    """
    days = _get_cached_days(market)
    if days and not _is_stale(days, market):
        return days
    # 缓存缺失 或 滞后（长假）→ 刷新。用 NX 冷却锁防并发风暴：
    # 节后首日多个任务同时进来时只有第一个真正打上游，其余等锁过期读新缓存。
    try:
        lock_key = f"{REFRESH_COOLDOWN_KEY_PREFIX}:{market}"
        if redis_obj.set(lock_key, '1', nx=True, ex=REFRESH_COOLDOWN_SEC):
            try:
                refresh_trading_calendar(market)
            finally:
                redis_obj.delete(lock_key)
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
