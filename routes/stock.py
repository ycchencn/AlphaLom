"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from flask import request, jsonify, Blueprint
from app import api_prefix, cache, trading_cache_key
from service import StockService, FactorValueService
from service import JobService, ResearchReportService
from service.stock_financial_score import StockFinancialScoreService
from service.stock_fear_greed_service import StockFearGreedService
from utils.data_loader import databull
from utils.common import get_today, get_date_by_n, validate_stock_code

stock_bp = Blueprint('stock', __name__)


def get_main_force_behavior_phase(code):
    greed_data = StockFearGreedService.get_latest_by_index(index_code=code)
    if greed_data is None:
        greed_data = {
            "fear_greed": 0
        }
    # 获取 main_force_behavior_phase
    main_force_behavior_phase = FactorValueService.get_latest_factor_value(
        ticker=code,
        factor_name='main_force_behavior_phase'
    )
    return greed_data, main_force_behavior_phase


@stock_bp.route(f'{api_prefix}/stock/dcf_research_report/<string:stock_code>', methods=['GET'])
def get_dcf_research_report(stock_code):
    """
    获取个股研报数据
    """
    report = ResearchReportService.get_by_code(stock_code=stock_code, report_type=1)
    return jsonify(report)


@stock_bp.route(f'{api_prefix}/stock/tech_analysis_report/<string:stock_code>', methods=['GET'])
def get_tech_analysis_report(stock_code):
    """
    获取个股研报数据
    """
    report = ResearchReportService.get_by_code(stock_code=stock_code, report_type=2)
    return jsonify(report)


@stock_bp.route(f'{api_prefix}/stocks/<string:symbol>', methods=['PUT'])
def update_stock(symbol):
    """
    更新股票信息
    """

    data = request.get_json(silent=True)

    if not validate_stock_code(symbol):
        return jsonify({'message': 'Invalid symbol'}), 500

    # 1. 检查请求体是否为有效 JSON
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON'}), 400

    if data is None:
        return jsonify({'message': 'Invalid JSON'}), 400

    # 2. 校验 symbol（可选：格式校验，如长度、字符集）
    if not symbol or not isinstance(symbol, str):
        return jsonify({'message': 'Invalid symbol'}), 400

    if not StockService.exists(symbol):
        # 个股不在数据库，查询api获取
        stock_api = databull.get_stock_info(symbol, market=data.get('market', 'cn'))
        # 自动添加
        StockService.upsert_stock({
            'symbol': symbol,
            'ts_code': stock_api.get('ts_code'),
            'name': stock_api.get('name'),
            'market': data.get('market', 'cn'),
            'securities_type': 'stock',
            'monitoring': 1
        })
    else:
        # 获取个股信息
        # stock = StockService.get_stock_by_symbol(symbol)
        data['symbol'] = symbol
        StockService.upsert_stock({
            'symbol': symbol,
            'market': data.get('market', 'cn'),
            'monitoring': data.get('monitoring', 1)
        })

    # 提交个股分析任务
    if request.args.get('is_update_history', type=int, default=1):
        _stock_reanalysis(symbol, sync_history=False, send_notification=True)

    return jsonify({'code': 0, 'message': 'Stock updated successfully!'})


@stock_bp.route(f'{api_prefix}/stocks_monitored', methods=['GET'])
@cache.cached(timeout=3600, query_string=True, make_cache_key=trading_cache_key)
def get_stocks_monitored():
    """
    获取个股监控列表
    """
    page = request.args.get('page', default=1, type=int)
    market = request.args.get('market', default='cn', type=str)
    page_size = request.args.get('page_size', default=300, type=int)
    simple = request.args.get('simple', default=0, type=int)
    stocks = StockService.get_monitoring_stock_pool(per_page=page_size, market=market)

    for stock in stocks:
        # 获取恐惧贪婪数据
        if simple == 1:
            continue
        stock['greed_data'], stock['main_force_behavior_phase'] = get_main_force_behavior_phase(stock['symbol'])
        stock['52week_low'] = FactorValueService.get_latest_factor_value(
            ticker=stock['symbol'],
            factor_name='52week_low'
        )
        stock['52week_high'] = FactorValueService.get_latest_factor_value(
            ticker=stock['symbol'],
            factor_name='52week_high'
        )

    return jsonify(stocks)


@stock_bp.route(f'{api_prefix}/stock/greed_data/<string:stock_code>', methods=['GET'])
@cache.cached(timeout=3600, query_string=True, make_cache_key=trading_cache_key)
def get_stocks_greed_data(stock_code):
    """
    获取个股恐惧贪婪数据
    """
    greed_data = StockFearGreedService.get_by_index_all(index_code=stock_code)
    return jsonify(greed_data)


@stock_bp.route(f'{api_prefix}/stocks/<string:stock_code>', methods=['GET'])
def get_stock(stock_code):
    """
    获取个股信息
    :param stock_code:
    :return:
    """
    if not validate_stock_code(stock_code):
        return jsonify({'code': -1, 'message': 'invalid stock code!'}), 500

    stock = StockService.get_stock_by_symbol(stock_code)
    # stock = datajiji.get_stock_info(stock_code)
    stock['tech_indicator'] = {
        '52week_low': FactorValueService.get_latest_factor_value(ticker=stock_code, factor_name='52week_low'),
        '52week_high': FactorValueService.get_latest_factor_value(ticker=stock_code, factor_name='52week_high'),
    }
    return jsonify(stock)


@stock_bp.route('/api/v1/stock_history/<string:stock_code>', methods=['GET'])
@cache.cached(timeout=3600, query_string=True, make_cache_key=trading_cache_key)
def get_stock_history(stock_code):
    """
    获取个股历史行情
    :param symbol:
    :return:
    """
    if not validate_stock_code(stock_code):
        return jsonify({'code': -1, 'message': 'invalid stock code!'}), 500

    # 获取查询参数，默认一年数据
    dayn = 365 * 1
    period = request.args.get('period', default='d')
    start_date = request.args.get('start_date', default=get_date_by_n(-1 * dayn))
    end_date = request.args.get('end_date', default=get_today())

    securities_data = databull.get_history(stock_code, start_date, end_date, period)
    securities_data.reset_index(inplace=True)
    securities_data['date'] = securities_data['date'].dt.strftime('%Y-%m-%d')

    # 将DataFrame转换为字典列表
    securities_data_dict = securities_data.to_dict(orient='records')

    return jsonify(securities_data_dict)


@stock_bp.route(f'{api_prefix}/stock/re_analysis/<string:symbol>', methods=['PUT'])
def stock_re_analysis(symbol):
    _stock_reanalysis(symbol)
    return jsonify({'code': 0, 'message': 'Stock updated successfully!'})


@stock_bp.route(f'{api_prefix}/stock/re_analysis_dcf/<string:symbol>', methods=['PUT'])
def stock_re_analysis_dcf(symbol):
    """
    重新分析个股DCF
    :param symbol:
    :return:
    """
    if not validate_stock_code(symbol):
        return jsonify({'code': -1, 'message': 'invalid stock code!'}), 500

    if StockService.get_stock_by_symbol(symbol) is None:
        return jsonify({'code': -1, 'message': 'Stock not found!'}), 404

    # 提交任务
    JobService.send_job({
        'job_func': 'job_stock_dcf_model_analysis',
        'job_args': {
            '_stock_code': symbol,
            'send_notification': False
        }
    })

    return jsonify({'code': 0, 'message': 'Stock updated successfully!'})


@stock_bp.route(f'{api_prefix}/stocks/profile/<string:symbol>', methods=['GET'])
@cache.cached(timeout=3600, query_string=True, make_cache_key=trading_cache_key)
def get_stock_profile(symbol):
    """
    获取公司信息
    :param symbol:
    :return:
    """
    if not validate_stock_code(symbol):
        return jsonify({}), 500
    stock_info = StockService.get_stock_by_symbol(symbol)
    stock_info_api = databull.get_stock_info(symbol, market=stock_info.get('market'))
    profile = stock_info_api.get('profile', {})
    beta = FactorValueService.get_latest_factor_value(ticker=symbol, factor_name='beta')
    profile['beta'] = beta
    return jsonify(profile)


def _stock_reanalysis(symbol, sync_history=False, send_notification=False):
    stock = StockService.get_stock_by_symbol(symbol)
    if stock is None:
        return
    # 重新计算恐惧贪婪指标
    JobService.send_job({
        'job_func': 'job_stock_analysis',
        'job_args': {
            'stock_code': symbol
        }
    })

@stock_bp.route(f'{api_prefix}/stocks/fundamental_scores/<string:symbol>', methods=['GET'])
def get_fundamental_scores(symbol):
    """
    获取个股基本面评分数据
    """
    fundamental_scores = StockFinancialScoreService.get_by_code(symbol)
    return jsonify(fundamental_scores)