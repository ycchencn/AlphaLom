"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from fastapi import APIRouter, Query, Request, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from app.fastapi_app import api_prefix
from utils.auth import get_current_user_id
from utils.logger import logger
from service import InvestmentPortfolioService, PortfolioAssetsService
from service import (
    DailyPnLRecordService,
    PortfolioDailySummaryService,
    PortfolioTransactionService
)
from models import Stock, StockIndustry
from models.database import db_session
from utils.common import is_etf
from backtest.quant_stat_report import generate_html_report_string
from fastapi.responses import HTMLResponse
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache

portfolio_router = APIRouter(prefix=api_prefix, tags=['投资组合'])

# ⚠️ 路由的 async/sync 不是风格问题，是并发度问题：
# Service 层全部是同步实现（pymysql / requests / redis-py），写 `async def` 会让这些阻塞调用
# 直接占死唯一的事件循环，把一个慢请求变成全站卡顿（并发度 1）。
# 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程），才是正确形态。
# 只有需要 `await` 的（`await request.json()`、`await FastAPICache.clear()`）才保留 async。

# 组合列表 / 详情的缓存命名空间：装饰器与「写后失效」两处共用同一常量，
# 避免字符串写得不一致导致失效静默落空（表现是新建完组合列表里看不到）。
PORTFOLIO_LIST_NS = 'investment_portfolios'
PORTFOLIO_DETAIL_NS = 'investment_portfolio_detail'

# ⚠️ 白名单刻意**不含** user_id / portfolio_id：
# 这两个字段是隔离与主键的依据，绝不能让调用方从 body 里指定 ——
# 否则任何人都能把组合挂到别人名下（越权写），或指定主键覆盖别人的行。
PORTFOLIO_WRITABLE_FIELDS = {
    'name', 'strategy_type', 'total_position_pct', 'base_currency',
    'position_plan', 'position_plan_reason', 'init_cash', 'current_cash',
    'llm_prompt', 'llm_setting', 'desc', 'enable', 'market',
}

PORTFOLIO_REQUIRED_FIELDS = {'name', 'init_cash', 'current_cash', 'total_position_pct'}


def make_response(data=None, msg="success", code=200):
    return {'code': code, 'msg': msg, 'data': data}


def _pick_writable(data):
    return {k: v for k, v in data.items() if k in PORTFOLIO_WRITABLE_FIELDS}


def get_owned_portfolio(portfolio_id, user_id):
    """
    取「当前用户名下」的组合，取不到就抛 404。

    ⚠️ 越权一律回 **404 而不是 403**：403 等于告诉对方「这个 id 存在但不是你的」，
    等于把别人组合的存在性泄露出去。404 对「不存在」和「不属于你」是同一个响应。
    ⚠️ 所有按 portfolio_id 的读写接口都必须先过这里 —— 组合 id 是自增整数，可枚举。
    """
    prof = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    if not prof or prof.get('user_id') != int(user_id):
        raise HTTPException(status_code=404, detail='Portfolio not found')
    return prof


def enrich_assets_with_industry(assets):
    """给持仓明细补充 `industry` 字段（行业分布饼图要用）。

    行业权威来源是 `stock_industry` 表（覆盖池内+池外所有出现过的票），
    兜底用 `stocks.industry`（监控池内票的旧字段），再兜底用 databull 公司资料按需拉取写回，
    三者都没有才标成「其他」。

    ⚠️ 不依赖 `stocks` 表：组合持仓可能包含监控池外的票，`stocks.industry` 覆盖不全，
    之前就因此导致饼图一堆「其他」。
    """
    if not assets:
        return
    codes = [a.get('stock_code') for a in assets if a.get('stock_code')]
    if not codes:
        for a in assets:
            a['industry'] = '其他'
        return

    # 1) 权威表 stock_industry
    industry_map = {}
    try:
        rows = db_session.query(StockIndustry.symbol, StockIndustry.industry).filter(
            StockIndustry.symbol.in_(codes)
        ).all()
        for sym, ind in rows:
            if ind:
                industry_map[sym] = ind
    except Exception as e:
        logger.warning(f"enrich assets industry (stock_industry) failed: {e}")

    # 2) 兜底 stocks.industry（监控池内票）
    missing = [c for c in codes if c not in industry_map]
    if missing:
        try:
            rows = db_session.query(Stock.symbol, Stock.industry).filter(
                Stock.symbol.in_(missing)
            ).all()
            for sym, ind in rows:
                if ind and sym not in industry_map:
                    industry_map[sym] = ind
        except Exception as e:
            logger.warning(f"enrich assets industry (stocks) failed: {e}")

    # 3) 仍缺失 → 按需从 databull 拉取并写回 stock_industry（best-effort）
    missing = [c for c in codes if c not in industry_map]
    if missing:
        from service.stock import StockService
        for sym in missing:
            try:
                fields = StockService.company_profile_fields(sym, 'cn')
                ind = fields.get('industry')
                if ind:
                    industry_map[sym] = ind
                    try:
                        db_session.merge(StockIndustry(symbol=sym, industry=ind, source='databull'))
                        db_session.commit()
                    except Exception:
                        db_session.rollback()
            except Exception as e:
                logger.warning(f"fetch industry for {sym} failed: {e}")

    for a in assets:
        sym = a.get('stock_code')
        if sym in industry_map:
            a['industry'] = industry_map[sym]
        elif is_etf(sym):
            # ETF / 基金没有「行业」概念，单独归类，避免污染「其他」扇区
            a['industry'] = 'ETF/基金'
        else:
            a['industry'] = '其他'


@portfolio_router.get('/investment_portfolios')
@cache(expire=360, namespace=PORTFOLIO_LIST_NS)
def get_investment_portfolios(user_id: int = Depends(get_current_user_id)):
    """获取**当前用户**的策略列表数据

    `user_id` 用 `Depends` 注入而不是从 query 读：它会被 FastAPI 作为 kwargs 传给
    endpoint，从而天然进入 fastapi_cache 的缓存键（用户维度自动隔离），
    同时前端也无法通过传参查看别人的策略。
    """
    portfolios = InvestmentPortfolioService.get_all(user_id=user_id)
    for prof in portfolios:
        prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(prof.get('portfolio_id'))
        if prof['summary'] is None:
            prof['summary'] = {'total_unrealized_pnl': 0, 'total_assets': 0}
        prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(prof.get('portfolio_id'))
        del prof['llm_prompt']
        del prof['position_plan']
    return portfolios


@portfolio_router.get('/investment_portfolios_info/{portfolio_id}')
@cache(expire=3600, namespace=PORTFOLIO_DETAIL_NS)
def get_investment_portfolios_info(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """获取策略详情（仅限本人组合）"""
    prof = get_owned_portfolio(portfolio_id, user_id)
    prof['portfolio_id'] = portfolio_id
    prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(portfolio_id)
    if prof['summary'] is None:
        prof['summary'] = {'total_unrealized_pnl': 0, 'total_assets': 0}
    prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    enrich_assets_with_industry(prof['assets'])
    prof['daily_pnl'] = DailyPnLRecordService.get_all_by_portfolio_id(portfolio_id)
    return prof


@portfolio_router.get('/portfolio_daily_summary/{portfolio_id}')
@cache(expire=3600)
def get_portfolio_daily_summary(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """获取策略每日统计数据（仅限本人组合）"""
    get_owned_portfolio(portfolio_id, user_id)
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)
    return summary_list


@portfolio_router.get('/portfolio_transaction/{portfolio_id}')
def get_portfolio_transaction(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """获取策略交易记录（仅限本人组合）"""
    get_owned_portfolio(portfolio_id, user_id)
    _list = PortfolioTransactionService.get_by_portfolio_id(portfolio_id)
    return _list


@portfolio_router.get('/portfolio_quantstat/{portfolio_id}')
def gen_quantstat(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """生成量化绩效报告（仅限本人组合）"""
    get_owned_portfolio(portfolio_id, user_id)
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)
    df = pd.DataFrame(summary_list)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    equity = df['total_assets']
    html_content, perf_data = generate_html_report_string(equity, title="量化策略绩效报告")
    InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, {"quantstat_json": perf_data})
    return HTMLResponse(content=html_content)


@portfolio_router.post('/investment_portfolios')
async def create_portfolio(request: Request, user_id: int = Depends(get_current_user_id)):
    """新建投资组合（自动归属于当前用户）"""
    try:
        data = await request.json()
    except Exception:
        data = {}

    if not isinstance(data, dict):
        return make_response(msg='Request must be JSON', code=400)

    missing = [f for f in PORTFOLIO_REQUIRED_FIELDS if data.get(f) is None]
    if missing:
        return make_response(msg=f'Missing required fields: {", ".join(missing)}', code=400)

    payload = _pick_writable(data)
    # ⚠️ 归属由服务端写入，不取 body 里的值（白名单里也没有 user_id，这里是双保险）
    payload['user_id'] = int(user_id)
    payload.setdefault('strategy_type', 1)
    # ⚠️ 不再手工生成 portfolio_id：线上主键是 int AUTO_INCREMENT，写 uuid 会被
    # 非严格模式静默截断为 0（第一次落库 id=0、第二次主键冲突）。交给数据库分配。

    try:
        new_id = InvestmentPortfolioService.add(payload)
        if new_id is not None:
            # 列表缓存必须立刻失效：前端建完会马上重拉列表，否则 6 分钟内看不到自己的新组合
            await FastAPICache.clear(namespace=PORTFOLIO_LIST_NS)
            return make_response(data={'portfolio_id': new_id}, msg='Created successfully')
        return make_response(msg='Failed to create (name may already exist)', code=400)
    except Exception as e:
        logger.error(f"Error creating portfolio: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.put('/investment_portfolios/{portfolio_id}')
async def update_portfolio(portfolio_id: str, request: Request,
                           user_id: int = Depends(get_current_user_id)):
    """更新投资组合（仅限本人组合）"""
    try:
        data = await request.json()
    except Exception:
        data = {}

    if not isinstance(data, dict):
        return make_response(msg='Request must be JSON', code=400)

    payload = _pick_writable(data)
    if not payload:
        return make_response(msg='No valid updatable fields provided', code=400)

    get_owned_portfolio(portfolio_id, user_id)

    try:
        success = InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, payload)
        if success:
            await FastAPICache.clear(namespace=PORTFOLIO_LIST_NS)
            await FastAPICache.clear(namespace=PORTFOLIO_DETAIL_NS)
            return make_response(msg='Updated successfully')
        return make_response(msg='Update failed', code=400)
    except Exception as e:
        logger.error(f"Error updating portfolio {portfolio_id}: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.delete('/investment_portfolios/{portfolio_id}')
async def delete_portfolio(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """删除投资组合（仅限本人组合）

    同 update：需要 await 清缓存，故本路由是 async（内部库操作全是同步的）。
    """
    get_owned_portfolio(portfolio_id, user_id)

    try:
        success = InvestmentPortfolioService.delete_by_portfolio_id(portfolio_id)
        if success:
            await FastAPICache.clear(namespace=PORTFOLIO_LIST_NS)
            await FastAPICache.clear(namespace=PORTFOLIO_DETAIL_NS)
            return make_response(msg='Deleted successfully')
        return make_response(msg='Delete failed', code=400)
    except Exception as e:
        logger.error(f"Error deleting portfolio {portfolio_id}: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.put('/portfolio/{portfolio_id}')
async def update_portfolio_legacy(portfolio_id: str, request: Request,
                                 user_id: int = Depends(get_current_user_id)):
    """兼容旧路径的组合更新（依赖与鉴权同 update_portfolio，勿单独绕开）"""
    return await update_portfolio(portfolio_id, request, user_id)


@portfolio_router.post('/portfolio/{portfolio_id}/analyze')
async def trigger_position_plan_analysis(portfolio_id: str, request: Request,
                                        user_id: int = Depends(get_current_user_id)):
    """手动触发 AI 调仓分析（仅限本人组合）"""
    from backtest.strategy.ai_position_plan_daily import job_position_plan_daily

    get_owned_portfolio(portfolio_id, user_id)

    try:
        data = await request.json()
    except Exception:
        data = {}
    send_feishu = bool(data.get('send_feishu', False))

    try:
        logger.info(f"手动触发 AI 调仓分析: portfolio_id={portfolio_id}, send_feishu={send_feishu}")
        # ⚠️ 必须丢线程池：job_position_plan_daily 内部全是同步阻塞调用
        # （DB + databull + LLM create_completion，一次可达数十秒）。
        # 直接在 async 路由里调用会占死唯一的事件循环 → 分析期间全站接口一起卡住。
        # run_in_threadpool 会把请求级 ContextVar（db_session 作用域令牌）复制进工作线程，
        # 会话隔离不受影响。
        await run_in_threadpool(job_position_plan_daily, portfolio_id=portfolio_id, send_feishu=send_feishu)
        return make_response(msg='Analysis completed successfully')
    except Exception as e:
        logger.error(f"AI 调仓分析失败: {e}")
        return make_response(msg=f'Analysis failed: {str(e)}', code=500)