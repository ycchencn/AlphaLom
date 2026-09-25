"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query, Request, HTTPException, Depends
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from app.fastapi_app import api_prefix
from config import cache_setting
from service import StockService, FactorValueService
from service import JobService, ResearchReportService
from service.stock_financial_score import StockFinancialScoreService
from service.stock_fear_greed_service import StockFearGreedService
from utils.auth import get_current_user_id
from utils.data_loader import databull
from utils.common import get_today, get_date_by_n, validate_stock_code
from utils.logger import logger

stock_router = APIRouter(prefix=api_prefix, tags=['个股'])

# ⚠️ 路由的 async/sync 决定并发度，不是代码风格：
# Service 层与 databull 客户端全是同步实现（pymysql / requests），写成 `async def` 会让这些
# 阻塞调用直接占死唯一的事件循环 —— 一个请求慢下来，全站请求都跟着排队（并发度退化为 1）。
# 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程），才是这里的正确形态。
# 只有真正需要 `await` 的才保留 async：`update_stock` 要 `await request.json()` 与
# `await FastAPICache.clear()`。带 `@cache` 的同步函数同样受支持（库内部走 run_in_threadpool）。

# 监控股票列表的缓存命名空间：装饰器与失效处共用，避免字符串写不一致导致失效落空
MONITORED_STOCKS_NS = 'stocks_monitored'


def _dispatch_stock_analysis(symbol: str) -> None:
    """把「个股分析」任务投递到任务队列（异步执行，实现见 job/job_stock_analysis.py）。

    分析链路：恐惧贪婪走势 → 技术因子 → DCF 估值 → 技术信号 → 最新报价。
    这些正是监控列表 / 详情页要展示的字段（fear_greed、main_force_behavior_phase、
    52week_low/high、ohlc_last...），而它们平时只由 20:10 的日更任务按股票池全量重算，
    所以**新入池的票必须立刻单独跑一次**，否则在第二天日更前页面上一片空白。

    注意两点：
    1. job_args 刻意与线上「重新分析」接口保持完全一致（只传 stock_code），
       不新增键 —— 新增键会要求 web 与 job_server 同时部署，否则消费者 TypeError；
       send_notification 走 job 函数默认值 False。
    2. 队列是 Redis Stream 消费组、prefetch=1 串行消费（job/job_server.py），
       这里只保证「已入队」，不保证何时算完。
    """
    JobService.send_job({
        'job_func': 'job_stock_analysis',
        'job_args': {'stock_code': symbol}
    })


def _stock_reanalysis(symbol):
    """对已在库的个股重新投递一次分析（语义见 _dispatch_stock_analysis）"""
    if StockService.get_stock_by_symbol(symbol) is None:
        return
    _dispatch_stock_analysis(symbol)


@stock_router.get('/stock/dcf_research_report/{stock_code}')
@cache(expire=3600)
def get_dcf_research_report(stock_code: str):
    """获取个股研报数据"""
    report = ResearchReportService.get_by_code(stock_code=stock_code, report_type=1)
    return report


@stock_router.get('/stock/tech_analysis_report/{stock_code}')
def get_tech_analysis_report(stock_code: str):
    """获取技术分析报告"""
    report = ResearchReportService.get_by_code(stock_code=stock_code, report_type=2)
    return report


@stock_router.get('/stock/research_reports/{stock_code}')
def get_research_reports(stock_code: str):
    """获取个股的深度研报列表"""
    reports = ResearchReportService.query_reports(stock_code=stock_code, report_type=3, limit=200)
    result = []
    for r in reports:
        d = r.to_dict()
        d.pop('content_text', None)
        d.pop('content_json', None)
        result.append(d)
    return result


@stock_router.get('/stock/research_report/{report_id}')
def get_research_report_detail(report_id: int):
    """获取单个研报详情"""
    from models import ResearchReport
    from models.database import db_session
    try:
        report = db_session.query(ResearchReport).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching report {report_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@stock_router.put('/stocks/{symbol}')
async def update_stock(symbol: str, request: Request,
                       user_id: int = Depends(get_current_user_id)):
    """
    把个股加入/移出**当前用户**的股票池（monitoring=1 加入，0 移出）。

    多用户改造后这里有两层数据，职责必须分开：
      - `user_stock_pool`（用户私有）：谁加了这只票 —— 真正的写入目标；
      - `stocks.*`（全局共享）：名称/市场/公司概况等按标的算的公共字段。
    `stocks.monitoring` 不再由本接口直写，改由 `StockService.sync_monitoring_flag`
    按「还有没有别的用户引用」统一重算 —— 它是并集标记，日更任务靠它枚举要更新的标的。
    """
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")

    try:
        data = await request.json()
    except Exception:
        data = {}

    monitoring = data.get('monitoring', 1)
    # 一次查询同时拿到「是否存在」与更新前的监控状态，省掉原先的 exists() 往返
    before = StockService.get_stock_by_symbol(symbol, fields=['monitoring', 'securities_type'])

    # ⚠️ market 只在调用方**显式传**时才覆盖已有标的：原来的 `data.get('market','cn')`
    # 会把不传 market 的调用（如 StockMonitor.vue）一律写成 cn，港股/美股标的被记错市场，
    # 之后按 market 分段查询就再也查不到它了。
    market = data.get('market') or (before or {}).get('market') or 'cn'

    if before is not None:
        # 已在库：只更新调用方显式传来的字段（不含 monitoring，见 docstring）
        StockService.upsert_stock({'symbol': symbol, 'market': market})
    else:
        # 不在库：从 API 补全基础信息（名称 + 公司概况）后入库
        StockService.ensure_stock_from_api(
            symbol,
            market=market,
            securities_type=data.get('securities_type', 'stock'),
        )

    # 用户私有层：加入 / 移出自己的池子（内部会同步 stocks.monitoring 并集标记）
    if monitoring:
        StockService.add_to_user_pool(user_id, symbol, market=market,
                                      monitor_by=data.get('monitor_by') or 'user')
    else:
        StockService.remove_from_user_pool(user_id, symbol)

    # 池子变了，列表缓存必须立即失效，否则用户改完看不到自己的改动。
    # （缓存键里含 user_id，这里是按 namespace 整片清，多清几个用户的键无副作用）
    await FastAPICache.clear(namespace=MONITORED_STOCKS_NS)

    # 「新增入库」或「这只票此前没人在监控」= 它的分析数据必然不存在，必须立刻投递一次
    # 个股分析（异步），否则用户加完看到的只有名称和代码。
    # ⚠️ 用「全站并集」（before.monitoring）而不是「我有没有加过」来判定：别的用户早就
    # 加过、而分析数据是公共的且已存在，再投一次只是白烧一次 DCF + 因子计算。
    # 需要强制重算走「重新分析」接口（PUT /stock/re_analysis/{symbol}）。
    securities_type = data.get('securities_type') or (before or {}).get('securities_type') or 'stock'
    just_added = securities_type == 'stock' and bool(monitoring) and (
        before is None or not before.get('monitoring')
    )
    if just_added:
        _dispatch_stock_analysis(symbol)

    return {
        'code': 0,
        'message': 'Stock updated successfully!',
        # 前端据此提示「分析已提交、稍后刷新」；False = 本次只是改了已有标的的字段
        'analysis_triggered': just_added,
    }


@stock_router.delete('/stocks/{symbol}')
async def delete_stock(symbol: str, user_id: int = Depends(get_current_user_id)):
    """
    把个股移出**当前用户**的股票池（等价于 PUT monitoring=0，语义更直白）。

    只删用户私有层那一行，`stocks` 表里的公共字段（名称/概况/行情）保留 ——
    别的用户可能还在关注它，而且这些字段是公摊数据，删了下次还得重新取。
    """
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")

    removed = StockService.remove_from_user_pool(user_id, symbol)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{symbol} 不在你的股票池中")

    await FastAPICache.clear(namespace=MONITORED_STOCKS_NS)
    return {'code': 0, 'message': 'ok'}


@stock_router.get('/stocks_monitored')
@cache(expire=cache_setting['monitored_stocks'], namespace=MONITORED_STOCKS_NS)
def get_stocks_monitored(
    page: int = Query(1, ge=1),
    market: str = Query(None, description='市场筛选：cn-沪深, hk-港股, us-美股；不传/为空则返回全部市场'),
    page_size: int = Query(300, ge=1, le=1000),
    simple: int = Query(0, ge=0, le=1),
    user_id: int = Depends(get_current_user_id)
):
    """获取**当前用户**的个股池列表

    ⚠️ `user_id` 用 `Depends(get_current_user_id)` 注入（而不是从 query 里读）：
    FastAPI 会把依赖解析结果作为 kwargs 传给 endpoint，而 fastapi_cache 的默认
    key builder 正是把 kwargs 拼进缓存键，所以用户维度**天然进 key**、不会串数据；
    同时前端也无法通过传参看别人的池子。

    性能注意（曾是全站最慢的接口）：这里原本对每只票串行查 4 次库
    （恐惧贪婪、主力行为阶段、52 周高低），默认 page_size=300 时是一个近 1200 次的
    N+1，实测单次请求要 6 秒以上。现已改为两次批量查询（见下方两个 *_batch 方法），
    并保留服务端缓存（TTL 见 config.cache_setting['monitored_stocks']）降低重复计算。

    缓存键由函数与其调用参数生成（FastAPI 把 query 参数与依赖注入值都作为 kwargs 传入），
    因此 page / market / page_size / simple / user_id 全部参与区分。

    返回给浏览器的仍是 no-store（全局缓存策略）：客户端不缓存、服务端命中缓存。
    是否命中看响应头 X-FastAPI-Cache: HIT|MISS。
    """
    stocks = StockService.get_monitoring_stock_pool(per_page=page_size, market=market,
                                                    user_id=user_id)
    if simple == 1:
        return stocks

    symbols = [s['symbol'] for s in stocks]

    # 两次批量查询取代 N+1：每只票原本 4 次往返，现在是 2 次固定往返
    greed_map = StockFearGreedService.get_latest_by_index_codes(symbols)
    factor_map = FactorValueService.get_latest_factor_values(
        symbols, ('main_force_behavior_phase', '52week_low', '52week_high')
    )

    for stock in stocks:
        symbol = stock['symbol']
        # 字段与默认值保持与原实现完全一致（因子缺失时为 ''，恐惧贪婪缺失时为 {"fear_greed": 0}）
        stock['greed_data'] = greed_map.get(symbol) or {"fear_greed": 0}
        stock['main_force_behavior_phase'] = factor_map.get(
            (symbol, 'main_force_behavior_phase'), ''
        )
        stock['52week_low'] = factor_map.get((symbol, '52week_low'), '')
        stock['52week_high'] = factor_map.get((symbol, '52week_high'), '')
    return stocks


@stock_router.get('/stock/greed_data/{stock_code}')
@cache(expire=3600)
def get_stocks_greed_data(
    stock_code: str,
    limit: int = Query(250, ge=1, le=1000, description='返回最近 N 个交易日的记录'),
):
    """
    获取个股恐惧贪婪数据（按交易日倒序）。

    ⚠️ `limit` 默认从 250 起（约一年交易日）：Service 层的默认值是 60，
    那个数量只够画两三个月的曲线，而个股详情页与大盘页一样要展示「近一年走势」。
    存量调用方若不传参，拿到的仍是 250 条（比原来的 60 条多，是超集，不会少数据）。
    """
    greed_data = StockFearGreedService.get_by_index_all(index_code=stock_code, limit=limit)
    return greed_data


@stock_router.get('/stock_search')
def search_stock_catalog(
    keyword: str = Query('', description='代码或名称关键字'),
    market: str = Query('cn'),
    limit: int = Query(50, ge=1, le=200),
):
    """
    按代码/名称在全市场股票目录中模糊搜索（databull get_stock_list 的服务端 search 过滤）。
    用于「添加个股监控」弹窗的搜索联想。
    """
    return StockService.search_stock_catalog(keyword, market=market, limit=limit)


@stock_router.get('/stocks/{stock_code}')
@cache(expire=3600)
def get_stock(stock_code: str):
    """获取个股信息"""
    if not validate_stock_code(stock_code):
        raise HTTPException(status_code=400, detail="Invalid stock code")
    stock = StockService.get_stock_by_symbol(stock_code)
    stock['tech_indicator'] = {
        '52week_low': FactorValueService.get_latest_factor_value(ticker=stock_code, factor_name='52week_low'),
        '52week_high': FactorValueService.get_latest_factor_value(ticker=stock_code, factor_name='52week_high'),
    }
    return stock


@stock_router.get('/stock_history/{stock_code}')
@cache(expire=3600)
def get_stock_history(
    stock_code: str,
    period: str = Query('d'),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """获取个股历史行情"""
    if not validate_stock_code(stock_code):
        raise HTTPException(status_code=400, detail="Invalid stock code")

    dayn = 365 * 1
    if start_date is None:
        start_date = get_date_by_n(-1 * dayn)
    if end_date is None:
        end_date = get_today()

    securities_data = databull.get_stock_history(stock_code, start_date, end_date, period)
    securities_data.reset_index(inplace=True)
    securities_data['date'] = securities_data['date'].dt.strftime('%Y-%m-%d')
    securities_data_dict = securities_data.to_dict(orient='records')
    return securities_data_dict


@stock_router.put('/stock/re_analysis/{symbol}')
def stock_re_analysis(symbol: str):
    """重新分析个股"""
    _stock_reanalysis(symbol)
    return {'code': 0, 'message': 'Stock updated successfully!'}


@stock_router.put('/stock/re_analysis_dcf/{symbol}')
def stock_re_analysis_dcf(symbol: str):
    """重新分析个股DCF"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid stock code")
    if StockService.get_stock_by_symbol(symbol) is None:
        raise HTTPException(status_code=404, detail="Stock not found")
    JobService.send_job({
        'job_func': 'job_stock_dcf_model_analysis',
        'job_args': {'_stock_code': symbol, 'send_notification': False}
    })
    return {'code': 0, 'message': 'Stock updated successfully!'}


@stock_router.get('/stocks/profile/{symbol}')
@cache(expire=3600)
def get_stock_profile(symbol: str):
    """获取公司信息"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    # SDK 的 get_company_profile 返回 {code, data} 信封（旧本地客户端已解包），
    # 这里取内层 data 再返回，前端是按 profile 的字段直接读的。
    resp = databull.get_company_profile(symbol, market='cn')
    return resp.get('data') if isinstance(resp, dict) else resp


@stock_router.get('/stock/fundamental_scores/{symbol}')
def get_fundamental_scores(symbol: str):
    """获取个股基本面评分数据"""
    scores = StockFinancialScoreService.get_by_code(symbol)
    return scores


# 财务三大报表 + 股本 + 每股指标。上游 /cn/stock/financial_data 靠 report_type 区分，
# ⚠️ SDK 默认值是 'Balance' —— 漏传不报错但会静默拿到资产负债表，
# 所以这里一律**显式必传**，且用白名单校验，避免前端拼错报表名拿到不相干数据。
FINANCIAL_REPORT_TYPES = ('Balance', 'Income', 'CashFlow', 'Capital', 'PershareIndex')


def _summarize_financial_rows(rows):
    """把上游 `report_table` 扁平字典归一成前端好用的结构。

    上游每行的真正载荷在 `report_table` 里（扁平 snake_case 字段，float 或 None），
    外层只有 id/stock_code/report_type/report_date/announce_date。
    这里**把 report_table 摊平到顶层**并统一日期格式：
      - `report_date` 统一成 'YYYY-MM-DD'（上游在 report_table 内是 'YYYYMMDD'，
        外层又是 'YYYY-MM-DD'，两种格式并存 → 前端排序/显示会踩坑）；
      - 顺带按 report_date 降序返回（上游顺序不稳定，同一日期偶尔重复）。
    """
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        table = row.get('report_table')
        item = dict(table) if isinstance(table, dict) else {}

        # report_date / announce_date 可能出现在两处，优先取 report_table 内的，再回退外层
        raw_date = item.get('report_date') or row.get('report_date') or ''
        raw_announce = item.get('announce_date') or row.get('announce_date') or ''
        item['report_date'] = _normalize_fin_date(raw_date)
        item['announce_date'] = _normalize_fin_date(raw_announce)
        item['report_type'] = row.get('report_type')
        out.append(item)

    # 降序：最新一期在前（同日期去重，保留先出现的）
    seen = set()
    deduped = []
    for r in sorted(out, key=lambda x: x.get('report_date') or '', reverse=True):
        key = r.get('report_date')
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def _normalize_fin_date(value):
    """'20241231' / '2024-12-31' → '2024-12-31'；无法识别的原样返回。"""
    if not value:
        return ''
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'
    return s


@stock_router.get('/stock/financial_data/{symbol}')
@cache(expire=3600)
def get_financial_data(
        symbol: str,
        report_type: str = Query(
            'PershareIndex',
            description='报表类型：Balance/Income/CashFlow/Capital/PershareIndex'
        ),
        periods: int = Query(12, ge=1, le=40, description='返回最近 N 期'),
):
    """获取个股财务数据（默认每股指标，可按报表切换）。

    ⚠️ 三个坑（都在本项目里踩过/验证过）：
    1. 必须**显式**传 report_type —— SDK 默认是 'Balance'，漏传会静默拿错报表；
    2. SDK 返回的是 `{code, data}` 信封，SDK **不自动解包**，必须自己取内层 data，
       否则前端拿到的是包着信封的一层壳（历史上 /stock/profile 就是这个坑）。
    3. 上游 report_type 实测有 5 种（文档只列了 4 种，`PershareIndex` 文档里没有但可用）
       → 以实测为准。这里的白名单与实测保持一致。

    另：上游只接受日期窗口、不提供「最近 N 期」语义，所以窗口按 periods 反推
    （一期 ≈ 一季，用 periods*100 天覆盖，再在 Python 侧截断到 periods 条）。
    """
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if report_type not in FINANCIAL_REPORT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report_type, expect one of {FINANCIAL_REPORT_TYPES}"
        )

    # periods 期 → 取数窗口。多留一倍冗余，避免跨年/停牌导致窗口内不满 periods 期。
    start_date = get_date_by_n(-max(periods * 100, 400))
    end_date = get_today()

    resp = databull.get_stock_financial_data(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        report_type=report_type,
    )
    # 解包 {code, data} 信封（SDK 不自动解包）
    rows = resp.get('data') if isinstance(resp, dict) else resp
    if not isinstance(rows, list):
        rows = []

    items = _summarize_financial_rows(rows)[:periods]
    return {
        'symbol': symbol,
        'report_type': report_type,
        'periods': periods,
        'items': items,
    }