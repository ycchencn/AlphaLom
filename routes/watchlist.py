"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from flask import jsonify, Blueprint, request
from app import api_prefix, cache
from service.user_watchlist_service import UserWatchlistService
from service import StockService, FactorValueService
from service.stock_fear_greed_service import StockFearGreedService
from utils.data_loader import databull
from utils.logger import logger

# 创建蓝图
watchlist_bp = Blueprint('watchlist', __name__)


def make_response_json(data=None, msg="success", code=200):
    """
    统一返回格式辅助函数
    """
    return jsonify({
        'code': code,
        'msg': msg,
        'data': data
    })


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


@watchlist_bp.route(f'{api_prefix}/watchlist', methods=['GET'])
@cache.cached(timeout=3600, query_string=True)
def get_watchlist():
    """
    获取自选股列表
    Query Params:
        page_size (int): 每页数量 (可选)
    """
    try:
        items = UserWatchlistService.get_all(securities_type='stock')
        # 将对象转换为字典列表
        watchlist = [item.to_dict() for item in items] if items else []
        stock_list = []
        for item in watchlist:
            _stock = StockService.get_stock_by_symbol(item['stock_code'], fields=[
                'symbol',
                'name',
                'market',
                'concepts'
            ])
            if _stock is None:
                continue
            if _stock['market'] != 'cn':
                continue
            _stock['greed_data'], _stock['main_force_behavior_phase'] = get_main_force_behavior_phase(_stock['symbol'])
            _stock['52week_low'] = FactorValueService.get_latest_factor_value(ticker=_stock['symbol'], factor_name='52week_low')
            _stock['52week_high'] = FactorValueService.get_latest_factor_value(ticker=_stock['symbol'], factor_name='52week_high')
            _stock['last_tick'] = databull.get_last_tick(symbol=_stock['symbol'])
            stock_list.append(_stock)

        return jsonify(stock_list)
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        return make_response_json(msg=str(e), code=500)


@watchlist_bp.route(f'{api_prefix}/watchlist/<string:stock_code>', methods=['GET'])
def get_stock_detail(stock_code):
    """
    获取单只自选股详情
    Path Param:
        stock_code (str): 股票代码
    """
    try:
        item = UserWatchlistService.get_by_code(stock_code)
        if not item:
            return make_response_json(msg=f"Stock {stock_code} not found", code=404)

        return make_response_json(data=item.to_dict())
    except Exception as e:
        logger.error(f"Error fetching stock detail: {e}")
        return make_response_json(msg=str(e), code=500)


@watchlist_bp.route(f'{api_prefix}/watchlist', methods=['POST'])
def add_stock():
    """
    添加自选股
    Body (JSON):
        stock_code (str, required): 股票代码
        stock_name (str, required): 股票名称
        price (float, optional): 价格
        ...其他字段
    """
    json_data = request.get_json()

    # 基础校验
    if not json_data or not json_data.get('stock_code'):
        return make_response_json(msg="Missing required fields: stock_code, stock_name", code=400)
    try:
        success = UserWatchlistService.add({
            "stock_code": json_data.get('stock_code'),
            "stock_name": "",
            "securities_type": "stock",
            "topic": "",
            "desc": "",
            "price": 0,
            "diff": 0,
            "from_ai": 0
        })
        if success:
            # 清除列表缓存，保证数据一致性
            cache.delete(f'view/{api_prefix}/watchlist')
            return make_response_json(msg="Added successfully")
        else:
            return make_response_json(msg="Failed to add (may be duplicate)", code=400)
    except Exception as e:
        logger.error(f"Error adding stock: {e}")
        return make_response_json(msg=str(e), code=500)


@watchlist_bp.route(f'{api_prefix}/watchlist/<string:stock_code>', methods=['PUT'])
def update_stock(stock_code):
    """
    更新股票行情（价格和涨跌幅）
    Path Param:
        stock_code (str): 股票代码
    Body (JSON):
        price (float): 最新价格
        diff (float): 涨跌幅
    """
    json_data = request.get_json()

    if not json_data:
        return make_response_json(msg="Request body cannot be empty", code=400)

    price = json_data.get('price')
    diff = json_data.get('diff')

    try:
        # 调用 Service 更新方法
        success = UserWatchlistService.update_price_diff(stock_code, price, diff)
        if success:
            # 清除相关缓存
            cache.delete(f'view/{api_prefix}/watchlist')
            cache.delete(f'view/{api_prefix}/watchlist/{stock_code}')
            return make_response_json(msg="Updated successfully")
        else:
            return make_response_json(msg=f"Stock {stock_code} not found or update failed", code=404)
    except Exception as e:
        logger.error(f"Error updating stock: {e}")
        return make_response_json(msg=str(e), code=500)


@watchlist_bp.route(f'{api_prefix}/watchlist/<string:stock_code>', methods=['DELETE'])
def delete_stock(stock_code):
    """
    删除自选股
    Path Param:
        stock_code (str): 股票代码
    """
    try:
        success = UserWatchlistService.delete_by_code(stock_code)
        if success:
            # 清除相关缓存
            cache.delete(f'view/{api_prefix}/watchlist')
            cache.delete(f'view/{api_prefix}/watchlist/{stock_code}')
            return make_response_json(msg="Deleted successfully")
        else:
            return make_response_json(msg=f"Stock {stock_code} not found", code=404)
    except Exception as e:
        logger.error(f"Error deleting stock: {e}")
        return make_response_json(msg=str(e), code=500)
