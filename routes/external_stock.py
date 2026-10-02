"""
 * @author Yc
 * 对外（外部交易决策系统）股票数据接口。
 *
 * 全部只读，且每个接口都显式 `Depends(require_api_user)`（API Key 鉴权 + 每日配额）。
 * 不放在路由级 dependencies 里，是为了避免「路由级 + 端点级」重复执行导致配额被计两次
 * （与 routes.external_portfolio 保持一致）。
 *
 * 数据形状与内部 /api/v1 接口尽量对齐，并复用内部 service 的计算逻辑，不重复实现：
 *   - 股票池：user_stock_pool（按 group_name 标签分组，不独立建表）；
 *   - 个股分析：因子（FactorAnalysisService）、基本面评分（StockFinancialScoreService）、
 *     财务（databull 三大报表，按需 report_type）、恐贪（StockFearGreedService）、
 *     公司概况（databull.get_company_profile）。
 *
 * ⚠️ 所有写库/写缓存的操作都不要出现在这里——对外接口是「数据面」，只读。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_

from models import Stock, UserStockPool
from models.database import db_session
from service.stock import StockService
from service.factor_analysis_service import FactorAnalysisService
from service.factor_service import FactorValueService
from service.stock_financial_score import StockFinancialScoreService
from service.stock_fear_greed_service import StockFearGreedService
from utils.api_auth import require_api_user
from utils.common import get_date_by_n, get_today, validate_stock_code
from utils.data_loader import databull

ext_stock_router = APIRouter(prefix='/stocks', tags=['Stocks'])

# 分组取成员的「未分组」哨兵：分组名本身不太可能叫这个，用它区分「未分组」与真实空串
_UNGROUPED_SENTINEL = '__ungrouped__'

# 财务三大报表 + 股本 + 每股指标的报表类型白名单（与 routes/stock.py 实测保持一致）
FINANCIAL_REPORT_TYPES = ('Balance', 'Income', 'CashFlow', 'Capital', 'PershareIndex')


# ---------------------------------------------------------------------------
# 纯函数：财务行归一化（从 routes/stock.py 平移，保持口径一致）
# ---------------------------------------------------------------------------
def _normalize_fin_date(value):
    """'20241231' / '2024-12-31' → '2024-12-31'；无法识别的原样返回。"""
    if not value:
        return ''
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'
    return s


def _summarize_financial_rows(rows):
    """把上游 `report_table` 扁平字典归一成统一结构（report_date 降序、去重）。"""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        table = row.get('report_table')
        item = dict(table) if isinstance(table, dict) else {}
        raw_date = item.get('report_date') or row.get('report_date') or ''
        raw_announce = item.get('announce_date') or row.get('announce_date') or ''
        item['report_date'] = _normalize_fin_date(raw_date)
        item['announce_date'] = _normalize_fin_date(raw_announce)
        item['report_type'] = row.get('report_type')
        out.append(item)
    seen = set()
    deduped = []
    for r in sorted(out, key=lambda x: x.get('report_date') or '', reverse=True):
        key = r.get('report_date')
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# 股票池
# ---------------------------------------------------------------------------
@ext_stock_router.get('/pools')
def list_stock_pools(user_id: int = Depends(require_api_user)):
    """列出当前 API Key 所属用户的全部股票池分组（含每组股票数）。

    分组是 `user_stock_pool.group_name` 标签；未分组的票归入一个名为「未分组」的虚拟分组。
    """
    return StockService.get_user_pool_groups(user_id)


@ext_stock_router.get('/pools/{group_name}')
def get_stock_pool(
    group_name: str,
    market: str = Query(None, description='市场筛选：cn-沪深, hk-港股, us-美股；不传返回全部'),
    user_id: int = Depends(require_api_user),
):
    """获取某个分组下的全部股票。

    group_name 传真实分组名；传 `__ungrouped__` 返回「未分组」的票。
    """
    ungrouped = group_name == _UNGROUPED_SENTINEL
    sym_q = db_session.query(UserStockPool.symbol).filter(
        UserStockPool.user_id == int(user_id)
    )
    if ungrouped:
        sym_q = sym_q.filter(or_(UserStockPool.group_name.is_(None), UserStockPool.group_name == ''))
    else:
        sym_q = sym_q.filter(UserStockPool.group_name == group_name)
    symbols = [r[0] for r in sym_q.all() if r[0]]
    if not symbols:
        return []
    q = db_session.query(Stock).filter(
        Stock.symbol.in_(symbols), Stock.securities_type == 'stock'
    )
    if market:
        q = q.filter(Stock.market == market)
    return [s.to_dict() for s in q.all()]


@ext_stock_router.get('/watchlist')
def get_watchlist(
    market: str = Query(None, description='市场筛选：cn-沪深, hk-港股, us-美股；不传返回全部'),
    user_id: int = Depends(require_api_user),
):
    """当前用户全部自选股（扁平列表）。

    每条含 symbol / name / market / industry / group_name / ohlc_last（最新报价），
    并批量注入 fear_greed（恐贪指数）、main_force_behavior_phase（主力行为阶段）、
    52week 高低位，便于外部决策系统一次性拿到持仓全景。
    """
    stocks = StockService.get_monitoring_stock_pool(per_page=10000, market=market, user_id=user_id)
    if not stocks:
        return []
    symbols = [s['symbol'] for s in stocks]
    group_map = StockService.get_user_pool_group_map(user_id)
    greed_map = StockFearGreedService.get_latest_by_index_codes(symbols)
    factor_map = FactorValueService.get_latest_factor_values(
        symbols, ('main_force_behavior_phase', '52week_low', '52week_high')
    )
    for s in stocks:
        sym = s['symbol']
        s['group_name'] = group_map.get(sym) or ''
        s['fear_greed'] = (greed_map.get(sym) or {}).get('fear_greed')
        s['main_force_behavior_phase'] = factor_map.get((sym, 'main_force_behavior_phase'), '')
        s['52week_low'] = factor_map.get((sym, '52week_low'), '')
        s['52week_high'] = factor_map.get((sym, '52week_high'), '')
    return stocks


# ---------------------------------------------------------------------------
# 批量分析 / 信号扫描（面向外部交易决策系统：一次调用覆盖整个股票池）
# ---------------------------------------------------------------------------

# 批量接口默认返回的核心因子（技术/动量/波动/位置 + 主力阶段）。
# 均为 factor_values 里的合法 factor_name；调用方可用 factors 参数覆盖。
_DEFAULT_BATCH_FACTORS = [
    'rsi_14', 'macd', 'macd_signal', 'macd_hist', 'is_ma_bullish',
    'mom_composite', 'bias_composite', 'vol_composite',
    'closing_strength', '52week_position', 'atr_14', 'main_force_behavior_phase',
]


@ext_stock_router.get('/batch/analysis')
def batch_analysis(
    symbols: str = Query(None, description='逗号分隔的股票代码；不传则分析当前用户整个股票池'),
    factors: str = Query(None, description=f'逗号分隔的因子名；不传用默认核心因子集：{",".join(_DEFAULT_BATCH_FACTORS)}'),
    market: str = Query(None, description='市场筛选（仅在分析整个池子时生效）：cn/hk/us'),
    user_id: int = Depends(require_api_user),
):
    """批量分析：一次调用返回多只票的核心分析数据（供外部决策系统扫描/排序整个股票池）。

    高效实现：股票、因子值、恐贪、基本面评分各 **一次批量查询**（而非每只票 N 次往返），
    因此即使池子有上百只也只计 1 次调用配额。

    每条返回：symbol / name / market / industry / group_name / ohlc_last（最新报价）/
    fear_greed / composite_score（基本面综合分）/ factors{因子:值}。
    """
    if symbols:
        codes = [s.strip() for s in symbols.split(',') if s.strip()]
        for c in codes:
            if not validate_stock_code(c):
                raise HTTPException(status_code=400, detail=f'Invalid symbol: {c}')
        stocks = [s.to_dict() for s in db_session.query(Stock).filter(
            Stock.symbol.in_(codes), Stock.securities_type == 'stock').all()]
        # 保持调用方传入的顺序
        order = {c: i for i, c in enumerate(codes)}
        stocks.sort(key=lambda x: order.get(x['symbol'], 10 ** 9))
    else:
        stocks = StockService.get_monitoring_stock_pool(per_page=10000, market=market, user_id=user_id)

    if not stocks:
        return []

    syms = [s['symbol'] for s in stocks]
    names = factors.split(',') if factors else _DEFAULT_BATCH_FACTORS
    names = [f.strip() for f in names if f.strip()]

    group_map = StockService.get_user_pool_group_map(user_id)
    factor_map = FactorValueService.get_latest_factor_values(syms, names)
    greed_map = StockFearGreedService.get_latest_by_index_codes(syms)
    score_map = StockFinancialScoreService.get_by_codes(syms)

    out = []
    for s in stocks:
        sym = s['symbol']
        row = {
            'symbol': sym,
            'name': s.get('name'),
            'market': s.get('market'),
            'industry': s.get('industry'),
            'group_name': group_map.get(sym) or '',
            'ohlc_last': s.get('ohlc_last'),
            'fear_greed': (greed_map.get(sym) or {}).get('fear_greed'),
            'composite_score': (score_map.get(sym) or {}).get('composite_score'),
            'factors': {f: factor_map.get((sym, f)) for f in names},
        }
        out.append(row)
    return out


@ext_stock_router.get('/signals')
def scan_signals_ext(
    signal: str = Query(..., description='信号名，如 macd_golden_cross / rsi_oversold / ma_bullish / near_52w_high / volume_surge 等'),
    limit: int = Query(100, ge=1, le=1000),
    user_id: int = Depends(require_api_user),
):
    """技术信号扫描：范围限定为**当前用户股票池**，用纯规则在因子库里筛选命中标的（零 LLM 成本）。

    返回命中的标的列表（含名称、信号值、asof 交易日）。
    """
    # 局部导入，避免模块加载期把整个 factor 路由拉进来（也防潜在的循环导入）
    from routes.factor import SIGNALS, _eval_signal
    from service.trading_calendar_service import get_latest_trading_date

    if signal not in SIGNALS:
        raise HTTPException(status_code=400, detail=f'未知信号：{signal}，可选：{list(SIGNALS.keys())}')

    asof = get_latest_trading_date()
    universe = StockService.get_user_pool_symbols(user_id)
    if not universe:
        return {'signal': signal, 'signal_label': SIGNALS[signal]['label'],
                'asof': str(asof), 'count': 0, 'rows': []}

    hits = _eval_signal(signal, universe, asof, limit)
    name_map = {s['symbol']: s.get('name') for s in
                StockService.get_monitoring_stock_pool(per_page=10000, user_id=user_id)}
    for h in hits:
        h['name'] = name_map.get(h['symbol'])

    return {
        'signal': signal,
        'signal_label': SIGNALS[signal]['label'],
        'asof': str(asof),
        'count': len(hits),
        'rows': hits,
    }


# ---------------------------------------------------------------------------
# 个股分析
# ---------------------------------------------------------------------------
@ext_stock_router.get('/{symbol}/profile')
def get_stock_profile_ext(symbol: str, user_id: int = Depends(require_api_user)):
    """公司基本信息（名称、主营、行业、注册资本等）。"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    resp = databull.get_company_profile(symbol, market='cn')
    return resp.get('data') if isinstance(resp, dict) else resp


@ext_stock_router.get('/{symbol}/fundamentals')
def get_fundamentals(symbol: str, user_id: int = Depends(require_api_user)):
    """个股基本面评分（盈利能力 / 成长 / 估值 / 财务质量等维度打分）。"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    return StockFinancialScoreService.get_by_code(symbol)


@ext_stock_router.get('/{symbol}/factors')
def get_factors(
    symbol: str,
    lookback_days: int = Query(400, ge=60, le=2000, description='回看天数（用于历史分位）'),
    user_id: int = Depends(require_api_user),
):
    """技术面因子：dashboard（均线排列/关键位/ATR/象限/主力阶段/超买超卖）+ board（全因子最新值+分位）。"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    try:
        dashboard = FactorAnalysisService.get_dashboard(symbol, asset_type='stock')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'技术面仪表盘计算失败: {e}')
    try:
        board = FactorAnalysisService.get_factor_board(symbol, lookback_days=lookback_days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'因子看板计算失败: {e}')
    return {'symbol': symbol, 'dashboard': dashboard, 'board': board}


@ext_stock_router.get('/{symbol}/financials')
def get_financials(
    symbol: str,
    report_type: str = Query('PershareIndex', description='报表类型：Balance/Income/CashFlow/Capital/PershareIndex'),
    periods: int = Query(12, ge=1, le=40, description='返回最近 N 期'),
    user_id: int = Depends(require_api_user),
):
    """个股财务数据（默认每股指标，可按 report_type 切换）。

    返回结构与内部 /stock/financial_data 一致：{symbol, report_type, periods, items[]}。
    """
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    if report_type not in FINANCIAL_REPORT_TYPES:
        raise HTTPException(
            status_code=400, detail=f'Invalid report_type, expect one of {FINANCIAL_REPORT_TYPES}'
        )
    start_date = get_date_by_n(-max(periods * 100, 400))
    end_date = get_today()
    resp = databull.get_stock_financial_data(
        symbol=symbol, start_date=start_date, end_date=end_date, report_type=report_type
    )
    rows = resp.get('data') if isinstance(resp, dict) else resp
    if not isinstance(rows, list):
        rows = []
    items = _summarize_financial_rows(rows)[:periods]
    return {'symbol': symbol, 'report_type': report_type, 'periods': periods, 'items': items}


@ext_stock_router.get('/{symbol}/fear-greed')
def get_fear_greed(symbol: str, user_id: int = Depends(require_api_user)):
    """个股最新恐惧贪婪指数记录（含 trade_date）。无数据时返回 null。"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    data = StockFearGreedService.get_latest_by_index_codes([symbol])
    return data.get(symbol)


@ext_stock_router.get('/{symbol}/analysis')
def get_analysis(symbol: str, user_id: int = Depends(require_api_user)):
    """个股分析聚合（一次调用拿全）：概况 + 基本面评分 + 技术因子 + 恐贪 + 最新财务摘要。

    任一分项取数失败不影响其它分项（失败项返回 null），便于外部决策系统稳健消费。
    """
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail='Invalid symbol')

    result = {'symbol': symbol, 'profile': None, 'fundamentals': None,
              'factors': None, 'fear_greed': None, 'financials': None}

    # 公司概况
    try:
        resp = databull.get_company_profile(symbol, market='cn')
        result['profile'] = resp.get('data') if isinstance(resp, dict) else resp
    except Exception as e:
        result['profile'] = {'error': str(e)}

    # 基本面评分
    try:
        result['fundamentals'] = StockFinancialScoreService.get_by_code(symbol)
    except Exception as e:
        result['fundamentals'] = {'error': str(e)}

    # 技术因子
    try:
        result['factors'] = {
            'dashboard': FactorAnalysisService.get_dashboard(symbol, asset_type='stock'),
            'board': FactorAnalysisService.get_factor_board(symbol, lookback_days=400),
        }
    except Exception as e:
        result['factors'] = {'error': str(e)}

    # 恐贪
    try:
        fg = StockFearGreedService.get_latest_by_index_codes([symbol])
        result['fear_greed'] = fg.get(symbol)
    except Exception as e:
        result['fear_greed'] = {'error': str(e)}

    # 最新财务摘要（每股指标，近 8 期）
    try:
        start_date = get_date_by_n(-max(8 * 100, 400))
        end_date = get_today()
        resp = databull.get_stock_financial_data(
            symbol=symbol, start_date=start_date, end_date=end_date, report_type='PershareIndex'
        )
        rows = resp.get('data') if isinstance(resp, dict) else resp
        result['financials'] = {
            'report_type': 'PershareIndex', 'periods': 8,
            'items': _summarize_financial_rows(rows if isinstance(rows, list) else [])[:8],
        }
    except Exception as e:
        result['financials'] = {'error': str(e)}

    return result

