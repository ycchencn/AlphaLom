"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import uuid
import pandas as pd
from fastapi import APIRouter, Query, Request, HTTPException
from app.fastapi_app import api_prefix, cache
from utils.logger import logger
from service import InvestmentPortfolioService, PortfolioAssetsService
from service import (
    DailyPnLRecordService,
    PortfolioDailySummaryService,
    PortfolioTransactionService
)
from backtest.quant_stat_report import generate_html_report_string
from fastapi.responses import HTMLResponse

portfolio_router = APIRouter(prefix=api_prefix, tags=['投资组合'])

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


@portfolio_router.get('/investment_portfolios')
async def get_investment_portfolios():
    """获取策略列表数据"""
    portfolios = InvestmentPortfolioService.get_all()
    for prof in portfolios:
        prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(prof.get('portfolio_id'))
        if prof['summary'] is None:
            prof['summary'] = {'total_unrealized_pnl': 0, 'total_assets': 0}
        prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(prof.get('portfolio_id'))
        del prof['llm_prompt']
        del prof['position_plan']
    return portfolios


@portfolio_router.get('/investment_portfolios_info/{portfolio_id}')
async def get_investment_portfolios_info(portfolio_id: str):
    """获取策略详情"""
    prof = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    prof['portfolio_id'] = portfolio_id
    prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(portfolio_id)
    if prof['summary'] is None:
        prof['summary'] = {'total_unrealized_pnl': 0, 'total_assets': 0}
    prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    prof['daily_pnl'] = DailyPnLRecordService.get_all_by_portfolio_id(portfolio_id)
    return prof


@portfolio_router.get('/portfolio_daily_summary/{portfolio_id}')
async def get_portfolio_daily_summary(portfolio_id: str):
    """获取策略每日统计数据"""
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)
    return summary_list


@portfolio_router.get('/portfolio_transaction/{portfolio_id}')
async def get_portfolio_transaction(portfolio_id: str):
    """获取策略交易记录"""
    _list = PortfolioTransactionService.get_by_portfolio_id(portfolio_id)
    return _list


@portfolio_router.get('/portfolio_quantstat/{portfolio_id}')
async def gen_quantstat(portfolio_id: str):
    """生成量化绩效报告"""
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)
    df = pd.DataFrame(summary_list)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    equity = df['total_assets']
    html_content, perf_data = generate_html_report_string(equity, title="量化策略绩效报告")
    InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, {"quantstat_json": perf_data})
    return HTMLResponse(content=html_content)


@portfolio_router.post('/investment_portfolios')
async def create_portfolio(request: Request):
    """新建投资组合"""
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
    payload['portfolio_id'] = str(uuid.uuid4())
    payload.setdefault('strategy_type', 1)

    try:
        success = InvestmentPortfolioService.add(payload)
        if success:
            return make_response(data={'portfolio_id': payload['portfolio_id']}, msg='Created successfully')
        return make_response(msg='Failed to create (name may already exist)', code=400)
    except Exception as e:
        logger.error(f"Error creating portfolio: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.put('/investment_portfolios/{portfolio_id}')
async def update_portfolio(portfolio_id: str, request: Request):
    """更新投资组合"""
    try:
        data = await request.json()
    except Exception:
        data = {}

    if not isinstance(data, dict):
        return make_response(msg='Request must be JSON', code=400)

    payload = _pick_writable(data)
    if not payload:
        return make_response(msg='No valid updatable fields provided', code=400)

    if not InvestmentPortfolioService.get_by_portfolio_id(portfolio_id):
        return make_response(msg='Portfolio not found', code=404)

    try:
        success = InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, payload)
        if success:
            return make_response(msg='Updated successfully')
        return make_response(msg='Update failed', code=400)
    except Exception as e:
        logger.error(f"Error updating portfolio {portfolio_id}: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.delete('/investment_portfolios/{portfolio_id}')
async def delete_portfolio(portfolio_id: str):
    """删除投资组合"""
    if not InvestmentPortfolioService.get_by_portfolio_id(portfolio_id):
        return make_response(msg='Portfolio not found', code=404)

    try:
        success = InvestmentPortfolioService.delete_by_portfolio_id(portfolio_id)
        if success:
            return make_response(msg='Deleted successfully')
        return make_response(msg='Delete failed', code=400)
    except Exception as e:
        logger.error(f"Error deleting portfolio {portfolio_id}: {e}")
        return make_response(msg=str(e), code=500)


@portfolio_router.put('/portfolio/{portfolio_id}')
async def update_portfolio_legacy(portfolio_id: str, request: Request):
    """兼容旧路径的组合更新"""
    return await update_portfolio(portfolio_id, request)


@portfolio_router.post('/portfolio/{portfolio_id}/analyze')
async def trigger_position_plan_analysis(portfolio_id: str, request: Request):
    """手动触发 AI 调仓分析"""
    from backtest.strategy.ai_position_plan_daily import job_position_plan_daily

    if not InvestmentPortfolioService.get_by_portfolio_id(portfolio_id):
        return make_response(msg='Portfolio not found', code=404)

    try:
        data = await request.json()
    except Exception:
        data = {}
    send_feishu = bool(data.get('send_feishu', False))

    try:
        logger.info(f"手动触发 AI 调仓分析: portfolio_id={portfolio_id}, send_feishu={send_feishu}")
        job_position_plan_daily(portfolio_id=portfolio_id, send_feishu=send_feishu)
        return make_response(msg='Analysis completed successfully')
    except Exception as e:
        logger.error(f"AI 调仓分析失败: {e}")
        return make_response(msg=f'Analysis failed: {str(e)}', code=500)