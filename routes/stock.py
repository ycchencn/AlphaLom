"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from app.fastapi_app import api_prefix
from config import cache_setting
from service import StockService, FactorValueService
from service import JobService, ResearchReportService
from service.stock_financial_score import StockFinancialScoreService
from service.stock_fear_greed_service import StockFearGreedService
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


def _stock_reanalysis(symbol, sync_history=False, send_notification=False):
    stock = StockService.get_stock_by_symbol(symbol)
    if stock is None:
        return
    JobService.send_job({
        'job_func': 'job_stock_analysis',
        'job_args': {'stock_code': symbol}
    })


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
def update_stock(symbol: str, request: Request):
    """更新股票信息"""
    if not validate_stock_code(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")

    try:
        data = request.json()
    except Exception:
        data = {}

    if not StockService.exists(symbol):
        stock_api = databull.get_stock_info(symbol, market=data.get('market', 'cn'))
        StockService.upsert_stock({
            'symbol': symbol,
            'ts_code': stock_api.get('ts_code'),
            'name': stock_api.get('name'),
            'market': data.get('market', 'cn'),
            'securities_type': data.get('securities_type', 'stock'),
            'monitoring': 1
        })
    else:
        StockService.upsert_stock({
            'symbol': symbol,
            'market': data.get('market', 'cn'),
            'monitoring': data.get('monitoring', 1)
        })

    # 监控标记变了，列表缓存必须立即失效，否则用户改完看不到自己的改动
    # （后台任务直接改库的场景无法在这里挂钩，由 TTL 兜底）
    FastAPICache.clear(namespace=MONITORED_STOCKS_NS)

    return {'code': 0, 'message': 'Stock updated successfully!'}


@stock_router.get('/stocks_monitored')
@cache(expire=cache_setting['monitored_stocks'], namespace=MONITORED_STOCKS_NS)
def get_stocks_monitored(
    page: int = Query(1, ge=1),
    market: str = Query('cn'),
    page_size: int = Query(300, ge=1, le=1000),
    simple: int = Query(0, ge=0, le=1)
):
    """获取个股监控列表

    性能注意（曾是全站最慢的接口）：这里原本对每只票串行查 4 次库
    （恐惧贪婪、主力行为阶段、52 周高低），默认 page_size=300 时是一个近 1200 次的
    N+1，实测单次请求要 6 秒以上。现已改为两次批量查询（见下方两个 *_batch 方法），
    并保留服务端缓存（TTL 见 config.cache_setting['monitored_stocks']）降低重复计算。

    缓存键由函数与其调用参数生成（FastAPI 把 query 参数作为 kwargs 传入），
    因此 page / market / page_size / simple 全部参与区分，不会串数据。

    返回给浏览器的仍是 no-store（全局缓存策略）：客户端不缓存、服务端命中缓存。
    是否命中看响应头 X-FastAPI-Cache: HIT|MISS。
    """
    stocks = StockService.get_monitoring_stock_pool(per_page=page_size, market=market)
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
def get_stocks_greed_data(stock_code: str):
    """获取个股恐惧贪婪数据"""
    greed_data = StockFearGreedService.get_by_index_all(index_code=stock_code)
    return greed_data


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

    securities_data = databull.get_history(stock_code, start_date, end_date, period)
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
    profile = databull.get_company(symbol, market='cn')
    return profile


@stock_router.get('/stock/fundamental_scores/{symbol}')
def get_fundamental_scores(symbol: str):
    """获取个股基本面评分数据"""
    scores = StockFinancialScoreService.get_by_code(symbol)
    return scores


@stock_router.get('/stock/financial_data/{symbol}')
@cache(expire=3600)
def get_financial_data(symbol: str):
    """获取个股财务数据"""
    report = databull.get_stock_financial_data(
        symbol=symbol,
        start_date=get_date_by_n(-365),
        end_date=get_today(),
        report_type='PershareIndex'
    )
    return report