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
from llms import get_model_by_setting
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


def _default_summary(prof: dict) -> dict:
    """新建策略还没有每日汇总（PortfolioDailySummary）时，构造一个与真实汇总字段一致、
    且数值自洽的兜底 summary。

    旧兜底只给 ``{total_unrealized_pnl: 0, total_assets: 0}``，会漏掉 ``position_ratio``
    （前端仓位卡片 ``summary.position_ratio * 100`` → NaN%），且 ``total_assets=0`` 会让
    「持仓市值」卡片按 ``total_assets - current_cash`` 算出负数。

    这里用「当前现金 + 持仓市值」反推总资产与仓位比例，保证非负、非 NaN。
    """
    cash = float(prof.get('current_cash') or 0)
    position_value = 0.0
    for a in (prof.get('assets') or []):
        try:
            position_value += float(a.get('position_size') or 0) * float(a.get('position_price') or 0)
        except (TypeError, ValueError):
            pass
    total_assets = cash + position_value
    position_ratio = (position_value / total_assets) if total_assets > 0 else 0.0
    return {
        'total_assets': total_assets,
        'total_unrealized_pnl': 0,
        'total_pnl_pct': 0,
        'position_ratio': position_ratio,
        'cash_balance': cash,
        'daily_pnl_change': 0,
        'cumulative_realized_pnl': 0,
    }


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
        prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(prof.get('portfolio_id'))
        prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(prof.get('portfolio_id'))
        if prof['summary'] is None:
            prof['summary'] = _default_summary(prof)
        del prof['llm_prompt']
        del prof['position_plan']
    return portfolios


@portfolio_router.get('/investment_portfolios_info/{portfolio_id}')
@cache(expire=3600, namespace=PORTFOLIO_DETAIL_NS)
def get_investment_portfolios_info(portfolio_id: str, user_id: int = Depends(get_current_user_id)):
    """获取策略详情（仅限本人组合）"""
    prof = get_owned_portfolio(portfolio_id, user_id)
    prof['portfolio_id'] = portfolio_id
    prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(portfolio_id)
    if prof['summary'] is None:
        prof['summary'] = _default_summary(prof)
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


@portfolio_router.post('/investment_portfolios/generate_prompt')
def generate_portfolio_prompt(payload: dict, user_id: int = Depends(get_current_user_id)):
    """基于用户描述的策略风格/目标/约束，调用大模型生成一份带占位符的调仓提示词。

    生成的提示词供 job_position_plan_daily 使用（内部用 $holdings_text 等占位符做 Template 替换），
    因此必须保留这些 $ 占位符变量，并要求模型以 JSON 输出调仓计划。
    """
    name = (payload.get('name') or '').strip()
    desc = (payload.get('desc') or '').strip()
    market = (payload.get('market') or 'cn').strip()
    style = (payload.get('style') or '').strip()
    target = (payload.get('target') or '').strip()
    constraints = (payload.get('constraints') or '').strip()

    meta = (
        "你是一名量化投资系统的提示词工程师。为「AI 主观策略」的调仓 Agent 编写一段用户提示词（user prompt）。\n"
        "这段提示词会被系统用以下占位符变量替换后发给大模型，模型据此输出调仓计划 JSON：\n"
        "- $current_date：今天的日期（YYYYMMDD）\n"
        "- $holdings_text：当前持仓列表（代码、名称、持仓量、成本、最新价）\n"
        "- $stock_pool_text：候选股票池（可买入标的）\n"
        "- $available_money：可用资金（元）\n"
        "- $market_data_csv：大盘（上证指数）近 30 天行情 CSV\n"
        "- $recent_news：近期相关新闻（JSON 字符串）\n"
        "- $position_plan：上一次调仓计划（JSON），可能为空\n"
        "- $stock_position_limit：单一标的仓位上限（只数）\n"
        "要求：\n"
        "1. 用中文撰写；必须原样保留上述所有 $ 占位符变量（不要替换成具体数值）。\n"
        "2. 明确指示模型以 JSON 格式输出，结构为 "
        "{\"position_style\": \"一句话风格描述\", \"actions\": [{\"action\": \"buy|sell|hold\", "
        "\"stock_code\": \"代码\", \"stock_name\": \"名称\", \"quantity\": 整数手数, \"reason\": \"理由\"}]}。\n"
        "3. 结合用户给出的策略定位与约束设计调仓倾向（如风控、行业偏好、仓位节奏）。\n"
        "4. 不要输出任何解释，不要用 markdown 代码块围栏，只输出可直接作为提示词的正文。\n"
    )
    user_part = (
        f"策略名称：{name or '（未命名）'}\n"
        f"策略描述/定位：{desc or '（未提供）'}\n"
        f"目标市场：{market}\n"
        f"风格倾向：{style or '（未指定，请给出均衡建议）'}\n"
        f"策略目标：{target or '（未提供）'}\n"
        f"额外约束：{constraints or '（无）'}\n"
        "请生成对应的调仓提示词。"
    )

    try:
        llm_setting = payload.get('llm_setting')
        staff = get_model_by_setting(_setting=llm_setting) if llm_setting else get_model_by_setting()
        staff.set_response_text()
        result = staff.create_completion(messages=[
            {'role': 'system', 'content': meta},
            {'role': 'user', 'content': user_part},
        ])
        prompt = (result.choices[0].message.content or '').strip()
        # 兜底剥离可能的代码块围栏（模型有时不听话）
        if prompt.startswith('```'):
            prompt = '\n'.join(prompt.split('\n')[1:])
        if prompt.endswith('```'):
            prompt = prompt[:-3]
        prompt = prompt.strip()
    except Exception as e:
        logger.warning(f"生成提示词失败：{e}")
        raise HTTPException(status_code=500, detail=f'生成提示词失败：{e}')

    if not prompt:
        raise HTTPException(status_code=500, detail='生成结果为空，请重试')

    return make_response(data={'prompt': prompt})