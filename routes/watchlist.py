"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from app.fastapi_app import api_prefix
from service.user_watchlist_service import UserWatchlistService
from service import StockService, FactorValueService
from service.stock_fear_greed_service import StockFearGreedService
from utils.data_loader import databull
from utils.logger import logger

watchlist_router = APIRouter(prefix=api_prefix, tags=['自选股'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）；`async def` 则跑在
# 唯一的事件循环线程上，而下面这些 Service / databull 调用都是同步阻塞的，会把 loop 占死
# → 「一个接口慢，全部接口卡」。只有需要 `await request.json()` 的写接口才保留 async。


def make_response(data=None, msg="success", code=200):
    return {'code': code, 'msg': msg, 'data': data}


def get_main_force_behavior_phase(code):
    greed_data = StockFearGreedService.get_latest_by_index(index_code=code)
    if greed_data is None:
        greed_data = {"fear_greed": 0}
    main_force_behavior_phase = FactorValueService.get_latest_factor_value(
        ticker=code,
        factor_name='main_force_behavior_phase'
    )
    return greed_data, main_force_behavior_phase


@watchlist_router.get('/watchlist')
def get_watchlist():
    """
    获取自选股列表
    """
    try:
        items = UserWatchlistService.get_all(securities_type='stock')
        watchlist = [item.to_dict() for item in items] if items else []
        stock_list = []
        for item in watchlist:
            _stock = StockService.get_stock_by_symbol(item['stock_code'], fields=[
                'symbol', 'name', 'market', 'concepts'
            ])
            if _stock is None or _stock['market'] != 'cn':
                continue
            _stock['greed_data'], _stock['main_force_behavior_phase'] = get_main_force_behavior_phase(_stock['symbol'])
            _stock['52week_low'] = FactorValueService.get_latest_factor_value(ticker=_stock['symbol'], factor_name='52week_low')
            _stock['52week_high'] = FactorValueService.get_latest_factor_value(ticker=_stock['symbol'], factor_name='52week_high')
            _stock['last_tick'] = databull.get_last_tick(symbol=_stock['symbol'])
            stock_list.append(_stock)
        return stock_list
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@watchlist_router.get('/watchlist/{stock_code}')
def get_stock_detail(stock_code: str):
    """
    获取单只自选股详情
    """
    try:
        item = UserWatchlistService.get_by_code(stock_code)
        if not item:
            raise HTTPException(status_code=404, detail=f"Stock {stock_code} not found")
        return make_response(data=item.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stock detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@watchlist_router.post('/watchlist')
async def add_stock(request: Request):
    """
    添加自选股
    """
    try:
        json_data = await request.json()
    except Exception:
        json_data = {}

    if not json_data or not json_data.get('stock_code'):
        return make_response(msg="Missing required fields: stock_code", code=400)

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
            return make_response(msg="Added successfully")
        else:
            return make_response(msg="Failed to add (may be duplicate)", code=400)
    except Exception as e:
        logger.error(f"Error adding stock: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@watchlist_router.put('/watchlist/{stock_code}')
async def update_stock(stock_code: str, request: Request):
    """
    更新股票行情（价格和涨跌幅）
    """
    try:
        json_data = await request.json()
    except Exception:
        json_data = {}

    if not json_data:
        return make_response(msg="Request body cannot be empty", code=400)

    price = json_data.get('price')
    diff = json_data.get('diff')

    try:
        success = UserWatchlistService.update_price_diff(stock_code, price, diff)
        if success:
            return make_response(msg="Updated successfully")
        else:
            return make_response(msg=f"Stock {stock_code} not found", code=404)
    except Exception as e:
        logger.error(f"Error updating stock: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@watchlist_router.delete('/watchlist/{stock_code}')
def delete_stock(stock_code: str):
    """
    删除自选股
    """
    try:
        success = UserWatchlistService.delete_by_code(stock_code)
        if success:
            return make_response(msg="Deleted successfully")
        else:
            return make_response(msg=f"Stock {stock_code} not found", code=404)
    except Exception as e:
        logger.error(f"Error deleting stock: {e}")
        raise HTTPException(status_code=500, detail=str(e))