"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

公司公告（投资组合 → 公司公告 页面）的查询与同步入口。

数据形态：**本地副本**（`stock_announcements`），由定时任务从巨潮资讯网经 DataBull
增量拉取，页面只查本地 SQL。理由见 `service/stock_announcement_service.py` 顶部说明
（上游按单只股票分页 + 日配额，列表页实时查会几十次请求、十几秒等待）。

## 「股票池」口径

页面范围 = **当前用户的股票池**（`user_stock_pool`），而不是全站监控池：
公告表按 symbol 全局存一份（同一只票被多个用户关注时只抓一次），查询时用当前用户的
代码列表过滤 —— 这样既不多烧配额，也不会把别人的票展示出来。

⚠️ 过滤走「先取代码列表再 IN」，**不 JOIN user_stock_pool**：库内各表 symbol 的
排序规则不统一（utf8mb4_unicode_ci / 0900_ai_ci 混用），JOIN 会撞
1267 Illegal mix of collations（股票池页踩过同一个坑）。

## 空与失败的区分

上游覆盖不完整（600519 / 600036 等恒为空），所以：
  - `items` 为空但 `coverage.with_data > 0` → 只是当前筛选条件下没有结果；
  - `coverage.without_data` 是「池里但从没抓到过公告」的票数，前端据此提示
    「上游未覆盖该标的」，而不是让用户以为接口挂了。
"""

import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.fastapi_app import api_prefix
from service import JobService, StockService
from service.stock_announcement_service import (
    ANNOUNCEMENT_CATEGORIES,
    StockAnnouncementService,
)
from utils.auth import get_current_user, get_current_user_id
from utils.logger import logger
from utils.redis_obj import redis_obj

# 全站登录制：整个 router 加登录鉴权（与 routes/stock.py 一致）。
stock_announcement_router = APIRouter(prefix=api_prefix, tags=['公司公告'],
                                      dependencies=[Depends(get_current_user)])

# 手动「立即同步」的冷却时间（秒）：同步是批量外部请求，重复点击没有意义，
# 也会把配额浪费在同一批数据上。用 Redis NX 做全站级节流（不是用户级）。
SYNC_COOLDOWN_SEC = 300
SYNC_LOCK_KEY = 'stock_announcement:sync:lock'


def _parse_date(value: Optional[str], field: str):
    """'YYYY-MM-DD' → date；空值返回 None；格式错误给 400（不要静默忽略）。
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f'{field} 必须是 YYYY-MM-DD 格式')


@stock_announcement_router.get('/announcements')
def list_announcements(
    page: int = Query(1, ge=1, le=5000, description='页码，从 1 开始'),
    page_size: int = Query(20, ge=1, le=200, description='每页条数'),
    symbol: Optional[str] = Query(None, description='只看某只股票（必须在自己的股票池内）'),
    category: Optional[str] = Query(None, description='分类筛选，取值见返回的 categories'),
    keyword: Optional[str] = Query(None, description='标题/公司名关键词'),
    days: int = Query(0, ge=0, le=3650,
                      description='最近 N 天；0=不限。与 date_from/date_to 同时给出时以后者为准'),
    date_from: Optional[str] = Query(None, description='起始日期 YYYY-MM-DD'),
    date_to: Optional[str] = Query(None, description='截止日期 YYYY-MM-DD'),
    user_id: int = Depends(get_current_user_id),
):
    """当前用户股票池内的公司公告清单（含分类统计与覆盖情况）。

    ⚠️ 刻意**不加 `@cache`**：手动同步后需要立刻看到新数据，缓存会让「点了同步没变化」
    变成默认体验；而本接口只查本地小表（池内几十只票、每只数百条），单次耗时在毫秒级。
    """
    pool = StockService.get_user_pool_symbols(user_id)
    if not pool:
        return {
            'items': [], 'total': 0, 'page': page, 'page_size': page_size,
            'pool_total': 0, 'categories': list(ANNOUNCEMENT_CATEGORIES),
            'category_counts': {c: 0 for c in ANNOUNCEMENT_CATEGORIES},
            'coverage': {'pool_total': 0, 'non_a_share': 0, 'a_share_total': 0,
                         'with_data': 0, 'without_data': 0},
            'data_as_of': None,
            'sync': {'synced': 0, 'never_synced': 0, 'failed': 0,
                     'last_sync_time': None, 'errors': []},
            'empty_reason': 'pool_empty',
        }

    # 日期条件：显式区间优先；否则用 days 折算出起始日
    start = _parse_date(date_from, 'date_from')
    end = _parse_date(date_to, 'date_to')
    if start is None and days and days > 0:
        start = datetime.now().date() - timedelta(days=int(days))

    items, total = StockAnnouncementService.query(
        pool,
        category=(category or '').strip() or None,
        keyword=(keyword or '').strip() or None,
        symbol=(symbol or '').strip() or None,
        date_from=start,
        date_to=end,
        page=page,
        page_size=page_size,
    )

    # 名称兜底：公告表里存了上游返回的名称快照，但历史行可能缺失（或上游未返回），
    # 用 stocks 表补一次 —— 只查本页涉及的代码，一次 IN 查询。
    missing = {row['symbol'] for row in items if not row.get('stock_name')}
    if missing:
        brief = StockService.get_stocks_brief(missing)
        for row in items:
            if not row.get('stock_name'):
                row['stock_name'] = (brief.get(row['symbol']) or {}).get('name') or ''

    # 统计（分类计数忽略 category 筛选，这样点击某个标签后其它标签的数字仍然可用）
    category_counts = StockAnnouncementService.category_counts(
        pool,
        keyword=(keyword or '').strip() or None,
        symbol=(symbol or '').strip() or None,
        date_from=start,
        date_to=end,
    )
    coverage = StockAnnouncementService.coverage(pool)
    states = StockAnnouncementService.get_sync_states(pool)

    synced_times = [s.get('last_sync_time') for s in states.values() if s.get('last_sync_time')]
    errors = [
        {'symbol': sym, 'error': s.get('last_error') or '同步失败'}
        for sym, s in states.items() if s.get('last_sync_status') == 'error'
    ]

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'pool_total': coverage['pool_total'],
        'categories': list(ANNOUNCEMENT_CATEGORIES),
        'category_counts': category_counts,
        'coverage': coverage,
        'data_as_of': (StockAnnouncementService.latest_date(pool) or None),
        'sync': {
            'synced': len(synced_times),
            'never_synced': max(0, coverage['pool_total'] - len(states)),
            'failed': len(errors),
            'last_sync_time': max(synced_times) if synced_times else None,
            # 只回前 5 条失败原因：足够定位问题，也不会把整个响应撑大
            'errors': sorted(errors, key=lambda x: x['symbol'])[:5],
        },
        # empty_reason 是前端「空态文案」的分支依据，三种情况必须分开：
        #   pool_empty  —— 股票池是空的，让用户先去加票；
        #   no_a_share  —— 池里只有港股/美股，上游本来就不覆盖，同步也没用；
        #   never_synced —— 有 A 股但一条都没抓到过，提示手动/等待同步；
        #   no_match    —— 有数据，只是当前筛选条件下没有结果。
        'empty_reason': (
            'no_match' if total else
            ('no_a_share' if coverage['a_share_total'] == 0 else
             ('never_synced' if not coverage['with_data'] else 'no_match'))
        ),
    }


@stock_announcement_router.post('/announcements/sync')
def trigger_announcement_sync(
    symbol: Optional[str] = Body(None, embed=True),
    user_id: int = Depends(get_current_user_id),
):
    """手动触发公告同步（投递后台任务，异步执行）。

    - 带 `symbol`：只同步该只票（单只约 1~2 秒，走队列）；
    - 不带 `symbol`：同步整个监控池（几百只，3~5 分钟，走队列）。

    ⚠️ 全站 5 分钟冷却：同步是批量外部请求，重复点击没有意义，还会白烧上游配额。
       冷却期内返回 `queued=false` + 提示语，前端按「已在同步中」展示即可。
    """
    if symbol:
        code = str(symbol).strip()
        # 只允许同步自己池内的票：公告虽公开，但接口口径是「我的股票池」，
        # 允许任意代码会让这个入口变成"给别人的票烧配额"。
        if code not in set(StockService.get_user_pool_symbols(user_id)):
            raise HTTPException(status_code=404, detail='该股票不在你的股票池中')
        JobService.send_job({
            'job_func': 'job_stock_announcement_sync_symbol',
            'job_args': {'_stock_code': code},
        })
        return {'code': 0, 'queued': True, 'scope': 'symbol', 'symbol': code,
                'message': f'已提交 {code} 的公告同步任务，稍后刷新查看'}

    if not redis_obj.set(SYNC_LOCK_KEY, str(int(time.time())), nx=True, ex=SYNC_COOLDOWN_SEC):
        return {'code': 0, 'queued': False, 'scope': 'all',
                'message': '刚刚已提交过同步任务，请稍等片刻再试（全站 5 分钟一次）'}

    try:
        JobService.send_job({
            'job_func': 'job_stock_announcement_sync_daily',
            'job_args': {},
        })
    except Exception as e:  # noqa: BLE001
        # 投递失败要放掉锁，否则 5 分钟内用户再点也没反应（看起来像按钮坏了）
        try:
            redis_obj.delete(SYNC_LOCK_KEY)
        except Exception:  # noqa: BLE001
            pass
        logger.error(f'[announcement] 投递全池同步任务失败：{e}')
        raise HTTPException(status_code=500, detail='提交同步任务失败，请稍后重试')

    return {'code': 0, 'queued': True, 'scope': 'all',
            'message': '已提交股票池公告同步任务，几分钟后刷新查看'}
