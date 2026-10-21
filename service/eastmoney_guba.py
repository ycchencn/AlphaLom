"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

东方财富股吧抓取器（个股发帖）。

## 为什么长这样

股吧没有公开 API（网传的 gbapi/gbpush 等端点实测全为 404/403），唯一稳定可用的入口是
服务端渲染的列表页，帖子数据以 JSON 形式内嵌在 HTML 的 `var article_list = {...}` 里。

⚠️ 三个必须遵守的约束（2026-10 实测得出，违反会导致功能静默失效或被封 IP）：

1. **不能用 HTTP 状态码判断成功**。触发反爬时返回的是 `200 OK` + 2826 字节的「身份核实」
   验证页，不是 403。若按状态码判断，会把验证页当正常数据解析，从而产出空样本、
   情绪分一路缺失，且日志上一切正常 —— 比直接报错危险得多。
   本模块统一用「响应体是否含 article_list 标记 + 长度阈值」判定。

2. **必须全局限速**。实测约 80~100 请求 / 10 分钟即触发封锁，且是 IP 级、全站生效
   （列表页、详情页、首页一起拦），≥9 分钟不恢复，需人工过验证码。
   这里用 Redis 做跨进程的最小间隔锁（web / scheduler / job_server 是三个独立进程，
   进程内 sleep 拦不住并发），默认间隔 20 秒。

3. **命中验证页要立刻停手**。继续重试会延长封锁。命中后写一个冷却键，
   冷却期内所有抓取请求直接跳过（相当于熔断），而不是逐个失败重试。

## 数据口径

- 列表页会**混入非目标股吧的推荐内容**（实测抓 600519 时混进了「财富号评论」bar 的帖子），
  必须按 `stockbar_code == 目标代码` 过滤，否则情绪样本被污染。
- `post_top_status == 1` 是置顶帖，往往是几天前的老帖，不代表当期情绪，单独标记后由
  分析层降权/剔除。
- 列表页只提供标题，**不含正文**。正文需逐帖请求详情页，是 8 倍请求量，
  第一版刻意不做（单 IP 不可持续），详见可行性报告。
"""

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from config import (
    guba_block_cooldown,
    guba_max_pages,
    guba_min_interval,
)
from utils.logger import logger
from utils.redis_obj import redis_obj

# ---------------------------------------------------------------- 常量

LIST_URL = 'https://guba.eastmoney.com/list,{symbol}.html'
LIST_PAGE_URL = 'https://guba.eastmoney.com/list,{symbol},f_{page}.html'
DETAIL_URL = 'https://guba.eastmoney.com/news,{symbol},{post_id}.html'

# 正常列表页约 160KB+；验证页约 2.8KB。用长度做第一道粗筛，避免大页面无谓的正则扫描。
_MIN_HTML_BYTES = 20000
# 列表页 JSON 的必经标记
_ARTICLE_LIST_MARK = 'var article_list'

_RATE_KEY = 'alphalom:guba:ratelimit'
_BLOCK_KEY = 'alphalom:guba:blocked'

_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://guba.eastmoney.com/',
}

_session: Optional[requests.Session] = None


class GubaBlockedError(Exception):
    """命中反爬验证页。调用方应中止整批抓取，而不是重试。"""


class GubaRateLimited(Exception):
    """冷却期内，跳过请求。"""


# ---------------------------------------------------------------- 基础设施

def _get_session() -> requests.Session:
    """复用连接（Session 保持 TCP 连接与 cookie，比每次新建更像个正常浏览器）。"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_HEADERS)
    return _session


def _wait_rate_limit() -> None:
    """跨进程最小间隔限速。

    用 Redis 的 SET NX EX 实现「一次性放行」：抢到键的请求立即发出，
    没抢到的等到键过期（= 距上次请求已满 min_interval）再抢一次。

    为什么不用进程内 sleep：web、scheduler、job_server 是三个独立进程，
    各自 sleep 20 秒互不知道，三个进程叠加就变成每 7 秒一个请求，限速形同虚设。
    """
    interval = max(1, int(guba_min_interval))
    for _ in range(3):
        try:
            if redis_obj.set(_RATE_KEY, '1', nx=True, ex=interval):
                return
            ttl = redis_obj.ttl(_RATE_KEY)
        except Exception as e:  # noqa: BLE001
            # Redis 不可用时退化为本地等待，宁可慢也不能裸奔
            logger.warning(f'[guba] 限速键不可用，退化为本地等待: {e}')
            time.sleep(interval)
            return
        if ttl is None or ttl < 0:
            ttl = interval
        time.sleep(min(ttl + 0.3, interval + 1))
    # 多次未抢到（极端并发），兜底再等一轮
    time.sleep(interval)


def _check_block_cooldown() -> None:
    """冷却期内直接跳过，不发任何请求。"""
    try:
        if redis_obj.exists(_BLOCK_KEY):
            ttl = redis_obj.ttl(_BLOCK_KEY)
            raise GubaRateLimited(f'股吧抓取处于冷却期，剩余 {ttl}s')
    except GubaRateLimited:
        raise
    except Exception:  # noqa: BLE001
        # Redis 异常时不阻塞业务
        return


def _mark_blocked(reason: str) -> None:
    try:
        redis_obj.set(_BLOCK_KEY, reason, ex=max(60, int(guba_block_cooldown)))
        logger.error(
            f'[guba] 触发反爬（{reason}），已进入 {guba_block_cooldown}s 冷却。'
            f'需要人工在浏览器打开 https://guba.eastmoney.com/ 完成身份核实后才会恢复。'
        )
    except Exception:  # noqa: BLE001
        logger.error(f'[guba] 触发反爬（{reason}），且冷却键写入失败')


def _http_get(url: str) -> str:
    """带限速与反爬校验的 GET。失败一律抛异常，不返回 None（避免上层把失败当空数据）。"""
    _check_block_cooldown()
    _wait_rate_limit()

    try:
        resp = _get_session().get(url, timeout=15)
    except requests.RequestException as e:
        raise RuntimeError(f'股吧请求失败 {url}: {e}') from e

    text = resp.text or ''

    # 校验一：长度。验证页恒定 ~2.8KB，正常列表页 160KB+
    if len(text) < _MIN_HTML_BYTES:
        _mark_blocked(f'响应过短 {len(text)}B')
        raise GubaBlockedError(f'疑似被拦截：响应仅 {len(text)} 字节')

    # 校验二：标记。即便长度够，也要确认是列表页而不是别的兜底页
    if _ARTICLE_LIST_MARK not in text:
        _mark_blocked('缺少 article_list 标记')
        raise GubaBlockedError('页面不含 article_list，可能已改版或被拦截')

    return text


# ---------------------------------------------------------------- 解析

def extract_article_list(html: str) -> Optional[Dict[str, Any]]:
    """从 HTML 中截取 `var article_list = {...}` 并解析为 dict。

    不能用正则 `\\{.*?\\}` —— JSON 里嵌套了 `user_extendinfos`、`bar_info` 等多层对象，
    非贪婪匹配会在第一个 `}` 就截断。这里用括号配平（跳过字符串内的括号与转义）。
    """
    marker = html.find(_ARTICLE_LIST_MARK)
    if marker < 0:
        return None
    start = html.find('{', marker)
    if start < 0:
        return None

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                raw = html[start:i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.warning(f'[guba] article_list JSON 解析失败: {e}')
                    return None
    return None


def _polish_post(raw: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    """把上游字段压成内部结构。非本吧帖子（跨吧推荐）返回 None。"""
    if str(raw.get('stockbar_code') or '') != str(symbol):
        return None

    title = (raw.get('post_title') or '').strip()
    if not title:
        return None

    return {
        'post_id': raw.get('post_id'),
        'title': title,
        'publish_time': raw.get('post_publish_time') or '',
        'click': int(raw.get('post_click_count') or 0),
        'comment': int(raw.get('post_comment_count') or 0),
        'author': (raw.get('user_nickname') or '').strip(),
        'is_top': raw.get('post_top_status') == 1,
        'is_majia': bool(raw.get('user_is_majia')),
    }


# ---------------------------------------------------------------- 对外接口

def fetch_posts(symbol: str, hours: int = 24, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
    """抓取某只股票最近 N 小时的股吧帖子（只含标题，不含正文）。

    翻页策略：从第 1 页往后翻，一旦发现某一页里**最早**的帖子已经早于时间窗口，
    说明窗口已覆盖完，停止翻页。最多翻 max_pages 页（防止冷门股把 100 页全翻一遍）。
    """
    symbol = str(symbol).strip()
    if not symbol:
        raise ValueError('symbol 不能为空')

    pages = max(1, int(max_pages or guba_max_pages))
    cutoff = datetime.now() - timedelta(hours=hours)

    seen = set()
    collected: List[Dict[str, Any]] = []

    for page in range(1, pages + 1):
        url = (LIST_URL.format(symbol=symbol) if page == 1
               else LIST_PAGE_URL.format(symbol=symbol, page=page))
        html = _http_get(url)
        data = extract_article_list(html)
        if not data:
            logger.warning(f'[guba] {symbol} 第 {page} 页无有效 article_list，停止翻页')
            break

        page_oldest: Optional[datetime] = None
        for raw in (data.get('re') or []):
            post = _polish_post(raw, symbol)
            if not post:
                continue
            if post['post_id'] in seen:
                continue
            seen.add(post['post_id'])

            try:
                published = datetime.strptime(post['publish_time'], '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                continue

            if page_oldest is None or published < page_oldest:
                page_oldest = published
            if published >= cutoff:
                collected.append(post)

        if page_oldest and page_oldest < cutoff:
            break

    logger.info(f'[guba] {symbol} 抓取 {hours}h 帖子 {len(collected)} 条')
    return collected


def sample_posts(posts: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """按互动量分层采样。

    帖子互动量极度右偏（实测茅台 24h 内点击数中位数 198、最大 8269），
    简单截断会只留高互动帖、丢掉长尾情绪；纯随机又会丢掉关键声音。
    做法：一半按互动量取头部，一半在全量上等距抽样，兼顾「焦点」与「分布」。
    """
    if not posts:
        return []
    limit = max(1, int(limit))
    if len(posts) <= limit:
        return list(posts)

    ranked = sorted(posts, key=lambda p: (p['click'] + p['comment'] * 20), reverse=True)
    head_n = max(1, limit // 2)
    head = ranked[:head_n]

    head_ids = {p['post_id'] for p in head}
    rest = [p for p in posts if p['post_id'] not in head_ids]
    tail_n = limit - len(head)

    if tail_n <= 0 or not rest:
        return head
    step = max(1, len(rest) // tail_n)
    tail = rest[::step][:tail_n]
    return head + tail
