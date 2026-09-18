"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from fastapi import APIRouter
from app.fastapi_app import api_prefix, cache
from utils.data_loader import databull

index_router = APIRouter(prefix=api_prefix, tags=['指数'])


@index_router.get('/index/last_tick')
async def get_index_last():
    """
    获取指数最新行情
    """
    index_codes = ['000001', '399001', '399006', '000688', '000692']
    index_ticks = []
    for code in index_codes:
        res = databull.get_last_tick(code, tick_type='index', market='cn')
        res['index_code'] = code
        index_ticks.append(res)
    return index_ticks