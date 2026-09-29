"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股技术面「专业分析」接口：把已落库的因子库（factor_values）暴露成可用的 API。

背景（为什么新建这个文件）：
    系统已积累了 ~2100 万行因子数据（107 个因子、1800+ 标的），但此前 **routes/ 里
    没有任何 factor 接口** —— 因子只被塞进 LLM prompt，人眼与前端都看不到。
    本模块提供「看板 / 序列 / 仪表盘 / 雷达 / 行业对比 / 选股 / 信号扫描」七类接口。

只读为主：除 `/factor/screen`（纯查询选股）外不写任何数据。
"""

from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.fastapi_app import api_prefix, json_resp
from service.factor_analysis_service import FactorAnalysisService, TECH_FACTOR_GROUPS
from service.factor_service import FactorValueService
from service.factor_selector_service import FactorSelectorService
from service.factor_desc import factor_descriptions
from service import StockService
from service.trading_calendar_service import get_latest_trading_date
from utils.logger import logger

factor_router = APIRouter(prefix=api_prefix, tags=['因子分析'])

# ⚠️ 同步 `def` 路由会被 Starlette 丢进 anyio 线程池；写成 async def 会让同步 DB 查询
# 占死事件循环。故本模块全部用同步 def。详见 routes/market.py 顶部说明。

# 信号扫描回溯「最近多少个有数据的交易日」。
# 日更按监控池分批落库，单日可能只覆盖极少标的（实测 2026-09-28 仅 7 只），
# 只取 1 天会让全库模式几乎扫不到东西；取 5 天覆盖面显著提升，
# 且因为走主键等值扫描，耗时仍在秒级。
RECENT_DATES = 5


# ==================== L0 · 因子字典 ====================
@factor_router.get('/factor/catalog')
def get_factor_catalog():
    """因子字典：全部因子的中文名 / 描述 / 分组（来自 service/factor_desc.py）

    前端用它把 `factor_name` 翻译成人话，并按分组渲染看板。
    """
    groups = TECH_FACTOR_GROUPS
    group_of = {}
    for g in groups:
        for f in g['fields']:
            group_of[f] = g['key']
    items = []
    for it in factor_descriptions:
        if not isinstance(it, dict):
            continue
        f = it.get('field')
        items.append({
            'field': f,
            'name': it.get('name', f),
            'description': it.get('description', ''),
            'formula': it.get('formula', ''),
            'usage': it.get('usage', ''),
            'group': group_of.get(f),
        })
    return json_resp({'groups': groups, 'factors': items})


# ==================== L0 · 因子看板 ====================
@factor_router.get('/factor/stock/{symbol}')
def get_factor_board(
    symbol: str,
    lookback_days: int = Query(400, ge=60, le=2000, description='回看天数（用于计算历史分位）'),
):
    """个股因子看板：全部技术因子的最新值 + 历史分位 + 分组 + 52周区间"""
    try:
        data = FactorAnalysisService.get_factor_board(symbol, lookback_days=lookback_days)
    except Exception as e:
        logger.error(f"get_factor_board failed symbol={symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail='因子看板计算失败')
    return json_resp(data)


@factor_router.get('/factor/stock/{symbol}/series')
def get_factor_series(
    symbol: str,
    names: str = Query(..., description='因子名，逗号分隔，如 mom_20,rsi_14'),
    lookback_days: int = Query(250, ge=10, le=2000),
):
    """多因子时间序列（按日期对齐），供前端画对比曲线"""
    fields = [f.strip() for f in (names or '').split(',') if f.strip()]
    if not fields:
        raise HTTPException(status_code=400, detail='names 不能为空')
    if len(fields) > 12:
        raise HTTPException(status_code=400, detail='一次最多查询 12 个因子')
    return json_resp(FactorAnalysisService.get_factor_series(symbol, fields, lookback_days=lookback_days))


# ==================== L1 · 技术面仪表盘 ====================
@factor_router.get('/factor/stock/{symbol}/dashboard')
def get_factor_dashboard(symbol: str):
    """技术面仪表盘：均线排列 / 关键位 / ATR 动态止损 / 动量-波动象限 / 主力阶段 / 超买超卖热度"""
    try:
        return json_resp(FactorAnalysisService.get_dashboard(symbol))
    except Exception as e:
        logger.error(f"get_factor_dashboard failed symbol={symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail='技术面仪表盘计算失败')


# ==================== L2 · 因子雷达 + 行业对比 ====================
@factor_router.get('/factor/stock/{symbol}/radar')
def get_factor_radar(symbol: str):
    """因子雷达：核心因子转 0~100 分位（反向因子已翻转）"""
    return json_resp(FactorAnalysisService.get_radar(symbol))


@factor_router.get('/factor/stock/{symbol}/industry_rank')
def get_industry_rank(
    symbol: str,
    names: Optional[str] = Query(None, description='指定因子，逗号分隔；默认一组核心因子'),
):
    """行业内因子排名：该股各因子在所属行业个股中的分位"""
    fields = [f.strip() for f in names.split(',') if f.strip()] if names else None
    data = FactorAnalysisService.get_industry_rank(symbol, factor_names=fields)
    if data is None:
        raise HTTPException(status_code=404, detail='该标的无行业归属或同行业样本不足')
    return json_resp(data)


# ==================== L3 · 因子选股 ====================
class ScreenCondition(BaseModel):
    operator: str = Field(..., description="运算符：>= <= > < ==")
    value: float = Field(..., description="阈值")


class ScreenRequest(BaseModel):
    conditions: dict = Field(..., description="因子条件：{factor_name: {operator, value}}")
    asof: Optional[str] = Field(None, description="截止日期 YYYY-MM-DD，默认最新交易日")
    limit: int = Field(100, ge=1, le=1000, description="最多返回数量")
    with_names: bool = Field(True, description="是否附加股票名称")


@factor_router.post('/factor/screen')
def screen_stocks(req: ScreenRequest):
    """按因子条件选股（截至 asof 的最新值）。

    ⚠️ 这里复用的是既有引擎 `FactorSelectorService.select_stocks_by_factors_asof`
    —— 它此前全仓无调用点，本接口是它第一次被接上出口。
    """
    if not req.conditions:
        raise HTTPException(status_code=400, detail='conditions 不能为空')
    try:
        asof = None
        if req.asof:
            from datetime import datetime
            asof = datetime.strptime(req.asof, '%Y-%m-%d').date()
        else:
            asof = get_latest_trading_date()
        result = FactorSelectorService.select_stocks_by_factors_asof(
            asof_date=asof, conditions=req.conditions, limit=req.limit
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"screen_stocks failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail='选股失败')

    tickers = result.get('selected_tickers', [])
    details = result.get('details', {})
    rows = []
    if req.with_names and tickers:
        try:
            info_map = {s['symbol']: s.get('name') for s in (StockService.search_stocks(per_page=10000) or [])}
        except Exception:
            info_map = {}
        for t in tickers:
            rows.append({'symbol': t, 'name': info_map.get(t), **details.get(t, {})})
    else:
        rows = [{'symbol': t, **details.get(t, {})} for t in tickers]

    return json_resp({
        'asof': str(asof),
        'count': len(rows),
        'conditions': req.conditions,
        'rows': rows,
    })


# ==================== L3 · 技术信号扫描（纯规则，零 token） ====================
# 每个信号的定义写在下面的 SIGNALS 里，全部只用「落库因子」，不调 LLM。
SIGNALS = {
    'macd_golden_cross': {
        'label': 'MACD 金叉',
        'desc': 'MACD 上穿信号线（近 3 日内发生）',
    },
    'rsi_oversold': {
        'label': 'RSI 超卖',
        'desc': 'RSI(14) < 30，短期超卖',
    },
    'rsi_overbought': {
        'label': 'RSI 超买',
        'desc': 'RSI(14) > 70，短期超买',
    },
    'ma_bullish': {
        'label': '均线多头排列',
        'desc': 'MA5>MA10>MA20 且连续 3 日确认',
    },
    'near_52w_high': {
        'label': '逼近 52 周新高',
        'desc': '52 周相对位置 > 0.95',
    },
    'near_52w_low': {
        'label': '触及 52 周新低',
        'desc': '52 周相对位置 < 0.05',
    },
    'volume_surge': {
        'label': '量能异动',
        'desc': '5 日均量 ≥ 20 日均量 × 1.3（近期成交明显放大）',
    },
}


@factor_router.get('/factor/signals')
def scan_signals(
    signal: str = Query(..., description=f"信号名：{','.join(SIGNALS.keys())}"),
    scope: str = Query('monitoring', description='扫描范围：monitoring=监控池；all=全库有因子数据的标的'),
    limit: int = Query(100, ge=1, le=1000),
):
    """技术信号扫描：用纯规则在因子库里筛标的（零 LLM 成本）。"""
    if signal not in SIGNALS:
        raise HTTPException(status_code=400, detail=f'未知信号：{signal}，可选：{list(SIGNALS.keys())}')

    from service import FactorValueService as FVS
    from service.trading_calendar_service import get_latest_trading_date as _latest
    asof = _latest()

    if scope == 'monitoring':
        stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000) or []
        universe = [s['symbol'] for s in stocks if s.get('symbol')]
        name_map = {s['symbol']: s.get('name') for s in stocks}
    else:
        universe = None  # 全库模式在下面用因子表自身枚举
        name_map = {}

    hits = _eval_signal(signal, universe, asof, limit)

    if scope != 'monitoring':
        # 补名称
        try:
            name_map = {s['symbol']: s.get('name') for s in (StockService.search_stocks(per_page=10000) or [])}
        except Exception:
            name_map = {}
    for h in hits:
        h['name'] = name_map.get(h['symbol'])

    return json_resp({
        'signal': signal,
        'signal_label': SIGNALS[signal]['label'],
        'asof': str(asof),
        'scope': scope,
        'count': len(hits),
        'rows': hits,
    })


@factor_router.get('/factor/signals/catalog')
def signal_catalog():
    """可用技术信号清单（供前端下拉）"""
    return json_resp([{'key': k, 'label': v['label'], 'desc': v['desc']} for k, v in SIGNALS.items()])


def _eval_signal(signal: str, universe: Optional[List[str]], asof, limit: int) -> List[dict]:
    """
    在因子库上评估单个信号。
    实现：只取「信号需要的因子」，用最新值（或近几日序列）判断，全部单次查询。
    universe=None 时，从因子表自身枚举有数据的标的。
    """
    from models import FactorValue
    from models.database import db_session
    from sqlalchemy import func, and_

    hits: List[dict] = []

    def _recent_dates(factor_name: str, asof) -> List:
        """该因子在 asof 之前「最近 RECENT_DATES 个有数据的交易日」。

        单次轻量 group by（有 idx_factor_ticker_date 覆盖，几十毫秒级）。
        存在的意义：日更按监控池分批落库，单日可能只覆盖极少标的，
        直接取 `MAX(trade_date)` 会落到几乎空的一天，导致全库扫描近乎 0 命中。
        """
        rows = (
            db_session.query(FactorValue.trade_date)
            .filter(FactorValue.factor_name == factor_name, FactorValue.trade_date <= asof)
            .group_by(FactorValue.trade_date)
            .order_by(FactorValue.trade_date.desc())
            .limit(RECENT_DATES)
            .all()
        )
        return [r[0] for r in rows if r[0] is not None]

    def latest_map(factor_name: str) -> dict:
        """{ticker: value}，该因子在 asof 前的最新值。

        ⚠️ 不要写 `group_by(ticker)` + `max(trade_date)` 再回表 join —— 在 2100 万行
        的 EAV 长表上，`trade_date <= asof` 的范围条件会让 MySQL 扫掉上千万行，
        全库模式实测超时。改为「先限定到最近 K 个交易日」再取最大值：

          1. 子查询只扫 factor_name 这一个分片的最近 K 个 trade_date（走
             idx_factor_ticker_date，几十万行）；
          2. 用这些日期做 `trade_date IN (...)` 等值过滤 —— 命中主键首列；
          3. 剩下的行数已经很小，再按 ticker 取 max 就很快。

        这样每只标的取到的仍是「它在这些近邻交易日里最新的一天的值」，
        对日更分批落库的容忍度反而更好（见 FactorSelectorService 的同类说明）。
        """
        # 最近 K 个有数据的交易日
        date_rows = (
            db_session.query(FactorValue.trade_date)
            .filter(FactorValue.factor_name == factor_name, FactorValue.trade_date <= asof)
            .group_by(FactorValue.trade_date)
            .order_by(FactorValue.trade_date.desc())
            .limit(RECENT_DATES)
            .all()
        )
        dates = [r[0] for r in date_rows if r[0] is not None]
        if not dates:
            return {}

        sub = (
            db_session.query(
                FactorValue.ticker.label('ticker'),
                func.max(FactorValue.trade_date).label('md'),
            )
            .filter(FactorValue.factor_name == factor_name,
                    FactorValue.trade_date.in_(dates))
            .group_by(FactorValue.ticker)
        )
        if universe:
            sub = sub.filter(FactorValue.ticker.in_(universe))
        sub = sub.subquery()
        rows = (
            db_session.query(FactorValue.ticker, FactorValue.value)
            .join(sub, and_(FactorValue.ticker == sub.c.ticker, FactorValue.trade_date == sub.c.md,
                            FactorValue.factor_name == factor_name))
            .all()
        )
        return {t: float(v) for t, v in rows if v is not None}

    if signal == 'macd_golden_cross':
        # 判断「最近两个都有 macd / macd_signal 的交易日」是否发生上穿：
        #   macd[d1] <= signal[d1]  且  macd[d2] > signal[d2]
        #
        # ⚠️ 不能按 ticker 循环、每只票查一次 —— 全库模式下 2000+ 只标的 = 2000+ 次
        # 往返（实测直接超时）。
        #
        # ⚠️ 也不能直接对 `factor_name='macd'` 整个分片做 ROW_NUMBER() OVER
        # (PARTITION BY ticker ...)：那要在 65 万行上排序，全库实测 149s。
        # 正确做法是**先用日期窗口把范围砍小**，再排序：
        #   1. 取 macd / macd_signal 各自的最近 K 个交易日（各一次轻量 group by）；
        #   2. `trade_date IN (<这些日期>)` 等值扫描命中主键首列 → 行数降到几千；
        #   3. 只有这几千行才需要按 (ticker, factor_name) 倒序编号取最近 2 条。
        dates = sorted(set(_recent_dates('macd', asof)) | set(_recent_dates('macd_signal', asof)))
        if not dates:
            return hits

        recent = (
            db_session.query(
                FactorValue.ticker.label('ticker'),
                FactorValue.factor_name.label('factor_name'),
                FactorValue.trade_date.label('trade_date'),
                FactorValue.value.label('value'),
                func.row_number().over(
                    partition_by=[FactorValue.ticker, FactorValue.factor_name],
                    order_by=FactorValue.trade_date.desc(),
                ).label('rn'),
            )
            .filter(FactorValue.factor_name.in_(['macd', 'macd_signal']),
                    FactorValue.trade_date.in_(dates),
                    FactorValue.value.isnot(None))
        )
        if universe:
            recent = recent.filter(FactorValue.ticker.in_(universe))
        recent = recent.subquery()

        rows = (
            db_session.query(recent.c.ticker, recent.c.factor_name,
                             recent.c.trade_date, recent.c.value)
            .filter(recent.c.rn <= 2)
            .all()
        )

        # {ticker: {'macd': {date: v}, 'macd_signal': {date: v}}}
        per_ticker: dict = {}
        for t, fn, d, v in rows:
            per_ticker.setdefault(t, {'macd': {}, 'macd_signal': {}})[fn][d] = float(v)

        for t, dmap in per_ticker.items():
            macd, sig = dmap['macd'], dmap['macd_signal']
            common = sorted(set(macd) & set(sig))
            if len(common) < 2:
                continue
            d1, d2 = common[-2], common[-1]
            if macd[d1] <= sig[d1] and macd[d2] > sig[d2]:
                hits.append({'symbol': t, 'macd': round(macd[d2], 4),
                             'macd_signal': round(sig[d2], 4), 'date': str(d2)})
    elif signal in ('rsi_oversold', 'rsi_overbought'):
        m = latest_map('rsi_14')
        thr = 30 if signal == 'rsi_oversold' else 70
        for t, v in m.items():
            if (v < thr) if signal == 'rsi_oversold' else (v > thr):
                hits.append({'symbol': t, 'rsi_14': round(v, 2)})
        hits.sort(key=lambda x: x['rsi_14'], reverse=(signal == 'rsi_overbought'))
    elif signal == 'ma_bullish':
        m = latest_map('is_ma_bullish')
        for t, v in m.items():
            if v >= 1:
                hits.append({'symbol': t, 'is_ma_bullish': int(v)})
    elif signal in ('near_52w_high', 'near_52w_low'):
        # ⚠️ 52week_position 在库里是 0~100（百分比），阈值用 95 / 5，不是 0.95 / 0.05。
        m = latest_map('52week_position')
        for t, v in m.items():
            if (v > 95) if signal == 'near_52w_high' else (v < 5):
                hits.append({'symbol': t, '52week_position': round(v, 4)})
        hits.sort(key=lambda x: x['52week_position'], reverse=(signal == 'near_52w_high'))
    elif signal == 'volume_surge':
        # ⚠️ 阈值取 1.3 而非 1.5：5 日均量与 20 日均量的比值天然被平滑，
        # 实测监控池最大仅 ~1.5，用 1.5 会恒为空。
        m5 = latest_map('turnover_5')
        m20 = latest_map('turnover_20')
        for t in set(m5) & set(m20):
            if m20[t] > 0 and m5[t] / m20[t] >= 1.3:
                hits.append({'symbol': t, 'ratio': round(m5[t] / m20[t], 2),
                             'turnover_5': round(m5[t], 0), 'turnover_20': round(m20[t], 0)})
        hits.sort(key=lambda x: x['ratio'], reverse=True)

    return hits[:limit]
