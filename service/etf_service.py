"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models.database import db_session
from models import EtfWatchlist

from utils.logger import logger
from utils.data_loader import databull

# 因子覆盖判定阈值（交易日个数）。
# 日更任务是 save_last=True —— 每个交易日只落**最后一行**，所以「刚加进来的新标的」
# 在 factor_values 里要么 0 行、要么只有 1 天；此时 52week_low/high 是用极短的窗口
# 算出来的（rolling(min_periods=1) 不报错，静默退化成「最近 N 天高低」），
# 历史分位恒 100%/0%，因子走势图只有一个点。
# 各因子窗口决定的最小有意义长度：52week_* 要 252 个交易日；前端「因子走势（近 250 日）」
# 也要 250 个点才画得满。低于该值即视为「需要回填历史」。
FACTOR_MIN_HISTORY_DAYS = 250

# 新入池标的的因子回填窗口（自然日）。与 tools/_backfill_etf_factors.py 的
# BACKFILL_DAYS 保持一致：1100 天 ≈ 3 年，扣除 50 日动量窗口的 dropna 后仍能落满
# 一个完整 52 周窗口（252 个交易日）。传 400 天凑不齐 252 个交易日，52 周区间会偏低。
FACTOR_BACKFILL_DAYS = 1100


class EtfService:
    """ETF 自选（监控）列表的持久化层，对应 etf_watchlist 表。

    多用户：这张表是**用户私有**的，读写都要带 user_id。
    ⚠️ 唯一约束是 (user_id, symbol)，所以「加过没有」的判断也必须限定在同一个用户内 ——
    只按 symbol 查会把别的用户的记录当成本用户已有，导致「加不上也报成功」。
    """

    @staticmethod
    def list_watchlist(user_id):
        """
        读取**某个用户**的监控 ETF（按加入时间倒序，最新加入的在最前）。

        ⚠️ user_id 必传，None 直接抛 ValueError：用户私有数据没有「不传就取全部」
        这种合理语义，而静默返回全部用户的清单正是多用户下最危险的默认行为。
        定时任务要拿「全站并集」请用 `list_all_symbols()`。
        """
        if user_id is None:
            raise ValueError('list_watchlist 必须指定 user_id（任务侧请用 list_all_symbols）')
        try:
            return db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == int(user_id)
            ).order_by(EtfWatchlist.created_at.desc()).all()
        except Exception as e:
            logger.error(f"list_etf_watchlist failed: {e}")
            return []

    @staticmethod
    def list_all_symbols():
        """
        **全部用户**自选的去重并集（按代码排序）。

        给日更任务用：它们没有用户上下文（也不该有），而恐贪/因子都是「按标的算」的
        公共数据 —— 两个用户都选了同一只 ETF 时只应算一次，所以这里 DISTINCT。
        """
        try:
            rows = db_session.query(EtfWatchlist.symbol).distinct().all()
            return sorted({r[0] for r in rows if r[0]})
        except Exception as e:
            logger.error(f"list_all_etf_symbols failed: {e}")
            return []

    @staticmethod
    def add_watchlist(user_id, symbol: str, name: str = None) -> EtfWatchlist:
        """
        把一只 ETF 加入**指定用户**的监控列表。
        - user_id 为空抛 ValueError（宁可报错也不要插一条无主数据 —— 那条数据谁都看不见）；
        - symbol 为空抛 ValueError；
        - 该用户已加过则直接返回已有记录（幂等）；
        - name 未传时尝试从 databull.get_etf_info 取名称兜底；
        - 唯一约束冲突（极端并发）回滚后回查已有记录。
        """
        if user_id is None:
            raise ValueError('add_watchlist 必须指定 user_id')
        user_id = int(user_id)

        symbol = (symbol or '').strip()
        if not symbol:
            raise ValueError('ETF 代码不能为空')

        # ⚠️ 幂等查询必须同时限定 user_id：只按 symbol 查会把别的用户已加的记录
        # 当成本用户已有，直接返回它 —— 用户以为加上了，实际自己的清单里没有。
        existing = db_session.query(EtfWatchlist).filter(
            EtfWatchlist.user_id == user_id,
            EtfWatchlist.symbol == symbol,
        ).first()
        if existing:
            return existing

        if not name:
            try:
                info = databull.get_etf_info(symbol) or {}
                name = info.get('name') if isinstance(info, dict) else None
            except Exception as e:
                logger.warning(f"get_etf_info(name) failed for {symbol}: {e}")

        item = EtfWatchlist(user_id=user_id, symbol=symbol, name=name)
        try:
            db_session.add(item)
            db_session.commit()
            db_session.refresh(item)
            return item
        except IntegrityError:
            db_session.rollback()
            logger.warning(f"EtfWatchlist duplicate on insert: user={user_id} {symbol}")
            return db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == user_id,
                EtfWatchlist.symbol == symbol,
            ).first()
        except Exception as e:
            db_session.rollback()
            logger.error(f"add_etf_watchlist failed for {symbol}: {e}")
            raise

    @staticmethod
    def dispatch_factor_backfill(symbol: str, reason: str = '') -> bool:
        """把「该 ETF 的因子回填」投进任务队列（异步执行），返回是否投递成功。

        ── 为什么需要它 ──────────────────────────────────────────────
        `add_watchlist` 只往 `etf_watchlist` 插一行，**不触发任何因子计算**。
        而 ETF 洞察列表的 52 周区间、详情页的技术分析卡都读 `factor_values`，
        这些数据平时只由 20:10 的日更任务（`job_update_stock_factor_daily`）按
        「监控清单 ∪ 轮动池」全量重算 —— 于是**新加的 ETF 在下一个日更跑完之前，
        页面上 52 周区间是空的**（这正是用户报的「加完 ETF 因子没算、显示缺很多」）。

        个股有对称的实现（`routes/stock.py::_dispatch_stock_analysis`），ETF 一直没有。

        ── 为什么投的是 save_last=False ──────────────────────────────
        走 `save_last=False` 分支 = 先 `delete_by_ticker` 再整段重写，落的是
        **3 年历史**（见 FACTOR_BACKFILL_DAYS）。若只投 save_last=True，只会落最新
        一天，52 周分位仍是退化值 —— 等于没修。

        ── 幂等去重 ─────────────────────────────────────────────────
        对**年轻 ETF**（上市不足 250 个交易日，如 159258 只有 234 天），历史天数
        永远到不了 FACTOR_MIN_HISTORY_DAYS，于是「重复添加」会反复触发重投 ——
        队列重塞一份 3 年回填（幂等无害但浪费）。这里用 Redis NX 键做**冷却**
        （回填通常几十秒完成，冷却 1 小时足够），冷却期内重复投递直接跳过。

        ── 约定 ─────────────────────────────────────────────────────
        `job_args` 必须与「手动回填」（tools/_backfill_etf_factors.py）**完全一致**，
        不要新增键：新增键会要求 web 与 job_server 同时部署，否则旧消费者
        `job_func(**job_args)` 直接 TypeError（见 routes/stock.py 里同样的告诫）。
        asset_type 显式传 'etf'，绝不靠代码号段猜（562xxx 曾被当个股取数）。
        """
        symbol = (symbol or '').strip()
        if not symbol:
            return False
        try:
            # 冷却去重：同一标的 1 小时内只投一次（Redis NX，见 utils/redis_obj.py）
            from utils.redis_obj import redis_obj
            cooldown_key = f'alphalom:etf_factor_backfill:{symbol}'
            if not redis_obj.set(cooldown_key, '1', nx=True, ex=3600):
                logger.info(f'[etf] {symbol} 处于回填冷却期，跳过重复投递（{reason}）')
                return False

            # 延迟导入：避免 web 启动期把 job/service 的整条依赖链拖进本模块
            from service import JobService
            JobService.send_job({
                'job_func': 'job_update_stock_factor',
                'job_args': {
                    'stock_code': symbol,
                    'asset_type': 'etf',
                    'save_last': False,
                    'time_period': -FACTOR_BACKFILL_DAYS,
                },
            })
            logger.info(f'[etf] 已投递因子回填任务: {symbol}（{reason}）')
            return True
        except Exception as e:
            # 投递失败不能让「添加 ETF」这个主流程失败：它已经把监控清单写好了，
            # 最坏情况只是回到「等下一个日更」的旧行为。
            logger.warning(f'[etf] 投递因子回填任务失败 {symbol}: {e}')
            return False

    @staticmethod
    def needs_factor_backfill(symbol: str) -> bool:
        """该 ETF 的因子历史是否**明显不足**（需要回填 3 年历史）。

        判据 = `factor_values` 里有因子的交易日个数 < FACTOR_MIN_HISTORY_DAYS（250）。
        - 新加且从未算过 → 0 天 → 需要回填；
        - 只被日更落过 1~2 天 → 需要回填（52 周分位是退化值）；
        - 正常长期日更累积 → 250+ 天 → 不需要。

        ⚠️ 用它做「是否投递」的门槛，而不是「有行就跳过」：只判空会让**部分历史**
        （如只有 1 天）的标的永远谈不上，退化值一直挂着。
        """
        try:
            from service.factor_service import FactorValueService
            days = FactorValueService.get_history_days([symbol]).get(symbol, 0)
            return days < FACTOR_MIN_HISTORY_DAYS
        except Exception as e:
            # 判不出来时保守返回 False（不投递）：宁可少投一次，也不要因为一次查询异常
            # 就批量投递回填任务（那会把 3 年窗口 × N 只的重活塞满队列）。
            logger.warning(f'[etf] 因子覆盖检查失败 {symbol}: {e}')
            return False

    @staticmethod
    def ensure_factor_coverage(symbol: str, reason: str = '') -> bool:
        """「因子不够 → 投回填」的组合入口，返回是否真的投了任务。

        路由侧只需 `await run_in_threadpool(EtfService.ensure_factor_coverage, sym, why)`
        一次调用（两个子步骤都是阻塞 DB / 网络操作，必须整块丢线程池，别在 async 路由
        里直接调用）。
        """
        if not EtfService.needs_factor_backfill(symbol):
            return False
        return EtfService.dispatch_factor_backfill(symbol, reason=reason or '因子历史不足')

    @staticmethod
    def delete_watchlist(user_id, symbol: str) -> bool:
        """
        从**指定用户**的监控列表移除一只 ETF。该用户没加过返回 False。

        ⚠️ 删除必须限定 user_id：否则 A 的删除动作会把 B 清单里的同一只 ETF 删掉，
        而且看起来「删成功了」，B 那边只会发现自己的自选莫名少了一行。
        """
        if user_id is None:
            raise ValueError('delete_watchlist 必须指定 user_id')
        symbol = (symbol or '').strip()
        try:
            item = db_session.query(EtfWatchlist).filter(
                EtfWatchlist.user_id == int(user_id),
                EtfWatchlist.symbol == symbol,
            ).first()
            if item:
                db_session.delete(item)
                db_session.commit()
                return True
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"delete_etf_watchlist failed for {symbol}: {e}")
            return False

    @staticmethod
    def search_etf(keyword: str, market: str = 'cn', limit: int = 50):
        """
        按代码/名称搜索全市场 ETF 目录。

        走 databull get_etf_list 的**服务端 search 过滤**（不再全量拉取后本地过滤），
        因此关键字直接交给上游匹配，支持代码/名称模糊搜索。
        返回 [{symbol, name}]，最多 limit 条。
        """
        keyword = (keyword or '').strip()
        if not keyword:
            return []

        try:
            resp = databull.get_etf_list(market=market, search=keyword)
        except Exception as e:
            logger.warning(f"get_etf_list(search={keyword}) failed: {e}")
            return []

        if resp is None:
            return []

        # 接口既可能直接返回数组，也可能返回 {code,data,...} 信封，兼容处理
        if isinstance(resp, list):
            items = resp
        else:
            items = resp.get('data') or resp.get('items') or resp.get('list') or []

        result, seen = [], set()
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get('symbol') or it.get('code') or '').strip()
            if not code or code in seen:
                continue
            seen.add(code)
            result.append({'symbol': code, 'name': str(it.get('name') or '').strip()})

        # 相关度排序：代码完全一致 > 代码前缀命中 > 代码包含 > 其余（名称命中）
        kw = keyword.lower()

        def _rank(item):
            code = item['symbol'].lower()
            if code == kw:
                return 0
            if code.startswith(kw):
                return 1
            if kw in code:
                return 2
            return 3

        result.sort(key=_rank)
        return result[:limit]
