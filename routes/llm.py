"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from llms import _PLATFORM_REGISTRY, list_platform_models
from app.fastapi_app import json_resp
from utils.auth import get_current_user
from utils.logger import logger
from utils.redis_obj import redis_obj

# 全站登录制：整个 router 加登录鉴权（见 etf.py 顶部说明）。
llm_router = APIRouter(prefix='/api/v1', tags=['LLM'],
                       dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# 模型列表缓存策略
#
# 模型列表变化极低频（上游新上/下线模型），成功结果缓存 30 分钟。
#
# ⚠️ 失败**不进缓存**。原实现是 `@cache` 包住整个路由函数，而本路由把上游异常
#    收敛成 200 + error 字段（不是 5xx），于是**一次 429 会被缓存 30 分钟** ——
#    这半小时里无论前端刷新多少次、切多少次平台，拿到的都是同一条错误，
#    用户会以为「百度平台坏了」，其实上游早就恢复了。
#
# 三层降级：
#   1. 新鲜缓存（30 分钟内）→ 直接返回，不打上游；
#   2. 上游失败但有旧列表 → 返回旧列表（stale），error 置空、只给 warning，
#      下拉照常有值（模型列表过期几小时，远好过下拉空白、被迫手打模型名）；
#   3. 上游失败且从未成功过 → 空列表 + 中文 error，前端退化为手动输入。
# ---------------------------------------------------------------------------
_MODELS_FRESH_SECONDS = 1800
# 旧值保留 7 天：这是 stale 兜底的数据来源。
_MODELS_KEEP_SECONDS = 7 * 86400
# 上游失败后的冷却窗口。百度千帆的 GET /models 限流很严（429 OverRateLimit），
# 失败后立刻重试只会把限流窗口越拖越长；而前端「每次切换平台」都会打一次接口。
_MODELS_COOLDOWN_SECONDS = 60

_MODELS_KEY = 'llm:models:{platform}'
_MODELS_COOLDOWN_KEY = 'llm:models:cooldown:{platform}'

# 同平台并发合流：platform -> Event（存在即表示「已有线程在打上游」）。
# 进程内有效（uvicorn 线程池跑同步路由）；跨进程靠 Redis 缓存 + 冷却兜底。
# 等待上限比上游超时（15s）留足余量，避免 leader 卡住时等待者一起吊死。
_INFLIGHT_WAIT_SECONDS = 25
_inflight_guard = threading.Lock()
_inflight: Dict[str, threading.Event] = {}


def _acquire_flight(platform: str) -> Optional[threading.Event]:
    """
    抢「打上游」的资格。
    :return: None = 抢到了，你是 leader，去调上游；
             否则返回一个 Event，等它 set 之后去读缓存。
    """
    with _inflight_guard:
        pending = _inflight.get(platform)
        if pending is not None:
            return pending
        _inflight[platform] = threading.Event()
        return None


def _release_flight(platform: str) -> None:
    with _inflight_guard:
        ev = _inflight.pop(platform, None)
    if ev is not None:
        ev.set()


def _wait_flight(ev: threading.Event) -> None:
    ev.wait(timeout=_INFLIGHT_WAIT_SECONDS)


def _is_rate_limited(err: Exception) -> bool:
    """识别上游限流：SDK 异常优先看 status_code，兜底再匹配文本（不同 SDK 文案不一）"""
    if getattr(err, 'status_code', None) == 429 or getattr(err, 'status', None) == 429:
        return True
    text = str(err).lower()
    return ('429' in text or 'over rate limit' in text
            or 'overratelimit' in text or 'rate limit' in text)


def _human_age(seconds: int) -> str:
    """把「多少秒前」说成人话，给 warning 文案用"""
    if seconds < 120:
        return '刚刚'
    if seconds < 3600:
        return f'{seconds // 60} 分钟'
    if seconds < 86400:
        return f'{seconds // 3600} 小时'
    return f'{seconds // 86400} 天'


def _read_models_cache(platform: str) -> Optional[Dict[str, Any]]:
    """读缓存。Redis 不可用 / 内容损坏一律当成「没有」—— 缓存是加速，不是依赖。"""
    try:
        raw = redis_obj.get(_MODELS_KEY.format(platform=platform))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'ignore')
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            return None
        return data
    except Exception as e:
        logger.debug(f'读取模型列表缓存失败（忽略）：platform={platform}, err={e}')
        return None


def _write_models_cache(platform: str, models: List[str]) -> None:
    payload = {'models': models, 'ts': int(time.time())}
    try:
        redis_obj.set(_MODELS_KEY.format(platform=platform),
                      json.dumps(payload, ensure_ascii=False), ex=_MODELS_KEEP_SECONDS)
    except Exception as e:
        logger.warning(f'写入模型列表缓存失败（忽略）：platform={platform}, err={e}')


def _in_cooldown(platform: str) -> bool:
    try:
        return bool(redis_obj.exists(_MODELS_COOLDOWN_KEY.format(platform=platform)))
    except Exception:
        return False


def _start_cooldown(platform: str) -> None:
    try:
        redis_obj.set(_MODELS_COOLDOWN_KEY.format(platform=platform), '1',
                      nx=True, ex=_MODELS_COOLDOWN_SECONDS)
    except Exception:
        pass


def _result(platform: str, models: List[str], *, error: Optional[str], warning: Optional[str],
            source: str, rate_limited: bool, cached_ts: Optional[int]) -> Dict[str, Any]:
    """统一响应结构。source 仅用于排障：cache / upstream / stale / none。"""
    return {
        'platform': platform,
        'models': models,
        'error': error,
        'warning': warning,
        'source': source,
        'stale': source == 'stale',
        'rate_limited': rate_limited,
        'cached_ts': cached_ts,
    }


def _degraded(platform: str, cached: Optional[Dict[str, Any]], reason: str,
              rate_limited: bool) -> Dict[str, Any]:
    """上游不可用时的统一出口：有旧列表就顶上，没有就空列表 + error。"""
    models = (cached or {}).get('models') or []
    if models:
        ts = int((cached or {}).get('ts') or 0)
        age = max(0, int(time.time()) - ts)
        return _result(platform, models, error=None,
                       warning=f'{reason}；当前展示的是 {_human_age(age)}前成功获取的列表',
                       source='stale', rate_limited=rate_limited, cached_ts=ts or None)
    return _result(platform, [], error=reason, warning=None,
                   source='none', rate_limited=rate_limited, cached_ts=None)


def _fetch_platform_models(platform: str) -> Dict[str, Any]:
    """
    拉单个平台的模型列表（带缓存与降级），**不抛异常** —— 批量模式下某个平台
    失败不该影响其它平台。
    """
    cached = _read_models_cache(platform)
    now = int(time.time())

    # 1. 新鲜缓存：不打上游
    if cached and now - int(cached.get('ts') or 0) < _MODELS_FRESH_SECONDS:
        return _result(platform, cached['models'], error=None, warning=None,
                       source='cache', rate_limited=False, cached_ts=cached.get('ts'))

    # 2. 冷却中：刚失败过，别再撞上游（否则 429 窗口会被自己不断续期）
    if _in_cooldown(platform):
        return _degraded(platform, cached,
                         f'上游接口刚失败过，{_MODELS_COOLDOWN_SECONDS} 秒内不再重试',
                         rate_limited=True)

    # 3. 合流：同一平台同一时刻只允许一个线程打上游，其余等它的结果。
    #    前端已经按平台去重了，但「多开一个标签页」「两个人在同一点开设置页」
    #    仍会让 N 个请求同时到达 —— 对限流严格的上游就是 N 次并发。
    #    uvicorn 用线程池跑同步路由，进程内锁有效；多进程/多实例再靠 Redis 冷却兜底。
    pending = _acquire_flight(platform)
    if pending is not None:
        _wait_flight(pending)
        cached_after = _read_models_cache(platform)
        if cached_after and int(time.time()) - int(cached_after.get('ts') or 0) < _MODELS_FRESH_SECONDS:
            # leader 成功并写了缓存 —— 直接复用，等于「免费」拿到同一份结果
            return _result(platform, cached_after['models'], error=None, warning=None,
                           source='cache', rate_limited=False, cached_ts=cached_after.get('ts'))
        # leader 失败（已写冷却）或还在飞 —— 不再自己打一次，避免放大限流
        return _degraded(platform, cached_after or cached,
                         '同一平台的另一个请求正在进行或刚刚失败，稍后会自动恢复',
                         rate_limited=True)

    # 4. 打上游（无论成败都要释放合流标记）
    try:
        try:
            models = list_platform_models(platform)
        except ValueError as e:
            # 配置类错误（平台未添加 / 未配置 Key）：不是上游故障 ——
            #   ① 不进冷却（本地检查而已，没消耗上游配额）；
            #   ② 不套「上游接口不可用」前缀（文案本身已是给用户看的中文指引，套了会变成
            #      「失败：上游接口不可用：大模型平台「智谱 AI」尚未添加…」两层废话）；
            #   ③ 不走 stale 兜底（Key 被删了却还展示旧列表，会让人误以为能用）。
            logger.debug(f'拉取平台模型列表被跳过（配置未完成）：platform={platform}, err={e}')
            return _result(platform, [], error=str(e), warning=None,
                           source='none', rate_limited=False, cached_ts=(cached or {}).get('ts'))
        except Exception as e:
            rate_limited = _is_rate_limited(e)
            _start_cooldown(platform)
            logger.warning(f'拉取平台模型列表失败：platform={platform}, '
                           f'rate_limited={rate_limited}, err={e}')
            if rate_limited:
                reason = '上游限流（HTTP 429），请稍后重试，或直接在模型名处手动填写'
            else:
                reason = f'上游接口不可用：{e}'
            return _degraded(platform, cached, reason, rate_limited)

        _write_models_cache(platform, models)
        logger.debug(f'拉取平台模型列表成功：platform={platform}, count={len(models)}')
        return _result(platform, models, error=None, warning=None,
                       source='upstream', rate_limited=False, cached_ts=now)
    finally:
        _release_flight(platform)


# 同步 `def` 路由（上游 HTTP 调用，同步 requests/openai SDK），由 Starlette 丢线程池执行，
# 见并发模型约定：默认写 def，不要写 async def。
@llm_router.get('/llm/models')
def get_llm_models(platform: str = Query(default=None, description='平台标识，缺省则返回全部平台')):
    """
    实时调用各大模型平台 OpenAI 兼容的 GET /models 接口，返回可用模型列表。

    - 带 platform 参数：只拉该平台（前端切换「大模型平台」下拉时联动调用）
    - 不带 platform：并发拉取全部支持的平台，供一次性展示

    响应统一为 {platform: {platform, models, error, warning, source, stale,
    rate_limited, cached_ts}}：

    - `models` 非空即可填入下拉；`error` 非空表示该平台一个模型都拿不到；
    - `warning` 非空表示「列表可用但不是最新的」（走了 stale 兜底），只提示不报错；
    - `source` 排障用：upstream / cache / stale / none。

    缓存见文件顶部说明：成功结果缓存 30 分钟，**失败不串缓存**。
    """
    if platform:
        platform = platform.strip()
        if platform not in _PLATFORM_REGISTRY:
            return json_resp({
                platform: {'platform': platform, 'models': [], 'warning': None,
                           'error': f"不支持的平台，支持：{', '.join(sorted(_PLATFORM_REGISTRY))}",
                           'source': 'none', 'stale': False, 'rate_limited': False,
                           'cached_ts': None}
            })
        return json_resp({platform: _fetch_platform_models(platform)})

    # 并发拉全部平台，任一平台失败不影响其它平台
    result = {}
    with ThreadPoolExecutor(max_workers=len(_PLATFORM_REGISTRY)) as pool:
        futures = {pool.submit(_fetch_platform_models, p): p for p in _PLATFORM_REGISTRY}
        for fut in as_completed(futures):
            r = fut.result()
            result[r['platform']] = r
    return json_resp(result)
