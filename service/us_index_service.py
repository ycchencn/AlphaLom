"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 美股大盘指数卡片（支撑「市场监控 → 美股大盘」页）。

 数据源：上游 `get_us_index_history`（日线，**没有实时 tick**）。
 ⚠️ `get_realtime(..., market='us')` 实测 404（上游美股只提供日线，历史接口
 带 `data_scope: 'local'|'realtime'` 字段但本地缓存下取到的就是已收盘日线），
 所以卡片展示的是**最近一个交易日的收盘**，不是盘中价。刷新按钮给的是
 「重新取一遍日线」，别在前端文案里写「实时」。

 ⚠️ **窗口首根的 chg_pct / change_amount 被上游置 0**：实测
 `get_us_index_history('GSPC', '2026-08-01', '2026-10-07')` 的第一根
 （2026-08-03）chg_pct=0.0，第二根起才正常。所以「当日涨跌」不能用窗口内
 最后一根的 chg_pct 之前那根来对照 —— 要多取一根自然日作为前置锚点，
 或者干脆**自己用相邻收盘价算**。本模块统一自己算（`_chg_from_closes`），
 不依赖上游的派生字段，口径与沪深大盘页保持一致。

 ⚠️ **各指数的「最新交易日」可能不一致**：实测同一天请求，GSPC/NDX/IXIC/DJI
 最新到 2026-10-06，而 VIX 已经有 2026-10-07 那根。所以「数据时间」取
 各指数最新交易日的**最大值**，同时把每个指数自己的 trade_date 原样带给前端，
 别在前端假设所有卡片是同一天。
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from databull import DataBullError

from service.index_card_common import (
    FETCH_WORKERS,
    build_card,
    history_window,
    normalize_bars,
)
from utils.data_loader import databull
from utils.logger import logger

# 上游实测「行情可取」的美股指数全集（get_us_index_list(quote_ready_only=True)
# 返回 total=13486 但 items 只有 11 条 —— total 是**目录全量**，真正 quote_ready
# 的只有这 11 个；其余 1.3 万条是目录条目、没有 K 线，传进去会 404）。
#
# ⚠️ 顺序 = 页面展示顺序，按「代表性优先」排：四大宽基 → 补充宽基 → 交易所 →
# 波动率 → 全收益。不要按字母排，VIX 会被塞到中间看不出它是什么。
US_INDEX_CODES: List[str] = [
    'GSPC',    # 标普500
    'IXIC',    # 纳斯达克综合
    'NDX',     # 纳斯达克100
    'DJI',     # 道琼斯工业
    'SP400',   # 标普中盘400
    'NYA',     # 纽约证券交易所综合
    'XAX',     # 美国交易所综合
    'OEX',     # 标普100
    'DJT',     # 道琼斯运输
    'VIX',     # 芝加哥期权交易所波动率指数
    'SPXTR',   # 标普500全收益
]

# 名称兜底：正常从上游 `data.index.name` 取中文名（实测 11 个都有），
# 万一上游某条缺 name，至少还能显示代码而不是空白卡片。
US_INDEX_NAME_FALLBACK = {
    'GSPC': '标普500',
    'IXIC': '纳斯达克综合指数',
    'NDX': '纳斯达克100',
    'DJI': '道琼斯工业平均',
    'SP400': '标普中盘400',
    'NYA': '纽约证券交易所综合指数',
    'XAX': '美国交易所综合指数',
    'OEX': '标普100指数',
    'DJT': '道琼斯运输平均指数',
    'VIX': '芝加哥期权交易所波动率指数',
    'SPXTR': '标普500全收益指数',
}

# VIX 是**波动率**指数、不是价格指数：涨=恐慌。它跟价格指数并排放在同一行
# 卡片里时，「红=涨」会让 VIX 涨（市场恐慌）显示成红色，看着像利好。
# 前端据此反转 VIX 的着色方向，这里给出唯一判定依据，避免两处各写一套。
VOLATILITY_CODES = {'VIX'}


class UsIndexError(RuntimeError):
    """取数失败。路由层转成 502/404，不把栈打给前端。"""


def _fetch_bars(code: str, start: str, end: str) -> Dict[str, Any]:
    """取单个指数的日线，归一化成升序 bar 列表。

    返回 `{'code', 'name', 'category', 'bars': [{date, close, open, high, low}...]}`。
    取不到就**抛**，由调用方决定是跳过还是整体失败。
    """
    try:
        res = databull.get_us_index_history(code, start, end, as_dataframe=False)
    except DataBullError as e:
        raise UsIndexError(f'美股指数 {code} 取数失败: {e}') from e
    except Exception as e:  # noqa: BLE001
        raise UsIndexError(f'美股指数 {code} 取数异常: {e}') from e

    if not isinstance(res, dict):
        raise UsIndexError(f'美股指数 {code} 返回结构异常: {type(res).__name__}')
    data = res.get('data') or {}
    items = data.get('items') or []
    if not items:
        raise UsIndexError(f'美股指数 {code} 无数据')

    meta = data.get('index') or {}
    bars = normalize_bars(items)
    if not bars:
        raise UsIndexError(f'美股指数 {code} 收盘价全为空')

    return {
        'code': meta.get('quote_symbol') or code,
        'name': meta.get('name') or US_INDEX_NAME_FALLBACK.get(code) or code,
        'category': meta.get('category') or 'broad',
        'bars': bars,
    }


def _build_card(item: Dict[str, Any]) -> Dict[str, Any]:
    """把一条日线序列压成一张卡片。

    ⚠️ 算法在 `index_card_common.build_card`（与沪深页共用），这层只补美股特有的
    category / is_volatility。**别在这层再写一份涨跌幅算法** —— 两页口径必须同源，
    否则同一天两个页面的「当日涨跌」会在小数点后分叉。
    """
    return build_card(
        item['bars'],
        code=item['code'],
        name=item['name'],
        category=item['category'],
        is_volatility=item['code'] in VOLATILITY_CODES,
    )


class UsIndexService:
    """美股指数卡片数据。"""

    @staticmethod
    def get_cards() -> Dict[str, Any]:
        """取全部美股指数的卡片数据。

        :return: ``{meta, items}``；``items`` 是**扁平列表**、按
            `US_INDEX_CODES` 的原序（代表性优先：标普/纳指/道指在前，VIX 靠后）。
            **不按 category 分组** —— 沪深大盘页的指数卡片就是一行平铺、没有分组，
            两个页面保持一致；上游的 category 字段仍带在每项里（前端可按需取用）。
            单个指数失败只跳过它（``meta.failed`` 记下原因），全部失败才抛
            —— 十张卡因为一条脏数据全白不划算。
        """
        start_c, end_c = history_window()

        results: Dict[str, Any] = {}
        failed: List[Dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {pool.submit(_fetch_bars, c, start_c, end_c): c for c in US_INDEX_CODES}
            for fut, code in futures.items():
                try:
                    item = fut.result()
                    results[code] = _build_card(item)
                except UsIndexError as e:
                    logger.warning(f'us index card failed for {code}: {e}')
                    failed.append({'code': code, 'reason': str(e)})

        if not results:
            raise UsIndexError('全部美股指数取数失败')

        # ⚠️ 按 US_INDEX_CODES 原序输出，不要按 dict 的插入序（并发完成顺序不定，
        # 会让卡片每次刷新都换位置）或按涨跌幅排（每次刷新顺序都在跳）。
        cards = [results[c] for c in US_INDEX_CODES if c in results]

        # ⚠️ 各指数最新交易日可能不同（VIX 实测比 GSPC 多一天），所以要定一个
        # 「主日期」：取**非波动率**指数的最新交易日的众数（价格指数才是市场
        # 本身的日历，VIX 提前一根属于上游自己的更新节奏，不代表大盘多了一天）。
        #
        # ⚠️ 别用 max()：VIX 领先时max 会让其余 10 个指数全被标成「落后一天」，
        # 页面顶部显示「10 个指数数据滞后」，看着像故障。
        # stale = 真正比主日期落后的（停更/漏更新），这才是要提示的。
        price_dates = [c['trade_date'] for c in cards if not c['is_volatility']]
        if price_dates:
            main_date = max(set(price_dates), key=price_dates.count)
        else:
            main_date = max(c['trade_date'] for c in cards)
        stale = [c['code'] for c in cards if c['trade_date'] < main_date]
        # 比主日期还新的（正常只有 VIX）不标 stale，但要单独列出来，
        # 前端可以在卡片上按各自 trade_date 显示「数据日期」，避免看着像错位。
        ahead = [c['code'] for c in cards if c['trade_date'] > main_date]

        return {
            'meta': {
                'data_date': main_date,
                'total': len(cards),
                'expected': len(US_INDEX_CODES),
                'stale_codes': stale,
                'ahead_codes': ahead,
                'failed': failed,
                'trade_timezone': 'America/New_York',
                # 没有实时 tick（get_realtime market='us' 实测 404），只有收盘日线。
                'realtime_available': False,
            },
            'items': cards,
        }
