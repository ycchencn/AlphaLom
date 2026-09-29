"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

全站「时区」配置的运行时解析层。

背景：项目里原先到处写死 `pytz.timezone('Asia/Shanghai')`，但**并非所有时间路径都走了它** ——
最典型的是 `datetime.now()`（naive，取的是**宿主机本地时区**）。一旦服务跑在 UTC 容器里，
`datetime.now()` 给的就是 UTC，于是「速览卡片」这类直接落库 naive 时间的地方，
显示出来的时间会比北京时间**少 8 小时**（实测库里的 13:30 其实是北京 21:30）。

现在统一成：

    代码默认值（Asia/Shanghai）  ←  system_setting 表覆盖（后台「通用设置」页可改，立即生效）

存储约定（system_setting 表）：
    setting_group = 'general_setting'
    setting_key   = 'general_setting.timezone'
    setting_value = "Asia/Shanghai"（IANA 时区名，字符串）
      - **库里没有该行 = 用代码默认值**（与 chart_display / llm_platform 的语义一致）；
      - 「恢复默认」= 删行，不是写一行默认值回去。

⚠️ 作用范围（重要）：时区**只影响展示与时间戳解释**，**不改定时任务调度**。
   调度（job/news_server.py 的 cron、A 股交易日口径）**固定按 A 股业务时区**走，
   因为「A 股 15:00 收盘」「交易日」这些是市场规则而不是用户偏好 ——
   让用户改时区把 15:30 的日更任务挪到凌晨跑，只会静默产生错误数据。
   所以本模块只提供「现在是几点」「这个 naive 时间按哪个时区解读」这类能力，
   调度侧请继续用 `A_SHARE_TZ_NAME`。
"""

from datetime import datetime, timedelta, timezone, tzinfo, date
from typing import Any, Dict, List, Optional

from utils.logger import logger

# system_setting 表里的分组名（同时也是配置键前缀）
GENERAL_SETTING_GROUP = 'general_setting'
TIMEZONE_KEY = 'timezone'

# 代码默认时区：A 股业务时区。用户不配置时用这个。
DEFAULT_TIMEZONE = 'Asia/Shanghai'

# A 股业务时区（**调度专用，不受用户配置影响**）。
# 交易日、收盘时刻、日更任务口径都按它算，避免用户改时区把任务跑偏。
A_SHARE_TZ_NAME = 'Asia/Shanghai'

# 设置页下拉的「常用时区」：置顶展示，减少在 598 个时区里翻找。
# value 是 IANA 名，label 是给用户看的中文名。
COMMON_TIMEZONES: List[Dict[str, str]] = [
    {'value': 'Asia/Shanghai', 'label': '北京 / 上海 (UTC+8)'},
    {'value': 'Asia/Hong_Kong', 'label': '中国香港 (UTC+8)'},
    {'value': 'Asia/Taipei', 'label': '中国台北 (UTC+8)'},
    {'value': 'Asia/Tokyo', 'label': '东京 (UTC+9)'},
    {'value': 'Asia/Singapore', 'label': '新加坡 (UTC+8)'},
    {'value': 'UTC', 'label': '协调世界时 UTC (UTC+0)'},
    {'value': 'Europe/London', 'label': '伦敦 (UTC+0/+1)'},
    {'value': 'America/New_York', 'label': '纽约 (UTC-5/-4)'},
    {'value': 'America/Los_Angeles', 'label': '洛杉矶 (UTC-8/-7)'},
]


def _is_valid_timezone(name: str) -> bool:
    """校验时区名是否可用（优先 zoneinfo，退回 pytz）。"""
    if not isinstance(name, str) or not name.strip():
        return False
    name = name.strip()
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)          # 不存在会抛 ZoneInfoNotFoundError
        return True
    except Exception:
        pass
    try:
        import pytz
        pytz.timezone(name)     # 不存在会抛 UnknownTimeZoneError
        return True
    except Exception:
        return False


def get_timezone_name() -> str:
    """
    当前生效的时区名（IANA）。表里配了且合法就用它，否则回代码默认值。

    读库失败一律回默认值 —— 时区取不到不该让任何接口挂掉。
    """
    try:
        from service.system_setting_service import SystemSettingService
        raw = SystemSettingService.get_value(
            f'{GENERAL_SETTING_GROUP}.{TIMEZONE_KEY}', default=None
        )
    except Exception as e:
        logger.warning(f'读取 system_setting[{GENERAL_SETTING_GROUP}.{TIMEZONE_KEY}] 失败，改用默认时区：{e}')
        return DEFAULT_TIMEZONE

    if isinstance(raw, str) and raw.strip():
        name = raw.strip()
        if _is_valid_timezone(name):
            return name
        logger.warning(f'配置的时区不可识别：{name!r}，改用默认时区 {DEFAULT_TIMEZONE}')
    return DEFAULT_TIMEZONE


def is_customized() -> bool:
    """表里是否显式配了时区（设置页据此显示「已自定义」）。"""
    try:
        from service.system_setting_service import SystemSettingService
        raw = SystemSettingService.get_value(
            f'{GENERAL_SETTING_GROUP}.{TIMEZONE_KEY}', default=None
        )
    except Exception:
        return False
    return isinstance(raw, str) and bool(raw.strip())


def get_tzinfo(name: Optional[str] = None) -> tzinfo:
    """
    取 tzinfo 对象。name 缺省用当前生效时区。

    zoneinfo 拿不到时退回 pytz；两个都失败再退回固定 +8 偏移
    （宁可偏移固定，也不要抛异常让调用方崩）。
    """
    tz_name = (name or get_timezone_name()).strip()
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        pass
    try:
        import pytz
        return pytz.timezone(tz_name)
    except Exception as e:
        logger.warning(f'时区 {tz_name!r} 无法解析，回退固定 +8 偏移：{e}')
        return timezone(timedelta(hours=8))


def now(name: Optional[str] = None) -> datetime:
    """
    当前时间，**该时区的 aware datetime**。

    ⚠️ 返回的是 aware（带 tzinfo）对象。若调用方要写进 MySQL 的 DATETIME 列，
    请先 `naive()` 一下 —— 本项目 MySQL 的 time_zone=SYSTEM，塞 aware 会被驱动
    按本地时区转换，反而引入偏移。写库请统一用 `now_naive()`。
    """
    return datetime.now(get_tzinfo(name))


def now_naive(name: Optional[str] = None) -> datetime:
    """
    当前时间，**该时区的 naive datetime**（丢了 tzinfo 但值是该时区的墙上时间）。

    写 MySQL DATETIME 列请用这个：列里存的就是「该时区的墙上时间」，
    读出来直接展示即可，不存在转换问题。
    """
    return datetime.now(get_tzinfo(name)).replace(tzinfo=None)


def today(_format: str = '%Y%m%d', name: Optional[str] = None) -> str:
    """该时区下的「今天」，格式化成字符串。"""
    return now_naive(name).strftime(_format)


def to_local(dt: Optional[datetime], name: Optional[str] = None) -> Optional[datetime]:
    """
    把一个时间**按该时区解释**并转成该时区的 naive datetime。

    用途：修「库里存的是 UTC 墙上时间」这类历史数据 ——
    `to_local(dt.replace(tzinfo=timezone.utc))` 即把 UTC 值转成目标时区的墙上时间。

    - dt 已经是 aware：直接 astimezone 到目标时区后去掉 tzinfo；
    - dt 是 naive：**假定它已经是目标时区的墙上时间**，原样返回（不猜、不乱转）；
    - None 原样返回。
    """
    if dt is None:
        return None
    tz = get_tzinfo(name)
    if dt.tzinfo is not None:
        return dt.astimezone(tz).replace(tzinfo=None)
    return dt


def to_utc_naive(dt: Optional[datetime], source_tz: Optional[str] = None) -> Optional[datetime]:
    """
    把「某时区的墙上时间」naive 值转成 **UTC naive** 值（写库用）。

    :param dt: 该时区的墙上时间（naive）
    :param source_tz: dt 所属的时区，缺省 = 当前配置时区

    ⚠️ 与 `to_local` 的区别：`to_local` 是「aware → 目标时区」，
    这里是「某个未知时区的 naive → UTC naive」——所以要显式给出源时区。
    """
    if dt is None:
        return None
    tz = get_tzinfo(source_tz)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    # naive：先标注为源时区，再转 UTC
    return dt.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_local(dt: Optional[datetime], name: Optional[str] = None) -> Optional[datetime]:
    """
    把库里的 **UTC naive** 值转成目标时区的墙上时间 naive（读库展示用）。

    这是 `to_utc_naive` 的逆运算，两者配合实现「存 UTC、按配置时区展示」。

    - dt 是 aware：视为绝对时刻，直接 astimezone；
    - dt 是 naive：**假定它是 UTC 墙上时间**，补上 UTC 再转；
    - None 原样返回。
    """
    if dt is None:
        return None
    tz = get_tzinfo(name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None)


def fix_utc_naive_to_local(dt: Optional[datetime], name: Optional[str] = None) -> Optional[datetime]:
    """
    订正「本该是本地时间、却按 UTC 落库」的 naive 值：给 UTC 值补上偏移。

    专给历史数据修补用（见 install/fix_news_digest_timezone.py）：
    库里那些 13:30 实际是 UTC 的 13:30，对应北京时间 21:30。
    """
    if dt is None:
        return None
    tz = get_tzinfo(name)
    offset = tz.utcoffset(datetime.now())
    if offset is None:
        return dt
    return dt + offset


def get_setting_view() -> Dict[str, Any]:
    """
    设置页视图：当前生效时区 + 默认值 + 是否被表内配置覆盖 + 常用时区清单 +
    该时区的当前时间与 UTC 偏移（前端可据此做个「现在是几点」的实时预览）。
    """
    name = get_timezone_name()
    tz = get_tzinfo(name)
    current = datetime.now(tz)
    offset = current.utcoffset()
    return {
        'timezone': name,
        'default': DEFAULT_TIMEZONE,
        'customized': is_customized(),
        'common': COMMON_TIMEZONES,
        'server_local_timezone': _server_local_timezone_name(),
        'server_local_offset': _server_local_offset_str(),
        'current_time': current.strftime('%Y-%m-%d %H:%M:%S'),
        'utc_offset': _format_offset(offset),
        'a_share_timezone': A_SHARE_TZ_NAME,
    }


def _format_offset(offset: Optional[timedelta]) -> str:
    """把 UTC 偏移格式化成 'UTC+08:00' 这样的串（前端直接显示）。"""
    if offset is None:
        return 'UTC±00:00'
    total_minutes = int(offset.total_seconds() // 60)
    sign = '+' if total_minutes >= 0 else '-'
    total_minutes = abs(total_minutes)
    return f'UTC{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}'


def _server_local_timezone_name() -> str:
    """
    宿主机本地时区的展示名，放在设置页做对照。

    这个**只用于展示/排障**（提示「服务器本身是 UTC」，解释为什么历史数据差了 8 小时），
    不参与任何业务计算 —— 业务时间一律走本模块的配置时区。
    """
    try:
        import time as _time
        offset = -(_time.timezone)
        sign = '+' if offset >= 0 else '-'
        hours = abs(offset) // 3600
        names = {'China Standard Time': '中国标准时间', 'UTC': '协调世界时',
                 'Coordinated Universal Time': '协调世界时'}
        tzname = (_time.tzname[0] if _time.tzname else '') or ''
        label = names.get(tzname, tzname)
        return f'{label} (UTC{sign}{hours:02d}:00)'.strip()
    except Exception:
        return ''


def _server_local_offset_str() -> str:
    """
    宿主机本地时区的 UTC 偏移（形如 'UTC+08:00'）。

    给设置页做**数值比较**用：判断「服务器机器时区」与「展示时区」是否真的差几个小时。
    ⚠️ 不能拿 `_server_local_timezone_name()` 的显示串去比：那串是带中文名的展示文本，
       与 IANA 时区名（Asia/Shanghai）永远不相等 —— 会比出「永远不同」的假告警。
    """
    try:
        import time as _time
        offset = -(_time.timezone)  # 秒，东为正
        return _format_offset(timedelta(seconds=offset))
    except Exception:
        return ''
