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

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

import anyio.to_thread
import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.fastapi_app import api_prefix
from service import JobService, StockService
from service import announcement_ai_service as ai_svc
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
            'today_count': 0,
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
    # 「今日新增」：口径见 service.count_today（忽略 category 与日期区间，只跟随
    # keyword/单只票这两个范围性筛选）。前端只拿它做一个提示入口，不参与分页。
    today_count = StockAnnouncementService.count_today(
        pool,
        keyword=(keyword or '').strip() or None,
        symbol=(symbol or '').strip() or None,
    )

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
        # 今天发布的公告条数（口径同上，忽略 category/日期区间）。0 也照回，
        # 让前端能区分「今天确实没有」与「字段缺失」。
        'today_count': today_count,
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


# ==================== AI 解读（列表页「AI 解读」抽屉） ====================
#
# 协议：NDJSON（每行一个完整 JSON），与 /api/v1/chat/agent_stream 保持一致，
# 前端按 \n 切分、逐行 JSON.parse。事件类型：
#   {"type":"status","data":"正在读取公告正文…"}     —— 长耗时阶段的提示（正文抽取最慢）
#   {"type":"meta",  ...}                        —— 正文状态/字数/是否命中缓存/模型名
#   {"type":"text",  "data":"片段"}                —— 解读正文增量
#   {"type":"error", "data":"..."}                 —— 出错（流已开启，只能以事件回传）
#
# ⚠️ 为什么不复用 /chat/agent_stream：那个接口的设计前提是「用户自建智能体 + 可调用 MCP 工具」，
#    而这里的角色、prompt、上下文全部由后端固定（避免用户改人格），也不需要工具 ——
#    公告正文已经由我们自己抽好了。硬套过去只会多一层 agent 与会话存储的耦合。


class AnnouncementAiRequest(BaseModel):
    """AI 解读入参。

    - `question` 为空 → 首轮解读（命中 `ai_summary` 缓存则直接回放，不调用模型）
    - `question` 非空 → 追问，需带 `history`（首轮解读在 history[0]，通常是 assistant）
    - `regenerate` → 强制重新生成首轮解读（忽略缓存），追问时忽略此字段
    """
    question: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    regenerate: bool = False


def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8')


def _load_announcement_for_user(announcement_id: int, user_id: int):
    """取公告并做「是否属于当前用户股票池」的校验。

    ⚠️ 越权与不存在**都返回 404**（不返 403）：公告是公开信息，但「我的股票池」这个
       口径不该被用来探测别人的持仓 —— 返回 403 等于确认「这条公告存在且不属于你」。
    """
    row = ai_svc.get_announcement(announcement_id)
    if row is None:
        raise HTTPException(status_code=404, detail='公告不存在')
    pool = set(StockService.get_user_pool_symbols(user_id))
    if row.symbol not in pool:
        raise HTTPException(status_code=404, detail='公告不存在')
    return row


@stock_announcement_router.post('/announcements/{announcement_id}/ai/stream')
async def announcement_ai_stream(announcement_id: int, req: AnnouncementAiRequest = Body(...),
                                 user: dict = Depends(get_current_user)):
    """流式生成公告 AI 解读（首轮解读 / 多轮追问）。"""
    row = await anyio.to_thread.run_sync(_load_announcement_for_user, announcement_id, user['id'])

    question = (req.question or '').strip()
    history = req.history or []
    first_turn = not question

    # 命中缓存：首轮解读已有结果且没要求重生成 → 直接回放，不花一次模型调用。
    # 追问时即使有缓存也继续走模型（问题不同，不能回放）。
    if first_turn and not req.regenerate and (row.ai_summary or '').strip():
        cached = row.ai_summary.strip()

        async def replay_generator():
            yield _ndjson({
                'type': 'meta',
                'cached': True,
                'content_status': row.content_status or None,
                'content_chars': int(row.content_chars or 0),
                'model': row.ai_model,
                'ai_update_time': (row.ai_update_time.strftime('%Y-%m-%d %H:%M:%S')
                                   if row.ai_update_time else None),
                'symbol': row.symbol,
                'title': row.title,
            })
            yield _ndjson({'type': 'text', 'data': cached})

        return StreamingResponse(replay_generator(), media_type='application/x-ndjson')

    model_settings_failed = ''
    try:
        from llms import get_model_by_setting
        staff = await anyio.to_thread.run_sync(lambda: get_model_by_setting('stock_announcement_ai'))
        model_name = staff.model
        platform = getattr(staff, 'platform', '')
    except Exception as e:  # noqa: BLE001 - 配置缺失不该 500，前端要能显示原因
        staff = None
        model_name = ''
        platform = ''
        model_settings_failed = f'大模型未配置或不可用：{e}'

    # ⚠️ 正文抽取与 prompt 组装**必须在返回 StreamingResponse 之前完成**：
    #    app/fastapi_app.py 的 db_session_scope 中间件在 call_next 返回时（也就是流
    #    还没开始发）就会 db_session.remove()，生成器里再用全局 session 读库会拿到
    #    新会话 + detached 对象（写库静默失效、懒加载属性直接抛异常）。
    #    代价只是慢一点（正文抽 0.2~2 秒），换来的是这条链路里不存在"幽灵写"。
    if staff is None:
        async def config_error_generator():
            yield _ndjson({'type': 'error', 'data': model_settings_failed})
        return StreamingResponse(config_error_generator(), media_type='application/x-ndjson')

    content = await anyio.to_thread.run_sync(lambda: ai_svc.ensure_content(row))
    messages = await anyio.to_thread.run_sync(
        lambda: ai_svc.build_messages(row, content, history=history, question=question or None)
    )

    async def response_generator():
        try:
            # 1) 元信息：正文状态/字数/模型。前端据此决定要不要显示「未取到正文」提示
            yield _ndjson({
                'type': 'meta',
                'cached': False,
                'content_status': content.get('status'),
                'content_chars': int(content.get('chars') or 0),
                'content_reason': content.get('reason') or '',
                'model': model_name,
                'symbol': row.symbol,
                'title': row.title,
            })

            # 2) 流式生成（同步 SDK，放线程池）
            stream = await anyio.to_thread.run_sync(
                lambda: staff.client.chat.completions.create(
                    model=model_name, messages=messages, stream=True,
                )
            )
            reply = ''
            usage = None
            for chunk in stream:
                if getattr(chunk, 'usage', None) is not None:
                    usage = chunk.usage
                delta = chunk.choices[0].delta.content or ''
                if delta:
                    reply += delta
                    yield _ndjson({'type': 'text', 'data': delta})

            # 3) 首轮解读落库（追问不落库：存下来下次打开会看到一串没头没尾的问答）
            if first_turn and reply.strip():
                await anyio.to_thread.run_sync(
                    lambda: ai_svc.save_summary(row.id, reply, model_name)
                )

            # 4) token 用量（失败忽略，不影响主链路）
            try:
                from llms.usage_recorder import record_llm_usage
                from utils.auth import request_user_id_var
                record_llm_usage(
                    user_id=request_user_id_var.get() or user.get('id'),
                    scene=getattr(staff, 'scene', 'stock_announcement_ai'),
                    platform=platform,
                    model=model_name,
                    prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                    completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                    total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                    input_text='\n'.join(f"{m['role']}: {m['content']}" for m in messages)[:8000],
                    output_text=reply,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f'[announcement-ai] token 记录失败（已忽略）：{e}')

        except Exception as e:  # noqa: BLE001
            logger.error(f'[announcement-ai] 解读失败 id={announcement_id}: {e}')
            yield _ndjson({'type': 'error', 'data': f'解读失败：{str(e)}'})

    return StreamingResponse(response_generator(), media_type='application/x-ndjson')


# ==================== 原文 PDF 代理（列表页「阅读」抽屉的 iframe 数据源） ====================
#
# 为什么不把 iframe 直接指向巨潮直链（`static.cninfo.com.cn`）：
#   1. 上游给的是 **http://** 直链（实测），生产页面走 https → 浏览器按「混合内容」
#      直接拦掉，表现为抽屉里一片空白，且控制台之外看不出原因；
#   2. 上游 CORS 只放行 `*.cninfo.com.cn`，前端 fetch 成 blob 也读不到响应体；
#   3. 同源代理后可以复用登录鉴权（越权仍 404），页面也不必把上游域名暴露出去。
#
# ⚠️ 透传 Range：Chrome/Edge 内置 PDF 阅读器先发 `Range: bytes=0-`，再按需取后续片段
#    （上游确实回了 `Accept-Ranges: bytes`）。不透传会导致「整包下完才显示」，
#    而且阅读器每次跳页都重新拉全量。上游返 206 就原样透传 206 + Content-Range。

# (连接, 读) 超时秒数：上游单份几百 KB、实测 0.1s，给 30 秒足够；
# 别设太大 —— 上游偶发抽风时用户的抽屉会一直转圈。
PDF_PROXY_TIMEOUT = (10, 30)
# 只信任巨潮的静态域名。公告行里的 pdf_url 来自我们自己的抓取，但表是共享的，
# 万一有别的写入路径，代理就成了 SSRF 跳板 —— 白名单是最便宜的防线。
PDF_ALLOWED_HOSTS = ('static.cninfo.com.cn', 'www.cninfo.com.cn', 'static.cninfo.com')
# 单份上限：防止异常链接把内存/带宽吃满（正常公告 PDF 多在 100~2000 KB）
PDF_MAX_BYTES = 40 * 1024 * 1024


def _pdf_content_disposition(row) -> str:
    """inline + 中文文件名（ASCII 兜底 + RFC 5987 编码）。

    inline 是必须的：attachment 会让浏览器直接下载，iframe 里就看不到内容了。
    """
    fallback = f'{row.announcement_id or row.id}.pdf'
    pretty = f'{(row.stock_name or row.symbol or "")}-{(row.announce_date or "")}-{(row.title or "")}'.strip('-')
    pretty = (pretty or fallback)[:120] + '.pdf'
    # filename 里不能出现引号/换行（会破坏头部），统一清掉
    safe_ascii = fallback.replace('"', '').replace('\r', '').replace('\n', '')
    encoded = quote(pretty.replace('"', '').replace('\r', '').replace('\n', ''), safe='')
    return f'inline; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded}'


@stock_announcement_router.get('/announcements/{announcement_id}/pdf')
def announcement_pdf(announcement_id: int, request: Request,
                     user: dict = Depends(get_current_user)):
    """代理巨潮公告原文 PDF（同源，供前端 iframe 阅读）。

    ⚠️ 这是个**同步** def：`requests` 是阻塞的，交给 FastAPI 的线程池跑，
       比在 async 里裸调更安全（本项目 async 路由会让并发退化为 1）。
    ⚠️ 返回的是 StreamingResponse，`row` 只在**返回之前**被读取（url / 标题 / 日期）。
       生成器里不能再碰 ORM 对象 —— 请求级 Session 在响应开始前就被 remove 了，
       detached 对象上取属性会抛 DetachedInstanceError（AI 解读接口踩过同一个坑）。
    """
    row = _load_announcement_for_user(announcement_id, user['id'])

    url = (row.pdf_url or '').strip()
    if not url:
        raise HTTPException(status_code=404, detail='该公告没有原文 PDF')
    if urlparse(url).hostname not in PDF_ALLOWED_HOSTS:
        logger.warning(f'[announcement-pdf] 拒绝非白名单域名 id={row.id} url={url[:120]}')
        raise HTTPException(status_code=502, detail='原文地址不在允许范围内')

    # 先把要用的字段读成普通值：生成器执行时 row 已经是 detached 的
    disposition = _pdf_content_disposition(row)

    upstream_headers = {
        # 上游对无 UA 的请求偶尔返 403/空包；Referer 不是必需但更接近真实浏览行为
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Referer': 'https://www.cninfo.com.cn/',
    }
    range_header = request.headers.get('range')
    if range_header:
        upstream_headers['Range'] = range_header

    try:
        upstream = requests.get(url, headers=upstream_headers, stream=True,
                                timeout=PDF_PROXY_TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        logger.warning(f'[announcement-pdf] 上游请求失败 id={announcement_id}: {e}')
        raise HTTPException(status_code=502, detail='原文下载失败，请稍后重试')

    if upstream.status_code not in (200, 206):
        upstream.close()
        logger.warning(f'[announcement-pdf] 上游返回 {upstream.status_code} id={announcement_id}')
        raise HTTPException(status_code=502, detail=f'原文下载失败（上游 {upstream.status_code}）')

    content_type = (upstream.headers.get('content-type') or '').lower()
    # 上游偶尔会把错误页当 200 返回（Content-Type: text/html）—— 那不是 PDF，
    # 塞给 iframe 只会显示一坨 HTML，直接判失败更诚实。
    if 'pdf' not in content_type:
        upstream.close()
        logger.warning(f'[announcement-pdf] 上游不是 PDF id={announcement_id} type={content_type}')
        raise HTTPException(status_code=502, detail='上游返回的不是 PDF 文件')

    try:
        length = int(upstream.headers.get('content-length') or 0)
    except (TypeError, ValueError):
        length = 0
    if length > PDF_MAX_BYTES:
        upstream.close()
        raise HTTPException(status_code=413, detail='原文文件过大，请在新窗口打开')

    out_headers = {
        'Content-Disposition': disposition,
        'Accept-Ranges': 'bytes',
        # Cache-Control 不在这里写：由 app/fastapi_app.py 的 apply_cache_policy 统一决策
        # （`/pdf` 后缀 → private, max-age=300），避免同一个口径在两处各存一份真值。
    }
    if length:
        out_headers['Content-Length'] = str(length)
    if upstream.status_code == 206 and upstream.headers.get('content-range'):
        out_headers['Content-Range'] = upstream.headers['content-range']

    def _iter_chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    # 同步生成器交给 StreamingResponse 后会被丢进线程池迭代，不会阻塞事件循环
    return StreamingResponse(
        _iter_chunks(),
        status_code=upstream.status_code,
        media_type='application/pdf',
        headers=out_headers,
    )
