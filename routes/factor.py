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

import time
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from app.fastapi_app import api_prefix, json_resp
from service.factor_analysis_service import FactorAnalysisService, TECH_FACTOR_GROUPS
from service.factor_service import FactorValueService
from service.factor_selector_service import FactorSelectorService, exclude_etf_condition
from service.factor_desc import factor_descriptions
from service import StockService
from service.trading_calendar_service import get_latest_trading_date
from service.etf_service import FACTOR_BACKFILL_DAYS
from utils.auth import get_current_user, get_current_user_id
from utils.logger import logger
from utils.redis_obj import redis_obj

# 全站登录制：整个 router 加登录鉴权（见 etf.py 顶部说明）。
# ⚠️ router 级依赖返回值不注入 endpoint，不污染缓存键、不改函数签名。
factor_router = APIRouter(prefix=api_prefix, tags=['因子分析'],
                          dependencies=[Depends(get_current_user)])

# ⚠️ 同步 `def` 路由会被 Starlette 丢进 anyio 线程池；写成 async def 会让同步 DB 查询
# 占死事件循环。故本模块全部用同步 def。详见 routes/market.py 顶部说明。

# 信号扫描回溯「最近多少个有数据的交易日」。
# 日更按监控池分批落库，单日可能只覆盖极少标的（实测 2026-09-28 仅 7 只），
# 只取 1 天会让全库模式几乎扫不到东西；取 5 天覆盖面显著提升，
# 且因为走主键等值扫描，耗时仍在秒级。
RECENT_DATES = 5

# 标的类型：'stock'（个股，默认）/ 'etf'。
# ⚠️ 只有**真正需要区分**的接口才声明它，不搞「全模块统一加一个用不上的参数」——
#    因子看板 / 序列 / 雷达都只按 ticker 查 factor_values，个股与 ETF 走的是同一张表、
#    同一套因子，多一个参数只会让人以为口径有差别。
# 目前需要它的两处：
#   1. `/dashboard` —— 决定走 get_etf_history 还是 get_stock_history（拿错接口不报错，
#      而是返回陈旧残缺的日线，均线/关键位/ATR 全错得静默无声）；
#   2. `/industry_rank` —— 个股按行业取样本，ETF 没有行业，改按全站 ETF 池取样本。
_ASSET_TYPE_DESC = "标的类型：stock=个股（默认）/ etf=ETF。决定行情接口与横向对比样本的选取"


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


# ==================== L0 · 因子重算 ====================
# 「一键重算」：看板上的数据是 factor_values 里的落库值，日更只按监控池跑一遍，
# 新加的标的 / 因子算法升级过的标的不会立刻反映到看板上。这里提供手动触发口。
#
# ⚠️ 刻意**只投队列、不在请求里同步算**：单个标的 1100 天窗口的因子计算要几十秒
# （上游行情请求 + pandas 全量因子 + 整段重写），放在请求里必然超时；而队列是
# prefetch=1 串行消费，塞进一条重任务还会顶住后面所有人的任务（见 routes/market.py
# 手动刷新闻同款取舍）。所以本接口只保证「已入队」，完成与否由前端轮询 status 判断。
#
# 冷却用 Redis SET NX EX（单键原子、多 worker 天然互斥），超时返 429 + Retry-After，
# 与 routes/market.py::refresh_news_digest 同一套写法。
FACTOR_RECALC_COOLDOWN_SEC = 300
FACTOR_RECALC_LOCK_KEY = 'alphalom:factor_recalc'


class FactorRecalcRequest(BaseModel):
    asset_type: str = Field('stock', pattern='^(stock|etf)$', description=_ASSET_TYPE_DESC)
    # full=True → save_last=False：先 delete_by_ticker 再整段重写，补齐 3 年历史（慢，~1分钟）
    # full=False → save_last=True：只重算最新一个交易日，与日更口径一致（快，~几秒）
    full: bool = Field(False, description='是否整段重写历史（true=补 3 年，false=只算最新一天）')


@factor_router.put('/factor/stock/{symbol}/recalc')
def recalc_factor(symbol: str, req: FactorRecalcRequest):
    """手动触发因子重算（入队异步执行，个股与 ETF 同一入口）。

    ⚠️ 需要登录（router 级已有 get_current_user）：本操作会向队列塞一条重任务
    （full 模式单只实测约 1 分钟），不设门槛等于任何人都能无限塞队列堵住别人。

    ⚠️ job_args **不新增任何键**，与 job_update_stock_factor 现有签名严格一致：
    新增键会要求 web 与 job_server 同时部署，否则旧消费者 `job_func(**job_args)`
    直接 TypeError（见 routes/stock.py::_dispatch_stock_analysis 的同类告诫）。

    ⚠️ asset_type 必须由调用方显式传，不靠代码号段猜：562xxx 曾被当个股取数，
    因子被 dropna 掉后整段重写 = 把已有的正确数据清成空。
    """
    symbol = (symbol or '').strip()
    if not symbol:
        raise HTTPException(status_code=400, detail='symbol 不能为空')

    lock_key = f'{FACTOR_RECALC_LOCK_KEY}:{symbol}'
    # 键值写**入队时刻的时间戳**（不是 '1'）：状态接口靠它与库里 MAX(update_time)
    # 比较来判断重算是否已完成，冷却语义（NX + TTL）与去重语义共用一个键。
    if not redis_obj.set(lock_key, str(int(time.time())), nx=True, ex=FACTOR_RECALC_COOLDOWN_SEC):
        try:
            waiting = max(int(redis_obj.ttl(lock_key)), 1)
        except Exception:
            waiting = FACTOR_RECALC_COOLDOWN_SEC
        raise HTTPException(
            status_code=429,
            detail=f'该标的刚触发过重算，请 {waiting} 秒后再试',
            headers={'Retry-After': str(waiting)},
        )

    try:
        from service import JobService
        JobService.send_job({
            'job_func': 'job_update_stock_factor',
            'job_args': {
                'stock_code': symbol,
                'asset_type': req.asset_type,
                'save_last': not req.full,
                'time_period': -FACTOR_BACKFILL_DAYS if req.full else -400,
            },
        })
    except Exception as e:
        # 投递失败要把冷却键放掉，否则用户要干等 5 分钟才能重试
        try:
            redis_obj.delete(lock_key)
        except Exception:
            pass
        logger.error(f'[factor] 投递因子重算任务失败 {symbol}: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='任务投递失败，请稍后重试')

    return json_resp({
        'symbol': symbol,
        'asset_type': req.asset_type,
        'full': req.full,
        # 前端据此提示「已入队，稍后自动刷新」；full=True 要明说会重写全部历史
        'message': '重算任务已提交',
        'cooldown_sec': FACTOR_RECALC_COOLDOWN_SEC,
    })


@factor_router.get('/factor/stock/{symbol}/recalc_status')
def get_factor_recalc_status(symbol: str):
    """重算进度查询：是否已入队 + 当前因子的新鲜度（前端据此自动刷新）。

    ⚠️ 队列本身不回报执行结果（Redis Stream 只有 ACK，job_server 也不写状态表），
    所以这里的「是否完成」用**库里的最新 update_time 是否晚于冷却键的写入时间**判定，
    而不是查任务状态 —— 冷却是 NX 写入、值即入队时刻，天然就是这个语义。
    """
    symbol = (symbol or '').strip()
    lock_key = f'{FACTOR_RECALC_LOCK_KEY}:{symbol}'
    dispatched_at = None
    try:
        raw = redis_obj.get(lock_key)
        if raw:
            dispatched_at = datetime.fromtimestamp(int(raw))
    except Exception as e:
        # Redis 抖动不该让「刷新中」这个辅助信息把整个状态接口打挂
        logger.warning(f'[factor] 读取重算状态失败 {symbol}: {e}')

    data = FactorValueService.get_ticker_stats(symbol)
    last_update = data.get('last_update')
    done = bool(dispatched_at and last_update and last_update >= dispatched_at)
    return json_resp({
        'symbol': symbol,
        'dispatched_at': dispatched_at.strftime('%Y-%m-%d %H:%M:%S') if dispatched_at else None,
        'done': done,
        'last_update': last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else None,
        'latest_trade_date': str(data.get('latest_trade_date')) if data.get('latest_trade_date') else None,
        'history_days': data.get('history_days', 0),
        'factor_count': data.get('factor_count', 0),
    })


# ==================== L1 · 技术面仪表盘 ====================
@factor_router.get('/factor/stock/{symbol}/dashboard')
def get_factor_dashboard(
    symbol: str,
    asset_type: str = Query('stock', pattern='^(stock|etf)$', description=_ASSET_TYPE_DESC),
):
    """技术面仪表盘：均线排列 / 关键位 / ATR 动态止损 / 动量-波动象限 / 主力阶段 / 超买超卖热度"""
    try:
        return json_resp(FactorAnalysisService.get_dashboard(symbol, asset_type=asset_type))
    except Exception as e:
        logger.error(f"get_factor_dashboard failed symbol={symbol} asset_type={asset_type}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail='技术面仪表盘计算失败')


# ==================== L2 · 因子雷达 + 行业对比 ====================
@factor_router.get('/factor/stock/{symbol}/radar')
def get_factor_radar(symbol: str):
    """因子雷达：核心因子转 0~100 分位（反向因子已翻转）"""
    return json_resp(FactorAnalysisService.get_radar(symbol))


@factor_router.get('/factor/stock/{symbol}/industry_rank')
def get_industry_rank(
    symbol: str,
    asset_type: str = Query('stock', pattern='^(stock|etf)$', description=_ASSET_TYPE_DESC),
    names: Optional[str] = Query(None, description='指定因子，逗号分隔；默认一组核心因子'),
):
    """横向对比排名：个股比同行业，ETF 比全站 ETF 池（响应带 scope/peer_label）

    个股无行业归属、或样本不足 3 个时返回 404（前端按「不渲染该卡片」处理）。
    """
    fields = [f.strip() for f in names.split(',') if f.strip()] if names else None
    data = FactorAnalysisService.get_peer_rank(symbol, factor_names=fields, asset_type=asset_type)
    if data is None:
        raise HTTPException(status_code=404, detail='该标的无同类样本或样本不足')
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
def screen_stocks(req: ScreenRequest, user_id: int = Depends(get_current_user_id)):
    """按因子条件选股（截至 asof 的最新值）。

    ⚠️ 需要登录：全库选股是重查询（因子表 2000 万行级扫描），且是「按条件拿全市场
    候选」的能力，开放给未登录访客易被脚本批量调用打爆资源。这里至少要求登录用户
    （user_id 同时进入缓存键，天然按用户隔离）。

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
                    FactorValue.trade_date.in_(dates),
                    exclude_etf_condition())
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
                    FactorValue.value.isnot(None),
                    exclude_etf_condition())
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
