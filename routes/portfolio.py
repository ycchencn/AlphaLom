"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
from flask import jsonify, Blueprint, request
from app import api_prefix, cache
from service import InvestmentPortfolioService, PortfolioAssetsService
from service import (
    DailyPnLRecordService,
    PortfolioDailySummaryService,
    PortfolioTransactionService
)
from backtest.quant_stat_report import generate_html_report_string

portfolio_bp = Blueprint('portfolio', __name__)


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
    # print(perf_data)
    return html_content

@portfolio_bp.route(f'{api_prefix}/portfolio/<string:portfolio_id>', methods=['PUT'])
def update_portfolio(portfolio_id):
    """
    更新组合信息
    """
    update_data = request.get_json(silent=True)

    # 1. 检查请求体是否为有效 JSON
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON'}), 400
    if update_data is None:
        return jsonify({'message': 'Invalid JSON'}), 400

    # 2. 校验 symbol（可选：格式校验，如长度、字符集）
    if not portfolio_id or not isinstance(portfolio_id, str):
        return jsonify({'message': 'Invalid symbol'}), 400

    # 获取个股信息
    portfolio = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)

    if not portfolio:
        return jsonify({'message': 'No stock found!'}), 404

    # 执行更新
    InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, update_data)

    return jsonify({'code': 0, 'message': 'Stock updated successfully!'})
