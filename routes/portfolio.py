"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import uuid

import pandas as pd
from flask import jsonify, Blueprint, request
from app import api_prefix, cache
from utils.logger import logger
from service import InvestmentPortfolioService, PortfolioAssetsService
from service import (
    DailyPnLRecordService,
    PortfolioDailySummaryService,
    PortfolioTransactionService
)
from backtest.quant_stat_report import generate_html_report_string

portfolio_bp = Blueprint('portfolio', __name__)

# 允许客户端直接写入/更新的字段白名单（其余字段由系统维护，忽略防止越权覆盖）
PORTFOLIO_WRITABLE_FIELDS = {
    'name', 'strategy_type', 'total_position_pct', 'base_currency',
    'position_plan', 'position_plan_reason', 'init_cash', 'current_cash',
    'llm_prompt', 'llm_setting', 'desc', 'enable', 'market',
}

# 新建组合时的必填字段（name 唯一；init_cash/current_cash/total_position_pct 无默认值，非空约束）
PORTFOLIO_REQUIRED_FIELDS = {'name', 'init_cash', 'current_cash', 'total_position_pct'}


def make_response_json(data=None, msg="success", code=200):
    """统一返回格式"""
    return jsonify({'code': code, 'msg': msg, 'data': data})


def _pick_writable(data):
    """从请求体中过滤出仅允许写入的字段"""
    return {k: v for k, v in data.items() if k in PORTFOLIO_WRITABLE_FIELDS}


@portfolio_bp.route(f'{api_prefix}/investment_portfolios', methods=['GET'])
# @cache.cached(timeout=360, query_string=True)
def get_investment_portfolios():
    # 获取策略列表数据
    portfolios = InvestmentPortfolioService.get_all()
    for prof in portfolios:
        # 获取持仓最新统计信息
        prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(prof.get('portfolio_id'))
        if prof['summary'] is None:
            prof['summary'] = {
                'total_unrealized_pnl': 0,
                'total_assets': 0
            }
        # prof['summary_list'] = PortfolioDailySummaryService.get_all_by_portfolio_id(prof.get('portfolio_id'))
        # 获取持仓最新信息
        prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(prof.get('portfolio_id'))
        # 删除无用字段
        del prof['llm_prompt']
        del prof['position_plan']
    return jsonify(portfolios)


@portfolio_bp.route(f'{api_prefix}/investment_portfolios_info/<string:portfolio_id>', methods=['GET'])
# @cache.cached(timeout=360, query_string=True)
def get_investment_portfolios_info(portfolio_id):
    # 获取策略详情
    prof = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    prof['portfolio_id'] = portfolio_id
    prof['summary'] = PortfolioDailySummaryService.get_last_by_portfolio_id(portfolio_id)
    if prof['summary'] is None:
        prof['summary'] = {
            'total_unrealized_pnl': 0,
            'total_assets': 0
        }
    prof['assets'] = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    prof['daily_pnl'] = DailyPnLRecordService.get_all_by_portfolio_id(portfolio_id)
    return jsonify(prof)


@portfolio_bp.route(f'{api_prefix}/portfolio_daily_summary/<string:portfolio_id>', methods=['GET'])
# @cache.cached(timeout=360, query_string=True)
def get_portfolio_daily_summary(portfolio_id):
    # 获取策略每日统计数据
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)
    return jsonify(summary_list)

@portfolio_bp.route(f'{api_prefix}/portfolio_transaction/<string:portfolio_id>', methods=['GET'])
def get_portfolio_transaction(portfolio_id):
    # 获取策略交易记录
    _list = PortfolioTransactionService.get_by_portfolio_id(portfolio_id)
    return jsonify(_list)

@portfolio_bp.route(f'{api_prefix}/portfolio_quantstat/<string:portfolio_id>', methods=['GET'])
def gen_quantstat(portfolio_id):
    # 获取策略交易记录
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id)

    # 2. 转换为 DataFrame，只取日期和总资产
    df = pd.DataFrame(summary_list)
    df['date'] = pd.to_datetime(df['date'])  # 确保是 datetime 格式
    df = df.set_index('date').sort_index()  # 设为索引并按时间排序
    equity = df['total_assets']  # 净资产序列

    # 你的归一化净值序列 equity
    html_content, perf_data = generate_html_report_string(equity, title="量化策略绩效报告")

    InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, {
        "quantstat_json": perf_data
    })

    return html_content

@portfolio_bp.route(f'{api_prefix}/investment_portfolios', methods=['POST'])
def create_portfolio():
    """
    新建投资组合
    Body (JSON):
        name (str, required): 组合名称（唯一）
        init_cash (number, required): 初始资金
        current_cash (number, required): 当前现金
        total_position_pct (number, required): 总仓位百分比
        strategy_type (int, optional, default 1): 策略类型
        base_currency (str, optional, default 'USD'): 基准货币
        其他可选字段见 PORTFOLIO_WRITABLE_FIELDS
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return make_response_json(msg='Request must be JSON', code=400)

    # 必填字段校验（注意：0 是合法数值，不能误判为缺失；用 is-not-None 判断）
    missing = [f for f in PORTFOLIO_REQUIRED_FIELDS if data.get(f) is None]
    if missing:
        return make_response_json(msg=f'Missing required fields: {", ".join(missing)}', code=400)

    # 过滤白名单字段
    payload = _pick_writable(data)

    # portfolio_id 不在白名单内，统一由服务端生成 UUID（长度符合模型 36 位约束）
    payload['portfolio_id'] = str(uuid.uuid4())

    # 默认策略类型，避免数据库 not null 报错
    payload.setdefault('strategy_type', 1)

    try:
        success = InvestmentPortfolioService.add(payload)
        if success:
            return make_response_json(data={'portfolio_id': payload['portfolio_id']}, msg='Created successfully', code=200)
        return make_response_json(msg='Failed to create (name may already exist)', code=400)
    except Exception as e:
        logger.error(f"Error creating portfolio: {e}")
        return make_response_json(msg=str(e), code=500)


@portfolio_bp.route(f'{api_prefix}/investment_portfolios/<string:portfolio_id>', methods=['PUT'])
def update_portfolio(portfolio_id):
    """
    更新投资组合（字段级部分更新）
    Path Param:
        portfolio_id (str): 组合ID
    Body (JSON): 任意 PORTFOLIO_WRITABLE_FIELDS 中的字段
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return make_response_json(msg='Request must be JSON', code=400)

    payload = _pick_writable(data)
    if not payload:
        return make_response_json(msg='No valid updatable fields provided', code=400)

    if not InvestmentPortfolioService.get_by_portfolio_id(portfolio_id):
        return make_response_json(msg='Portfolio not found', code=404)

    try:
        success = InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, payload)
        if success:
            return make_response_json(msg='Updated successfully', code=200)
        return make_response_json(msg='Update failed', code=400)
    except Exception as e:
        logger.error(f"Error updating portfolio {portfolio_id}: {e}")
        return make_response_json(msg=str(e), code=500)


@portfolio_bp.route(f'{api_prefix}/investment_portfolios/<string:portfolio_id>', methods=['DELETE'])
def delete_portfolio(portfolio_id):
    """
    删除投资组合
    Path Param:
        portfolio_id (str): 组合ID
    """
    if not InvestmentPortfolioService.get_by_portfolio_id(portfolio_id):
        return make_response_json(msg='Portfolio not found', code=404)

    try:
        success = InvestmentPortfolioService.delete_by_portfolio_id(portfolio_id)
        if success:
            return make_response_json(msg='Deleted successfully', code=200)
        return make_response_json(msg='Delete failed', code=400)
    except Exception as e:
        logger.error(f"Error deleting portfolio {portfolio_id}: {e}")
        return make_response_json(msg=str(e), code=500)


@portfolio_bp.route(f'{api_prefix}/portfolio/<string:portfolio_id>', methods=['PUT'])
def update_portfolio_legacy(portfolio_id):
    """
    兼容旧路径的组合更新（与 /investment_portfolios/<id> 行为一致）
    """
    return update_portfolio(portfolio_id)
