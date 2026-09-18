"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 系统日志查询接口（FastAPI 实现）
"""

from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from service.app_log_service import AppLogService
from utils.logger import logger

syslog_router = APIRouter(prefix='/api/v1', tags=['系统日志'])

# ⚠️ 全部改为同步 `def`：这些接口只做同步 ORM 查询，Starlette 会把它们丢进 anyio
# 线程池（默认 40 线程）执行。写成 `async def` 则跑在唯一的事件循环线程上，
# 一次慢查询（`app_logs` 表数据量大、还要 count）就会让全站请求一起排队。


def make_response(data=None, msg="success", code=200):
    """统一返回格式"""
    return {'code': code, 'msg': msg, 'data': data}


@syslog_router.get('/app_logs')
def get_app_logs(
    level: str = Query(None, description="日志级别"),
    module: str = Query(None, description="模块名"),
    keyword: str = Query(None, description="关键词（搜索 message）"),
    start_time: str = Query(None, description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_time: str = Query(None, description="结束时间 YYYY-MM-DD HH:MM:SS"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=500, description="每页数量"),
):
    """分页查询系统日志"""
    try:
        start_dt = None
        end_dt = None
        if start_time:
            try:
                start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise HTTPException(status_code=400, detail="start_time 格式错误，应为 YYYY-MM-DD HH:MM:SS")
        if end_time:
            try:
                end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise HTTPException(status_code=400, detail="end_time 格式错误，应为 YYYY-MM-DD HH:MM:SS")

        result = AppLogService.query_logs(
            level=level,
            module=module,
            keyword=keyword,
            start_time=start_dt,
            end_time=end_dt,
            page=page,
            page_size=page_size
        )
        return make_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_app_logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@syslog_router.get('/app_logs/levels')
def get_log_levels():
    """获取所有日志级别（用于筛选下拉）"""
    try:
        levels = AppLogService.get_levels()
        return make_response(data=levels)
    except Exception as e:
        logger.error(f"Error in get_log_levels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@syslog_router.get('/app_logs/modules')
def get_log_modules():
    """获取所有模块名（用于筛选下拉）"""
    try:
        modules = AppLogService.get_modules()
        return make_response(data=modules)
    except Exception as e:
        logger.error(f"Error in get_log_modules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@syslog_router.get('/app_logs/statistics')
def get_log_statistics():
    """获取日志统计信息"""
    try:
        stats = AppLogService.get_statistics()
        return make_response(data=stats)
    except Exception as e:
        logger.error(f"Error in get_log_statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ⚠️ 带路径参数的路由必须放在所有静态子路径之后（声明顺序 = 匹配优先级）。
# FastAPI/Starlette 按声明顺序取第一个 FULL match，而 `/app_logs/{log_id}` 的形状
# 会吃掉 `/app_logs/levels`、`/app_logs/modules`、`/app_logs/statistics` ——
# 表现为这几个接口稳定返回 422（log_id 不是整数），而不是被打到正确的处理函数。
# Flask 时代 Werkzeug 会按具体度排序，所以这是迁移引入的回归，不是历史遗留。
# 以后新增 `/app_logs/xxx` 静态路径，请加在上面几个之前。
@syslog_router.get('/app_logs/{log_id}')
def get_app_log_detail(log_id: int):
    """获取单条日志详情"""
    try:
        log = AppLogService.get_by_id(log_id)
        if log is None:
            raise HTTPException(status_code=404, detail="日志不存在")
        return make_response(data=log)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_app_log_detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))
