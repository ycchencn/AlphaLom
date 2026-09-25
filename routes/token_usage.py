"""
 * @author Yc
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * Token 使用量统计接口：汇总 + 明细。
 * 管理员可见全局；普通用户仅可见本人记录。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Depends

from utils.auth import get_current_user
from models.database import db_session
from models import LlmTokenUsage

token_usage_router = APIRouter(prefix='/api/v1', tags=['Token 统计'])


def make_response(data=None, msg="success", code=200):
    return {'code': code, 'msg': msg, 'data': data}


def _scope(user):
    """查询基：管理员全局，普通用户限本人。"""
    q = db_session.query(LlmTokenUsage)
    if user.get('role') != 'admin':
        q = q.filter(LlmTokenUsage.user_id == int(user['id']))
    return q


def _apply_filters(q, model, scene, start_date, end_date):
    # 仅接受字符串参数。FastAPI 依赖注入会把缺省参数解析成 None/str，
    # 但脱离 DI 直调时可能拿到 Query 对象，做 isinstance 守卫既能让函数可被
    # 独立测试，也避免对生产环境造成任何副作用。
    if isinstance(model, str) and model:
        q = q.filter(LlmTokenUsage.model == model)
    if isinstance(scene, str) and scene:
        q = q.filter(LlmTokenUsage.scene == scene)
    if isinstance(start_date, str) and start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            q = q.filter(LlmTokenUsage.created_at >= start_dt)
        except ValueError:
            pass
    if isinstance(end_date, str) and end_date:
        # 包含 end_date 当天（取到次日 0 点）
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(LlmTokenUsage.created_at < end_dt)
        except ValueError:
            pass
    return q


@token_usage_router.get('/token_usage/summary')
def token_usage_summary(
    user: dict = Depends(get_current_user),
    model: str = Query(default=None, description='按模型筛选'),
    scene: str = Query(default=None, description='按场景筛选'),
    start_date: str = Query(default=None, description='起始日期 YYYY-MM-DD'),
    end_date: str = Query(default=None, description='结束日期 YYYY-MM-DD'),
):
    q = _apply_filters(_scope(user), model, scene, start_date, end_date)
    rows = q.all()
    total_calls = len(rows)
    total_prompt = sum(r.prompt_tokens or 0 for r in rows)
    total_completion = sum(r.completion_tokens or 0 for r in rows)
    total_tokens = sum(r.total_tokens or 0 for r in rows)

    by_model = {}
    by_scene = {}
    daily = {}
    for r in rows:
        by_model.setdefault(r.model, {
            'model': r.model, 'calls': 0,
            'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
        })
        by_model[r.model]['calls'] += 1
        by_model[r.model]['total_tokens'] += r.total_tokens or 0
        by_model[r.model]['prompt_tokens'] += r.prompt_tokens or 0
        by_model[r.model]['completion_tokens'] += r.completion_tokens or 0

        key = r.scene or '(未分类)'
        by_scene.setdefault(key, {'scene': key, 'calls': 0, 'total_tokens': 0})
        by_scene[key]['calls'] += 1
        by_scene[key]['total_tokens'] += r.total_tokens or 0

        d = r.created_at.strftime('%Y-%m-%d') if r.created_at else 'unknown'
        daily.setdefault(d, {'date': d, 'calls': 0, 'total_tokens': 0,
                             'prompt_tokens': 0, 'completion_tokens': 0})
        daily[d]['calls'] += 1
        daily[d]['total_tokens'] += r.total_tokens or 0
        daily[d]['prompt_tokens'] += r.prompt_tokens or 0
        daily[d]['completion_tokens'] += r.completion_tokens or 0

    return make_response(data={
        'total_calls': total_calls,
        'total_prompt_tokens': total_prompt,
        'total_completion_tokens': total_completion,
        'total_tokens': total_tokens,
        'by_model': sorted(by_model.values(), key=lambda x: -x['total_tokens']),
        'by_scene': sorted(by_scene.values(), key=lambda x: -x['total_tokens']),
        'daily': sorted(daily.values(), key=lambda x: x['date']),
    })


@token_usage_router.get('/token_usage/records')
def token_usage_records(
    user: dict = Depends(get_current_user),
    model: str = Query(default=None),
    scene: str = Query(default=None),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    q = _apply_filters(_scope(user), model, scene, start_date, end_date)
    total = q.count()
    rows = (q.order_by(LlmTokenUsage.created_at.desc())
              .offset((page - 1) * page_size)
              .limit(page_size)
              .all())
    return make_response(data={
        'total': total,
        'page': page,
        'page_size': page_size,
        'records': [r.to_dict() for r in rows],
    })
