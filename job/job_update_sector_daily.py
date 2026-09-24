"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 申万行业每日快照落库（支撑板块轮动图）。

 ⚠️ 上游 `/cn/market/sector_data/{sw1|sw2|sw3}` **只返回最新一个交易日**，
 没有「按日期取历史」的参数。因此本任务的历史是**逐日累积**出来的：
 今天不跑，今天的板块数据就永久缺失，轮动图会断档。别指望事后补。

 ⚠️ 任务必须幂等（队列是至少一次投递，见 service/sector_daily_service.py 的说明）。
"""

from datetime import datetime

from service.sector_daily_service import SectorDailyService, SECTOR_TYPES
from utils.data_loader import databull
from utils.logger import logger


def _parse_stat_date(raw):
    """上游 stat_date 可能是 '2026-09-23' / '20260923' / date / None。"""
    if raw is None:
        return None
    if hasattr(raw, 'date') and not isinstance(raw, str):
        return raw.date() if hasattr(raw, 'date') else raw
    s = str(raw).strip()
    for fmt in ('%Y-%m-%d', '%Y%m%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.warning(f'无法解析 stat_date: {raw!r}')
    return None


def _normalize_row(raw, stat_date, sector_type_upper):
    """把上游一行整成 DB 需要的 dict；缺关键字段返回 None。"""
    name = raw.get('sector_name')
    if not name:
        return None

    def _f(key):
        v = raw.get(key)
        if v is None or v == '':
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _i(key):
        v = _f(key)
        return int(v) if v is not None else None

    return {
        'stat_date': stat_date,
        'sector_type': sector_type_upper,
        'sector_name': str(name).strip(),
        'change_pct': _f('change_pct'),
        'stock_count': _i('stock_count'),
        'up_count': _i('up_count'),
        'down_count': _i('down_count'),
        'flat_count': _i('flat_count'),
        'up_down_ratio': _f('up_down_ratio'),
        'top_stock': raw.get('top_stock'),
        'top_stock_pct': _f('top_stock_pct'),
        'bottom_stock': raw.get('bottom_stock'),
        'bottom_stock_pct': _f('bottom_stock_pct'),
        'total_trade_amount': _f('total_trade_amount'),
    }


def job_update_sector_daily(sector_types=None):
    """拉取申万各级别最新一个交易日的板块数据并落库。

    :param sector_types: 要处理的级别，默认 sw1/sw2/sw3；可传 ['sw1'] 单跑一级
    :return: dict {级别: 写入行数}
    """
    types = sector_types or list(SECTOR_TYPES)
    summary = {}

    for st in types:
        st_upper = st.upper()
        try:
            data = databull.get_sector_data(sector_type=st)
        except Exception as e:
            # ⚠️ SDK 失败是抛 DataBullError，不是返回 None —— 必须 try/except。
            # 某个级别失败不能拖垮其它级别，所以放在循环内 catch。
            logger.error(f'{st_upper} 板块数据获取失败: {e}')
            summary[st_upper] = 0
            continue

        if not data:
            logger.warning(f'{st_upper} 板块数据为空，跳过')
            summary[st_upper] = 0
            continue

        # 一次响应里所有行的 stat_date 应该一致；按行解析以免上游混排
        rows = []
        stat_dates = set()
        for raw in data:
            if not isinstance(raw, dict):
                continue
            sd = _parse_stat_date(raw.get('stat_date'))
            if sd is None:
                continue
            stat_dates.add(sd)
            norm = _normalize_row(raw, sd, st_upper)
            if norm:
                rows.append(norm)

        if not rows:
            logger.warning(f'{st_upper} 解析后无可写入行（原始 {len(data)} 行）')
            summary[st_upper] = 0
            continue

        # ⚠️ 上游返回「最新交易日」，但**不等于今天**：周末/节假日跑，或者盘中
        # 早于收盘跑，拿到的都是上一个交易日 —— 这正是我们想要的（存的是有数据的
        # 那个交易日），所以这里不校验「是否等于今天」，只如实记录。
        written = SectorDailyService.upsert_daily(rows)
        summary[st_upper] = written
        logger.info(f'{st_upper} 板块快照: {len(rows)} 行 -> 写入 {written} 行, '
                    f'交易日 {sorted(d.isoformat() for d in stat_dates)}')

    logger.info(f'板块日更完成: {summary}')
    return summary


if __name__ == '__main__':
    job_update_sector_daily()
