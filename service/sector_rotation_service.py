"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 板块轮动分析（沪深大盘监控页）。

 数据全部来自本地表 `sector_daily_stats`（日更 `job_update_sector_daily`，
 mon-fri 20:35 落库），**不走上游** —— 上游 `/cn/market/sector_data/{sw}` 只返回
 最新一个交易日，没有历史接口，算不了任何"轮动"。

 ⚠️ 这个模块只做**纯计算**：取数交给 `SectorDailyService.get_history`，不要在这里
 再写 SQL。原因有两个：一是历史窗口的取法（先去重日期再按日期取明细）在那边已经
 处理过；二是 `days` 的语义是「交易日个数」而不是自然日，两处各写一份迟早会漂移。

 ⚠️ 样本长度的现实约束：表是 2026-09-23 才开始落库的，早期只有几个交易日。
 所有"累计/排名变化/连续性"类指标在样本过短时噪音极大，因此这里显式给出
 `meta.trade_days` 与 `meta.is_short_sample`，由前端决定是否挂提示条 ——
 不要在前端拿 `days` 参数当样本长度（请求 20 天可能只返回 5 天）。

 ⚠️ 还有第二类样本问题：**板块本身不一定每个交易日都出现**。实测 sw3 每天上游只给
 150 行，而窗口并集有 170 个板块 —— 有 41 个板块只覆盖了部分交易日（其中 12 个只有
 1 天）。这类板块的"区间累计涨幅"其实是单日涨幅，按它排序会把「视频媒体（1 天
 +6.06%）」顶到第一名。所以每个板块都带 `is_partial`，排序时**不完整样本一律沉底**
 （表格另给一个 `sort_cum`，因为前端表格会按 sortField 重排，只排服务端顺序没用），
 前端也要能看出"这个板块样本只有 1/5 天"。sw1/sw2 实测全部完整（31/131），
 只有 sw3 会踩到。
"""

from statistics import median, pstdev
from typing import Any, Dict, List, Optional

from service.sector_daily_service import SectorDailyService, normalize_sector_type
from utils.logger import logger

# 样本短于这个交易日数就认为"结论仅供参考"。10 个交易日 = 两周，
# 足以让"连续跑赢"这类指标不再是单点巧合。
SHORT_SAMPLE_DAYS = 10

# 涨跌幅字段是百分数（2.06 = 2.06%），累计涨幅必须按复利算：
# (1+r1/100)(1+r2/100)... - 1。直接相加会在涨跌幅大时高估（几天 +5% 差出 0.5 个点）。
_PCT_DIVISOR = 100.0

# 样本不完整的板块在**表格排序键**里用的地板值。
# ⚠️ 后端把 `series` 排成"完整样本在前"，但前端 DataTable 会按 `sortField` **重排**，
# 仅靠服务端顺序在 UI 上等于没排 —— 所以"完整样本优先"必须编码进排序键本身。
# 取一个远低于任何真实累计涨幅的数（真实值在 ±50% 内），并保留原 cum_pct 作为偏移，
# 让这些板块之间仍按各自涨幅排序。
_PARTIAL_SORT_FLOOR = -1e6


def _safe_float(v) -> Optional[float]:
    """上游/库里给到字符串或 None 时统一成 float；转不动返回 None（不抛）。"""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class SectorRotationService:

    @staticmethod
    def get_rotation(sector_type: str, days: int = 20) -> Optional[Dict[str, Any]]:
        """板块轮动分析：窗口内各板块的强弱、排名变化与持续性。

        :param sector_type: sw1 / sw2 / sw3（大小写不敏感）
        :param days: 窗口长度，单位是**交易日个数**（库里有多少就取多少，不足不报错）
        :return: None 表示 sector_type 非法（路由转 400）；数据为空时返回
                 trade_days=0 的正常结构（**不是** None），前端据此渲染空态。

        ⚠️ 这里**不做 "Top N" 裁剪**：`series` 永远是完整榜单（完整样本按区间累计降序，
        样本不完整的沉底）。"热力图/象限图只画最强 N 个"是**展示层**的事，交给前端切 ——
        表格需要的是全量（否则用户找不到弱势板块），而图表需要的是裁剪（170 行画不出来）。
        两边的诉求相反，收在服务端就只能满足一个。
        """
        st = normalize_sector_type(sector_type)
        if not st:
            logger.error(f'get_rotation: 非法 sector_type={sector_type}')
            return None

        rows = SectorDailyService.get_history(st, limit_days=days)
        if not rows:
            return {
                'meta': {
                    'sector_type': st, 'start_date': None, 'end_date': None,
                    'trade_days': 0, 'requested_days': days, 'sector_count': 0,
                    'is_short_sample': True,
                    'sample_hint': '库中还没有板块快照数据（日更任务 job_update_sector_daily mon-fri 20:35 落库）',
                },
                'dates': [], 'series': [], 'daily': [],
            }

        # ── 1. 按交易日聚合，并算当日的排名 / 中位数 / 市场宽度 ──
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_date.setdefault(r['stat_date'], []).append(r)
        dates = sorted(by_date.keys())

        # 每个板块的当日「跑赢中位数」标记要按日横向比，所以先算好当日的横截面指标
        cross: Dict[str, Dict[str, Any]] = {}
        for d in dates:
            day = by_date[d]
            pcts = [_safe_float(it.get('change_pct')) for it in day]
            valid = [p for p in pcts if p is not None]
            med = median(valid) if valid else None
            # 排名：涨跌幅降序，None 排最后（数据目前无空值，防御性处理）
            ordered = sorted(day, key=lambda x: (_safe_float(x.get('change_pct')) is None,
                                                 -(_safe_float(x.get('change_pct')) or 0.0)))
            rank_of = {it['sector_name']: i + 1 for i, it in enumerate(ordered)}

            up_stocks = sum((it.get('up_count') or 0) for it in day)
            down_stocks = sum((it.get('down_count') or 0) for it in day)
            flat_stocks = sum((it.get('flat_count') or 0) for it in day)
            amount_total = sum((_safe_float(it.get('total_trade_amount')) or 0.0) for it in day)
            cross[d] = {
                'median_pct': med,
                'rank_of': rank_of,
                # 当日实际参与排名的板块数。⚠️ 不等于窗口并集的板块数：sw3 每天上游只给
                # 150 行而并集有 170 个，所以"第 3 名 /170"是错的、"第 3 名 /150"才对。
                'sector_count': len(valid),
                'amount_total': amount_total,
                'up_sector_count': sum(1 for p in valid if p > 0),
                'down_sector_count': sum(1 for p in valid if p < 0),
                'flat_sector_count': sum(1 for p in valid if p == 0),
                # 分化度：板块涨跌幅的标准差。普涨普跌时低、结构市时高。
                'dispersion': round(pstdev(valid), 3) if len(valid) > 1 else None,
                'strongest': {'sector_name': ordered[0]['sector_name'],
                              'change_pct': _safe_float(ordered[0].get('change_pct'))} if ordered else None,
                'weakest': {'sector_name': ordered[-1]['sector_name'],
                            'change_pct': _safe_float(ordered[-1].get('change_pct'))} if ordered else None,
                'up_stock_total': up_stocks,
                'down_stock_total': down_stocks,
                'flat_stock_total': flat_stocks,
                # ⚠️ 不复用上游 up_down_ratio：它在 down_count=0 时直接给 100.0
                # （银行 2026-09-30 实测），拿它做宽度计算会把"全涨"放大成"极端强势"。
                # 这里按 涨/(涨+跌) 自算，口径稳定。
                'adv_ratio': round(up_stocks / (up_stocks + down_stocks), 4)
                if (up_stocks + down_stocks) else None,
            }

        # ── 2. 逐板块汇总 ──
        by_sector: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_sector.setdefault(r['sector_name'], []).append(r)

        series: List[Dict[str, Any]] = []
        for name, items in by_sector.items():
            m = {it['stat_date']: it for it in items}
            # 按 dates 对齐（某板块某天缺数据就留 None，不 fill —— ffill 会造出
            # "涨跌幅没变的假平点"，与 growth_value 那边同一条约定）
            values = [_safe_float(m[d].get('change_pct')) if d in m else None for d in dates]
            ranks = [cross[d]['rank_of'].get(name) if d in m else None for d in dates]

            valid_pairs = [(v, r) for v, r in zip(values, ranks) if v is not None]
            valid_values = [v for v, _ in valid_pairs]
            valid_ranks = [r for _, r in valid_pairs if r is not None]

            # 复利累计
            cum = 1.0
            for v in valid_values:
                cum *= (1.0 + v / _PCT_DIVISOR)
            cum_pct = (cum - 1.0) * _PCT_DIVISOR

            # 跑赢当日中位数（严格大于；等于中位数不算跑赢）
            beat = [1 if (v is not None and cross[d]['median_pct'] is not None
                          and v > cross[d]['median_pct']) else 0
                    for d, v in zip(dates, values)]
            beat_days = sum(beat)
            # 连续跑赢：从最新一个交易日往回数，遇到不满足就停。
            # 这是"当前是否正在走强"的度量，与"累计涨得多"是两件事。
            streak = 0
            for flag in reversed(beat):
                if flag:
                    streak += 1
                else:
                    break

            # 成交额占比（该板块当日成交额 / 当日全板块合计）
            shares = []
            for d, v in zip(dates, values):
                if v is None or not cross[d]['amount_total']:
                    shares.append(None)
                    continue
                amt = _safe_float(m[d].get('total_trade_amount')) or 0.0
                shares.append(round(amt / cross[d]['amount_total'] * 100, 2))

            share_valid = [s for s in shares if s is not None]
            latest_item = m.get(dates[-1]) or items[-1]
            is_partial = len(valid_values) < len(dates)

            series.append({
                'sector_name': name,
                'values': values,
                'ranks': ranks,
                'cum_pct': round(cum_pct, 2),
                # 表格专用的排序键：完整样本用真实累计涨幅，不完整的沉到地板之下。
                # 展示值仍是 cum_pct，两者只在 is_partial 的行上不同。
                'sort_cum': round(cum_pct, 2) if not is_partial else _PARTIAL_SORT_FLOOR + cum_pct,
                'avg_pct': round(sum(valid_values) / len(valid_values), 3) if valid_values else None,
                'latest_pct': values[-1] if values else None,
                'std_pct': round(pstdev(valid_values), 3) if len(valid_values) > 1 else None,
                'latest_rank': ranks[-1] if ranks else None,
                'first_rank': ranks[0] if ranks else None,
                # 正 = 窗口内排名上升（数字变小），负 = 下滑
                'rank_change': (ranks[0] - ranks[-1]) if (ranks and ranks[0] and ranks[-1]) else None,
                'avg_rank': round(sum(valid_ranks) / len(valid_ranks), 1) if valid_ranks else None,
                'sample_days': len(valid_values),
                'is_partial': is_partial,
                'win_days': sum(1 for v in valid_values if v > 0),
                'lose_days': sum(1 for v in valid_values if v < 0),
                'beat_days': beat_days,
                'streak': streak,
                'amount_share_series': shares,
                'amount_share_latest': shares[-1] if shares else None,
                'amount_share_change': (round(shares[-1] - share_valid[0], 2)
                                        if (shares[-1] is not None and share_valid) else None),
                'amount_avg': round(sum((_safe_float(m[d].get('total_trade_amount')) or 0.0)
                                        for d in dates if d in m) / len(items), 1) if items else None,
                'stock_count': latest_item.get('stock_count'),
                'up_count': latest_item.get('up_count'),
                'down_count': latest_item.get('down_count'),
                'flat_count': latest_item.get('flat_count'),
                # 自算的上涨家数占比，替代不可靠的上游 up_down_ratio
                'up_ratio_latest': (round((latest_item.get('up_count') or 0) /
                                          latest_item['stock_count'], 4)
                                    if latest_item.get('stock_count') else None),
                'top_stock': latest_item.get('top_stock'),
                'top_stock_pct': _safe_float(latest_item.get('top_stock_pct')),
                'bottom_stock': latest_item.get('bottom_stock'),
                'bottom_stock_pct': _safe_float(latest_item.get('bottom_stock_pct')),
            })

        # 排序：完整样本在前（按区间累计降序），样本不完整的沉底。
        # ⚠️ 不这么排的话，「只有 1 天数据」的板块会被顶到最前 —— 它的 cum_pct
        # 其实就是那一天的涨幅，拿它当"区间最强"是错的。
        series.sort(key=lambda x: (x['is_partial'], -(x['cum_pct'] if x['cum_pct'] is not None else -1e9)))

        daily = []
        for d in dates:
            c = cross[d]
            daily.append({
                'trade_date': d,
                'median_pct': round(c['median_pct'], 3) if c['median_pct'] is not None else None,
                'up_sector_count': c['up_sector_count'],
                'down_sector_count': c['down_sector_count'],
                'flat_sector_count': c['flat_sector_count'],
                'dispersion': c['dispersion'],
                'strongest': c['strongest'],
                'weakest': c['weakest'],
                'sector_count': c['sector_count'],
                # ⚠️ 这里的家数是**按板块加总**的，一个股票只会落在一个申万板块里，
                # 所以对同一级别是准的；跨级别不要相加。
                'up_stock_total': c['up_stock_total'],
                'down_stock_total': c['down_stock_total'],
                'flat_stock_total': c['flat_stock_total'],
                'adv_ratio': c['adv_ratio'],
                'amount_total': round(c['amount_total'], 1),
            })

        total = len(series)
        partial = sum(1 for s in series if s['is_partial'])
        complete = total - partial

        trade_days = len(dates)
        return {
            'meta': {
                'sector_type': st,
                'start_date': dates[0],
                'end_date': dates[-1],
                'trade_days': trade_days,
                'requested_days': days,
                'sector_count': total,
                'complete_count': complete,
                'partial_count': partial,
                'is_short_sample': trade_days < SHORT_SAMPLE_DAYS,
                # 前端可以直接把这句话挂到卡片上，不用自己拼口径
                'sample_hint': (
                    f'库里仅有 {trade_days} 个交易日样本（少于 {SHORT_SAMPLE_DAYS} 日），'
                    f'累计涨幅与排名变化噪音较大，建议随日更累积后再解读'
                    if trade_days < SHORT_SAMPLE_DAYS else None
                ),
                'partial_hint': (
                    f'{partial} 个板块未覆盖窗口内全部 {trade_days} 个交易日'
                    f'（上游每天只给部分三级板块），已沉到明细表末尾，且不参与图表排行'
                    if partial else None
                ),
            },
            'dates': dates,
            'series': series,
            'daily': daily,
        }
