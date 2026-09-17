"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify
from app import api_prefix
from service.app_log_service import AppLogService
from utils.logger import logger

syslog_bp = Blueprint('syslog', __name__)


def make_response_json(data=None, msg="success", code=200):
    """统一返回格式"""
    return jsonify({'code': code, 'msg': msg, 'data': data})


@syslog_bp.route(f'{api_prefix}/app_logs', methods=['GET'])
def get_app_logs():
    """
    分页查询系统日志
    Query params:
      - level: 日志级别
      - module: 模块名
      - keyword: 关键词（搜索 message）
      - start_time: 开始时间 (YYYY-MM-DD HH:MM:SS)
      - end_time: 结束时间 (YYYY-MM-DD HH:MM:SS)
      - page: 页码（默认 1）
      - page_size: 每页数量（默认 50）
    """
    try:
        level = request.args.get('level')
        module = request.args.get('module')
        keyword = request.args.get('keyword')
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))

        start_time = None
        end_time = None
        if start_time_str:
            try:
                start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return make_response_json(msg="start_time 格式错误，应为 YYYY-MM-DD HH:MM:SS", code=400)
        if end_time_str:
            try:
                end_time = datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return make_response_json(msg="end_time 格式错误，应为 YYYY-MM-DD HH:MM:SS", code=400)

        result = AppLogService.query_logs(
            level=level,
            module=module,
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size
        )
        return make_response_json(data=result)
    except Exception as e:
        logger.error(f"Error in get_app_logs: {e}")
        return make_response_json(msg=str(e), code=500)


@syslog_bp.route(f'{api_prefix}/app_logs/<int:log_id>', methods=['GET'])
def get_app_log_detail(log_id):
    """
    获取单条日志详情
    """
    try:
        log = AppLogService.get_by_id(log_id)
        if log is None:
            return make_response_json(msg="日志不存在", code=404)
        return make_response_json(data=log)
    except Exception as e:
        logger.error(f"Error in get_app_log_detail: {e}")
        return make_response_json(msg=str(e), code=500)


@syslog_bp.route(f'{api_prefix}/app_logs/levels', methods=['GET'])
def get_log_levels():
    """
    获取所有日志级别（用于筛选下拉）
    """
    try:
        levels = AppLogService.get_levels()
        return make_response_json(data=levels)
    except Exception as e:
        logger.error(f"Error in get_log_levels: {e}")
        return make_response_json(msg=str(e), code=500)


@syslog_bp.route(f'{api_prefix}/app_logs/modules', methods=['GET'])
def get_log_modules():
    """
    获取所有模块名（用于筛选下拉）
    """
    try:
        modules = AppLogService.get_modules()
        return make_response_json(data=modules)
    except Exception as e:
        logger.error(f"Error in get_log_modules: {e}")
        return make_response_json(msg=str(e), code=500)


@syslog_bp.route(f'{api_prefix}/app_logs/statistics', methods=['GET'])
def get_log_statistics():
    """
    获取日志统计信息
    """
    try:
        stats = AppLogService.get_statistics()
        return make_response_json(data=stats)
    except Exception as e:
        logger.error(f"Error in get_log_statistics: {e}")
        return make_response_json(msg=str(e), code=500)
