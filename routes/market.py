"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import datetime
from flask import jsonify, Blueprint, request
from app import api_prefix, cache, json_resp, trading_cache_key
from service import MarketNewsService
from utils.logger import logger
from utils.data_loader import databull

market_bp = Blueprint('market', __name__)


@market_bp.route(f'{api_prefix}/market/sectors', methods=['GET'])
@cache.cached(timeout=3600, query_string=True, make_cache_key=trading_cache_key)
def get_market_sectors():
    """
    获取沪深板块涨跌幅数据
    :return:
    """
    sector_type = request.args.get('sector_type', default='sw1', type=str)
    market_sector = databull.get_market_sector(sector_type=sector_type)
    return json_resp(market_sector)


@market_bp.route(f'{api_prefix}/market/news', methods=['GET'])
@cache.cached(timeout=3600, query_string=True)
def get_news():
    page = request.args.get('page', default=1, type=int)
    page_size = request.args.get('page_size', default=20, type=int)
    news = MarketNewsService.get_by_time_range(limit=page_size)
    return jsonify(news)


@market_bp.route(f'{api_prefix}/market/search_news', methods=['GET'])
def search_news():
    try:
        # 获取查询参数
        keyword = request.args.get('keyword', type=str, default='')
        stock_code = request.args.get('stock_code', type=str)
        start_time_str = request.args.get('start_time', type=str)
        end_time_str = request.args.get('end_time', type=str)
        page = request.args.get('page', default=1, type=int)
        page_size = request.args.get('page_size', default=20, type=int)

        # 解析时间（ISO 格式）
        start_time = None
        end_time = None
        if start_time_str:
            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        if end_time_str:
            end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        # 调用服务层搜索
        # es_res = search_digest_keyword(keyword, top_k=page_size, sort_field="news_time.keyword", sort_order="desc")
        # result = {
        #     "items": es_res['hits'],
        #     "total": es_res['total'],
        #     "page": page,
        #     "page_size": page_size,
        #     "has_more": False
        # }

        result = MarketNewsService.search(
            keyword=keyword,
            stock_code=stock_code,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size
        )

        return jsonify(result), 200

    except Exception as e:

        logger.error(f"Unexpected error in search_news endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


def make_response_json(data=None, msg="success", code=200):
    """
    统一返回格式辅助函数
    """
    return jsonify({
        'code': code,
        'msg': msg,
        'data': data
    })
