"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
from fastapi import APIRouter
from utils.redis_obj import redis_obj
from app.fastapi_app import json_resp
from job.dump_stocks_dcf import export_dcf_to_excel

quant_router = APIRouter(prefix='/api/v1', tags=['量化'])

# ⚠️ 同步 `def` 路由由 Starlette 自动丢进 anyio 线程池（默认 40 线程）。这个接口尤其需要：
# 缓存未命中时会同步执行 `export_dcf_to_excel()` 生成 Excel、再同步读 Redis，
# 写成 `async def` 会把事件循环占住很久 → 全站一起卡。


@quant_router.get('/quant/stock/get_dcf_report_snap')
def get_dcf_report_snap():
    """
    获取个股研报数据
    """
    report = redis_obj.get('dcf_valuation_report')
    if report is None:
        export_dcf_to_excel('./dcf_valuation_report.xlsx', sort_by='中性空间', ascending=False)
        return json_resp({})
    report = json.loads(report)
    return json_resp(report)