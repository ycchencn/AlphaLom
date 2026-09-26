"""
 * @author Yc
 * 对外（外部/第三方）投资组合数据接口。
 *
 * 全部只读，且每枚接口都显式 `Depends(require_api_user)`（用 API Key 鉴权 + 每日配额）。
 * 不放在路由级 dependencies 里，是为了避免「路由级 + 端点级」重复执行导致配额被计两次。
 *
 * 数据形状与内部 /api/v1 接口尽量对齐，但剥离敏感字段（llm_prompt / position_plan /
 * llm_setting / quantstat_json），并复用 routes.portfolio 的越权防护 get_owned_portfolio。
"""

from fastapi import APIRouter, Depends, HTTPException

from routes.portfolio import (
    _default_summary,
    enrich_assets_with_industry,
    get_owned_portfolio,
)
from service import (
    DailyPnLRecordService,
    InvestmentPortfolioService,
    PortfolioAssetsService,
    PortfolioDailySummaryService,
    PortfolioTransactionService,
)
from utils.api_auth import require_api_user

ext_portfolio_router = APIRouter(prefix='/portfolios', tags=['Portfolios'])

# 对外响应里绝不外泄的字段
_SENSITIVE_KEYS = {
    'llm_prompt',
    'position_plan',
    'position_plan_reason',
    'llm_setting',
    'quantstat_json',
}


def _strip(prof: dict) -> dict:
    for k in _SENSITIVE_KEYS:
        prof.pop(k, None)
    return prof


@ext_portfolio_router.get('')
def list_portfolios(user_id: int = Depends(require_api_user)):
    """列出当前 API Key 所属用户的所有投资组合（含最新每日汇总，不含持仓明细）。"""
    portfolios = InvestmentPortfolioService.get_all(user_id=user_id)
    result = []
    for prof in portfolios:
        _strip(prof)
        summary = PortfolioDailySummaryService.get_last_by_portfolio_id(prof.get('portfolio_id'))
        if summary is None:
            summary = _default_summary(prof)
        prof['summary'] = summary
        result.append(prof)
    return result


@ext_portfolio_router.get('/{portfolio_id}')
def get_portfolio(portfolio_id: str, user_id: int = Depends(require_api_user)):
    """获取单个投资组合详情（含持仓明细+行业、每日汇总、每日盈亏序列）。"""
    prof = get_owned_portfolio(portfolio_id, user_id)
    prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    enrich_assets_with_industry(prof['assets'])
    summary = PortfolioDailySummaryService.get_last_by_portfolio_id(portfolio_id)
    if summary is None:
        summary = _default_summary(prof)
    prof['summary'] = summary
    prof['daily_pnl'] = DailyPnLRecordService.get_all_by_portfolio_id(portfolio_id)
    _strip(prof)
    return prof


@ext_portfolio_router.get('/{portfolio_id}/daily-summary')
def get_portfolio_daily_summary(portfolio_id: str, user_id: int = Depends(require_api_user)):
    """获取投资组合的每日统计序列。"""
    get_owned_portfolio(portfolio_id, user_id)
    return PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)


@ext_portfolio_router.get('/{portfolio_id}/transactions')
def get_portfolio_transactions(portfolio_id: str, user_id: int = Depends(require_api_user)):
    """获取投资组合的交易记录。"""
    get_owned_portfolio(portfolio_id, user_id)
    return PortfolioTransactionService.get_by_portfolio_id(portfolio_id)
