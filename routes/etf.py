"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from flask import jsonify, Blueprint
from app import api_prefix, cache
from utils.data_loader import databull
from service import FactorValueService
from config import cache_setting

etf_bp = Blueprint('etf', __name__)


@etf_bp.route(f'{api_prefix}/etfs', methods=['GET'])
@cache.cached(timeout=cache_setting.get('stock_history'), query_string=True)
def get_etfs():
    """
    获取ETF监控列表
    """
    # 将对象转换为字典列表
    etfs = [
        {"name": "中证100ETF易方达", "symbol": "159901"},
        {"name": "沪深300ETF", "symbol": "159919"},
        {"name": "家电ETF国泰", "symbol": "159996"},
        {"name": "芯片ETF华夏", "symbol": "159995"},
        {"name": "通信ETF银华", "symbol": "159994"},
        {"name": "证券ETF鹏华", "symbol": "159993"},
        {"name": "创新药ETF银华", "symbol": "159992"},
        {"name": "创业板大盘ETF招商", "symbol": "159991"}
    ]
    # etfs = datagigi.get_etf_list(market='cn')[:8]
    for etf in etfs:
        etf['52week_low'] = FactorValueService.get_latest_factor_value(
            ticker=etf['symbol'],
            factor_name='52week_low'
        )
        etf['52week_high'] = FactorValueService.get_latest_factor_value(
            ticker=etf['symbol'],
            factor_name='52week_high'
        )
        # etf['composition'] = databull.get_etf_composition(symbol=etf['symbol'])
        # etf['composition'] = etf['composition']['data']
        etf['ohlc_last'] = databull.get_last_tick(symbol=etf['symbol'], tick_type='etf')
        etf['ohlc_last']['chg_pct'] = (etf['ohlc_last']['lastPrice'] - etf['ohlc_last']['lastClose']) / etf['ohlc_last']['lastClose'] * 100

    return jsonify(etfs)