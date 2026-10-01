"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ETF 轮动：轮动池管理（etf_rotation_pool）+ 风险调整动量信号 + 定期调仓回测。

动手前先读这段能力边界：

1. **信号一律现算，不读因子库**。轮动需要「每个调仓日、池内每只的动量」，而
   `factor_values` 里只有**被监控过的** ETF 才有历史（深度不可控），且日更分批落库
   会让某些交易日只有少数标的有值。若基于因子库取截面，用户新加进池子的 ETF 会
   「加了但排名里没有」（冷启动），某些日子甚至整个排名缺一大半。所以这里统一走
   `databull.get_etf_history` 拉日线自算 —— 数据源唯一、口径自洽、新标的立刻可用。
   代价是 N 只 × 1 次请求（上游无批量行情接口），因此池子有数量上限 + 结果缓存。
   （因子库的 ETF 覆盖仍由 job_update_factors 保证，那是给 52 周区间等其他功能用的。）

2. **排序键 = 风险调整动量** `mom / (日收益年化波动)`，不是裸动量。
   裸动量会在高波动标的上过度集中，这是 ETF 轮动最常见的翻车点。

3. **净值是「相对净值」**：起点 1.0，只反映收益率，不含申赎金额/份额。
   与组合回测（portfolio_backtest_service）同口径，绩效指标也**直接复用它的
   `_performance_metrics`**，避免两个页面各算一套、同一条曲线给出两个夏普。

4. **已知失真点**（与全站行情用法一致，前端要如实提示）：
   - 上游行情**不复权**，分红除权日价格会掉一截 → 高分红 ETF 的收益被低估；
   - 停牌/缺数据 → 前值填充（等价于不涨不跌）；未上市前的 NaN 不填充（该日不可选）；
   - 已在区间内退市的标的按最后有效价一直持有，会高估收益。

5. **不落库**：纯计算，请求即算，没有轮动任务表。
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy.exc import IntegrityError

from models import EtfRotationPool
from models.database import db_session
from utils.data_loader import databull
from utils.logger import logger

# 刻意复用组合回测的绩效口径（同一条净值曲线，两个页面必须给出同一组指标）。
# 它是模块级函数，不依赖任何 service 单例，导入不会带来循环依赖。
from service.portfolio_backtest_service import _performance_metrics

TRADING_DAYS_PER_YEAR = 252

# 池子上限：单次分析要把每只的日线都拉一遍，上游无批量接口，纯串行 N 只就是 N 次往返。
# 30 只 × 并发 12 实测约 1~2s（近 3 年区间），再大就明显拖慢首屏。
POOL_LIMIT = 30
HISTORY_FETCH_WORKERS = 12
HISTORY_FETCH_DEADLINE = 30.0   # 秒；到点用已到手的部分，缺的标的剔除并告警

# 参数默认值与边界（service 层兜底，路由层还有一层 Pydantic 校验）
DEFAULT_LOOKBACK = 20           # 动量窗口（交易日）
DEFAULT_REBALANCE_DAYS = 5      # 调仓周期（交易日），5 ≈ 周频
DEFAULT_TOP_N = 3
DEFAULT_COST = 0.0005           # 单边费率（ETF 万 3 佣金 + 冲击的粗略近似）
DEFAULT_WINDOW_DAYS = 1095      # 默认回测区间：近 3 年

LOOKBACK_RANGE = (5, 250)
REBALANCE_RANGE = (1, 60)
COST_RANGE = (0.0, 0.01)
WINDOW_RANGE = (120, 3650)      # 最短 120 自然日，避免年化指标被放大成荒谬值

# 热力图色阶截断：风险调整动量在低波动标的上会炸到 ±10 以上，会把整张图压成一片同色
HEATMAP_CLAMP = 3.0

# 按月采样热力图：3 年 = 36 个点 × 30 只，载荷可控
HEATMAP_MIN_SPAN_DAYS = 200


class EtfRotationError(ValueError):
    """入参或数据不满足轮动前提。路由层转成 400，不要把栈打给前端。"""


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _clamp_float(value, low: float, high: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(low, min(high, parsed))


def _round_list(values: Sequence[float], digits: int = 6) -> List[Optional[float]]:
    """把 numpy/pandas 数值序列转成 JSON 友好的 list，并对 nan/inf 做 None 化。

    ⚠️ `round(float('nan'))` 不报错，但 json 序列化会抛 `ValueError: Out of range float
    values are not JSON compliant` —— 整条接口 500。净值/回撤理论上不该有 nan，
    但取数补丁一旦有洞，这里就是最后一道防线。
    """
    out: List[Optional[float]] = []
    for v in values:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(round(fv, digits) if math.isfinite(fv) else None)
    return out


class EtfRotationService:
    """轮动池的持久化 + 轮动计算。"""

    # ==================== 池管理（与 EtfService 同约定：user_id 必须全限定） ====================

    @staticmethod
    def list_pool(user_id) -> List[EtfRotationPool]:
        """读取某用户的轮动池（按加入时间倒序）。

        ⚠️ user_id 必传：用户私有数据没有「不传就取全部」的合理语义，静默返回全部
        用户的池子正是多用户下最危险的默认行为。任务侧要并集请用 `list_all_pool_symbols()`。
        """
        if user_id is None:
            raise ValueError('list_pool 必须指定 user_id')
        try:
            return db_session.query(EtfRotationPool).filter(
                EtfRotationPool.user_id == int(user_id)
            ).order_by(EtfRotationPool.created_at.desc()).all()
        except Exception as e:
            logger.error(f'list_etf_rotation_pool failed: {e}')
            return []

    @staticmethod
    def list_all_pool_symbols() -> List[str]:
        """全用户轮动池的去重并集，给因子日更任务用（因子是按标的算的公共数据）。"""
        try:
            rows = db_session.query(EtfRotationPool.symbol).distinct().all()
            return sorted({r[0] for r in rows if r[0]})
        except Exception as e:
            logger.error(f'list_all_etf_rotation_symbols failed: {e}')
            return []

    @staticmethod
    def add_to_pool(user_id, symbol: str, name: str = None) -> EtfRotationPool:
        """
        把一只 ETF 加入某用户的轮动池。

        - user_id / symbol 为空抛 ValueError；
        - 该用户已加过则直接返回已有记录（幂等）；
        - 超出 POOL_LIMIT 抛 EtfRotationError（宁可报错也不要建一个拉不动的池子）；
        - name 未传时从 databull.get_etf_info 兜底；
        - 并发撞唯一约束 → 回滚后回查已有记录。
        """
        if user_id is None:
            raise ValueError('add_to_pool 必须指定 user_id')
        user_id = int(user_id)

        symbol = (symbol or '').strip().split('.')[0]
        if not symbol:
            raise ValueError('ETF 代码不能为空')

        # ⚠️ 幂等查询必须限定 user_id：只按 symbol 查会把别的用户已加的记录当成本用户已有，
        # 用户以为加上了，实际自己的池子里没有。
        existing = db_session.query(EtfRotationPool).filter(
            EtfRotationPool.user_id == user_id,
            EtfRotationPool.symbol == symbol,
        ).first()
        if existing:
            return existing

        current = db_session.query(EtfRotationPool).filter(
            EtfRotationPool.user_id == user_id
        ).count()
        if current >= POOL_LIMIT:
            raise EtfRotationError(
                f'轮动池最多 {POOL_LIMIT} 只 ETF（每只都要单独取日线，再多会明显拖慢分析），'
                f'请先移除部分标的'
            )

        if not name:
            try:
                info = databull.get_etf_info(symbol) or {}
                name = info.get('name') if isinstance(info, dict) else None
            except Exception as e:
                logger.warning(f'get_etf_info(name) failed for {symbol}: {e}')

        item = EtfRotationPool(user_id=user_id, symbol=symbol, name=name)
        try:
            db_session.add(item)
            db_session.commit()
            db_session.refresh(item)
            return item
        except IntegrityError:
            db_session.rollback()
            logger.warning(f'EtfRotationPool duplicate on insert: user={user_id} {symbol}')
            return db_session.query(EtfRotationPool).filter(
                EtfRotationPool.user_id == user_id,
                EtfRotationPool.symbol == symbol,
            ).first()
        except Exception as e:
            db_session.rollback()
            logger.error(f'add_etf_rotation_pool failed for {symbol}: {e}')
            raise

    @staticmethod
    def delete_from_pool(user_id, symbol: str) -> bool:
        """从某用户的轮动池移除一只。没加过返回 False。

        ⚠️ 删除必须限定 user_id，否则 A 的删除会把 B 池子里的同一只删掉。
        """
        if user_id is None:
            raise ValueError('delete_from_pool 必须指定 user_id')
        symbol = (symbol or '').strip().split('.')[0]
        try:
            item = db_session.query(EtfRotationPool).filter(
                EtfRotationPool.user_id == int(user_id),
                EtfRotationPool.symbol == symbol,
            ).first()
            if not item:
                return False
            db_session.delete(item)
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f'delete_etf_rotation_pool failed for {symbol}: {e}')
            return False

    # ==================== 行情取数 ====================

    @staticmethod
    def _fetch_closes(symbols: List[str], start_date: str, end_date: str):
        """并发拉一组 ETF 的收盘价，返回 ({symbol: Series}, [失败/无数据的 symbol])。

        并发模式与 routes/etf.py::_fetch_latest_prices 一致，三个要点都不能省：
        1. 上游没有批量行情接口，逐只请求 → 必须并发；
        2. `as_completed(timeout=)` 到点抛 TimeoutError，此时**保留已到手的序列**继续算，
           而不是整块失败（一只卡住不该让整页打不开）；
        3. 退出必须 `shutdown(wait=False)` —— 用 with 会等所有在途请求结束，
           一次网络抖动就能把接口拖到分钟级。
        """
        result: Dict[str, pd.Series] = {}
        failed: List[str] = []
        if not symbols:
            return result, failed

        def _one(code: str):
            try:
                frame = databull.get_etf_history(code, start_date, end_date)
            except Exception as e:
                logger.warning(f'get_etf_history failed for {code}: {e}')
                return code, None
            if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
                return code, None
            if 'close' not in frame.columns:
                return code, None
            series = pd.to_numeric(frame['close'], errors='coerce').astype('float64')
            # ⚠️ 上游 SDK 返回的 DataFrame **index 已经是日期**（name='date'，datetime64），
            # 同时另有一列毫秒 timestamp。不要拿 timestamp 列当索引 —— 与
            # portfolio_backtest_service._fetch_close_series 保持一致。
            series.index = pd.to_datetime(frame.index)
            series = series[series > 0]          # 0 价是脏数据，否则 pct_change 会除零/爆表
            series = series[~series.index.duplicated(keep='last')].sort_index()
            if series.empty:
                return code, None
            series.name = code
            return code, series

        executor = ThreadPoolExecutor(max_workers=HISTORY_FETCH_WORKERS)
        try:
            futures = [executor.submit(_one, c) for c in symbols]
            try:
                for fut in as_completed(futures, timeout=HISTORY_FETCH_DEADLINE):
                    code, series = fut.result()
                    if series is None:
                        failed.append(code)
                    else:
                        result[code] = series
            except TimeoutError:
                done = set(result) | set(failed)
                missing = [c for c in symbols if c not in done]
                failed.extend(missing)
                logger.warning(
                    f'etf history fetch timed out, got {len(result)}/{len(symbols)}, '
                    f'missing={missing}'
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # 同一只可能既进了 result 又进了 failed（不会，但排序保证返回稳定）
        failed = sorted(set(failed))
        return result, failed

    # ==================== 轮动计算 ====================

    @classmethod
    def analyze(
        cls,
        user_id,
        lookback: Any = None,
        rebalance_days: Any = None,
        top_n: Any = None,
        abs_filter: Any = None,
        cost: Any = None,
        window_days: Any = None,
    ) -> Dict[str, Any]:
        """跑一次轮动分析：当前排名 + 净值回测 + 持仓演变 + 动量热力图。

        抛 EtfRotationError 表示前提不满足（池子太小 / 数据不足），路由层转 400。
        """
        lookback = _clamp_int(lookback, *LOOKBACK_RANGE, default=DEFAULT_LOOKBACK)
        rebalance_days = _clamp_int(rebalance_days, *REBALANCE_RANGE, default=DEFAULT_REBALANCE_DAYS)
        cost = _clamp_float(cost, *COST_RANGE, default=DEFAULT_COST)
        window_days = _clamp_int(window_days, *WINDOW_RANGE, default=DEFAULT_WINDOW_DAYS)
        # 前端传来的可能是字符串 'false'，不能直接用 bool()（bool('false') is True）
        if abs_filter is None:
            abs_filter = True
        elif isinstance(abs_filter, str):
            abs_filter = abs_filter.strip().lower() not in ('false', '0', 'no', '')
        else:
            abs_filter = bool(abs_filter)

        pool = cls.list_pool(user_id)
        if len(pool) < 2:
            raise EtfRotationError(
                '轮动分析至少需要 2 只 ETF（当前 %d 只），请先添加' % len(pool)
            )

        name_map = {row.symbol: (row.name or row.symbol) for row in pool}
        symbols = [row.symbol for row in pool]
        top_n = _clamp_int(top_n, 1, len(symbols), default=min(DEFAULT_TOP_N, len(symbols)))

        end_compact = pd.Timestamp.now().normalize()
        start_compact = end_compact - pd.Timedelta(days=window_days)
        # 信号需要预热：回测起点之前必须已有 lookback 个交易日的历史，
        # 否则第一个调仓日算不出动量，回测会被整体推迟。
        fetch_start = (start_compact - pd.Timedelta(days=lookback * 2 + 30)).strftime('%Y-%m-%d')

        closes_map, failed = cls._fetch_closes(symbols, fetch_start, end_compact.strftime('%Y-%m-%d'))
        warnings: List[str] = []
        if failed:
            warnings.append(
                f'有 {len(failed)} 只没取到行情已剔除：{", ".join(failed)}'
            )
        if len(closes_map) < 2:
            raise EtfRotationError(
                '轮动池里可取到行情的 ETF 不足 2 只，无法进行轮动分析'
            )

        # 按池序排列，保证列顺序稳定（否则热力图/持仓的行序会随返回顺序抖动）
        usable = [s for s in symbols if s in closes_map]
        prices = pd.DataFrame({s: closes_map[s] for s in usable})
        prices = prices.sort_index()
        prices = prices[~prices.index.duplicated(keep='last')]

        # 停牌 → 前值填充（等价于不涨不跌）。⚠️ 未上市前的前导 NaN 不填，保留为不可选。
        prices = prices.ffill()
        prices = prices.dropna(how='all')
        if len(prices) < lookback + 2:
            raise EtfRotationError(
                f'有效交易日不足（{len(prices)} 天，至少需要 {lookback + 2} 天），'
                f'请缩短动量窗口或更换标的'
            )

        ret = prices.pct_change()
        # 动量为**小数**（0.03 = 3%），与因子库 mom_* 口径一致
        mom = prices / prices.shift(lookback) - 1.0
        vol = ret.rolling(lookback).std() * math.sqrt(TRADING_DAYS_PER_YEAR)
        # 风险调整动量：低波动标的不会被裸动量过度抬高
        score = mom / vol.replace(0, np.nan)

        dates = prices.index
        # 回测起点：第一根「至少有一只算得出 score」的 K 线
        valid_first = score.dropna(how='all')
        if valid_first.empty:
            raise EtfRotationError('区间内没有可用的动量信号，请拉长区间或缩短动量窗口')
        start_i = int(dates.get_loc(valid_first.index[0]))
        if dates[start_i] > start_compact:
            warnings.append(
                f'受动量窗口预热影响，回测实际起点为 {dates[start_i].strftime("%Y-%m-%d")}'
                f'（请求起点 {start_compact.strftime("%Y-%m-%d")}）'
            )

        bt_dates = dates[start_i:]
        rebalance_set = _rebalance_positions(len(dates), start_i, rebalance_days)
        weights = pd.Series(0.0, index=usable)
        nav_values: List[float] = []
        holding_log: List[Dict[str, Any]] = []
        nav = 1.0
        rebalance_count = 0

        for i in range(start_i, len(dates)):
            # 先按「上一交易日收盘已确定的权重」推进当日收益，再做当日收盘的调仓
            # —— 顺序反了会让净值曲线整体右移一天（净值序列与日期错位一格，
            # 起点当天就吃到了次日收益，图上看起来是「回测起点提前了一天」）。
            if i > start_i:
                day_ret = float((weights * ret.iloc[i].fillna(0.0)).sum())
                nav *= (1.0 + day_ret)

            if i in rebalance_set:
                row = score.iloc[i].dropna()
                if abs_filter:
                    # 绝对动量过滤：动量转负的不纳入；全池皆负则空仓（净值走平，不下行）
                    keep = [s for s in row.index if pd.notna(mom.iloc[i].get(s)) and mom.iloc[i][s] > 0]
                    row = row[keep]
                picked = list(row.nlargest(top_n).index)
                new_weights = pd.Series(0.0, index=usable)
                if picked:
                    new_weights[picked] = 1.0 / len(picked)
                # 换手成本在调仓当日收盘扣除：|Δw| 之和 × 单边费率。
                # 首次建仓的 turnover = 1.0（从空仓到满仓），符合实际。
                turnover = float((new_weights - weights).abs().sum())
                nav *= (1.0 - turnover * cost)
                weights = new_weights
                rebalance_count += 1
                holding_log.append({
                    'date': dates[i].strftime('%Y-%m-%d'),
                    'symbols': picked,
                    'weights': {s: round(1.0 / len(picked), 6) for s in picked} if picked else {},
                })

            nav_values.append(nav)

        equity = pd.Series(nav_values, index=bt_dates, dtype='float64')

        # ---- 基准：池内等权买入持有（一次性等权，不调仓） ----
        # ⚠️ `.loc[bt_dates[0]:]` 用**标量**起点：直接写 `bt_dates:` 会把 DatetimeIndex
        # 当成切片起点，pandas 抛 "cannot do slice indexing on DatetimeIndex"。
        bench_prices = prices.loc[bt_dates[0]:, usable].ffill()
        bench_valid = bench_prices.iloc[0].dropna().index
        if len(bench_valid) == 0:
            raise EtfRotationError('回测起点没有可用的基准净值，无法计算等权基准')
        normalized = bench_prices[bench_valid] / bench_prices[bench_valid].iloc[0]
        # 起点前没数据的标的在其后有值时会被 ffill 成常量首值（收益 0），这不合理，
        # 因此基准只取「回测起点当天就有价」的标的，与策略的候选集口径一致。
        bench_equity = normalized.mean(axis=1)
        bench_equity = bench_equity.reindex(equity.index).ffill()
        drawdown = equity / equity.cummax() - 1.0
        bench_drawdown = bench_equity / bench_equity.cummax() - 1.0

        metrics = _performance_metrics(equity)
        try:
            bench_metrics = _performance_metrics(bench_equity)
        except Exception as e:
            logger.warning(f'benchmark metrics failed: {e}')
            bench_metrics = None

        if len(equity) < 30:
            warnings.append('有效交易日不足 30 天，年化收益/夏普的参考意义有限')
        warnings.append('行情为不复权价，分红除权会造成收益低估')

        # ---- 当前排名（最后一个交易日的截面） ----
        last_i = len(dates) - 1
        last_score = score.iloc[last_i]
        last_mom = mom.iloc[last_i]
        last_vol = vol.iloc[last_i]
        ordered = last_score.dropna().sort_values(ascending=False)
        held = set(holding_log[-1]['symbols']) if holding_log else set()
        ranking = []
        for rank, (sym, sc) in enumerate(ordered.items(), start=1):
            ranking.append({
                'symbol': sym,
                'name': name_map.get(sym, sym),
                'score': round(float(sc), 4),
                'mom': round(float(last_mom[sym]), 4) if pd.notna(last_mom.get(sym)) else None,
                'vol': round(float(last_vol[sym]), 4) if pd.notna(last_vol.get(sym)) else None,
                'rank': rank,
                'held': sym in held,
                # 未进排名的标的通常是数据不足（停牌/停牌前无足够历史）
                'missing': False,
            })
        for sym in usable:
            if sym not in ordered.index:
                ranking.append({
                    'symbol': sym, 'name': name_map.get(sym, sym), 'score': None,
                    'mom': None, 'vol': None, 'rank': None, 'held': False, 'missing': True,
                })

        # ---- 动量热力图（按月采样，行=标的、列=日期） ----
        # ⚠️ 行序统一用**当前排名顺序**：热力图与持仓时间带都吃这个顺序，
        # 否则三处（排名表 / 热力图 / 时间带）各按各的顺序排，同一只 ETF 在图上的
        # 上下位置对不上，用户得来回找。ranking 里已把无数据的标的排在最后。
        ordered_symbols = [it['symbol'] for it in ranking]
        heatmap = cls._build_heatmap(score, ordered_symbols, name_map)

        logger.info(
            f'[etf_rotation] user={user_id} {len(usable)} 只 {lookback}日动量 '
            f'{"周频" if rebalance_days == 5 else f"{rebalance_days}日"}调仓 Top{top_n} '
            f'abs={"on" if abs_filter else "off"} | 调仓 {rebalance_count} 次 | '
            f'总收益 {metrics["total_return"] * 100:.2f}% | 最大回撤 {metrics["max_drawdown"] * 100:.2f}%'
        )

        return {
            'meta': {
                'strategy': 'risk_adjusted_momentum_rotation',
                'strategy_label': '风险调整动量轮动',
                'pool_size': len(symbols),
                # 顺序 = 当前排名顺序（供前端持仓时间带与热力图对齐行序），集合仍等于可取到行情的标的
                'usable': ordered_symbols,
                'top_n': top_n,
                'lookback': lookback,
                'rebalance_days': rebalance_days,
                'abs_filter': abs_filter,
                'cost': cost,
                'window_days': window_days,
                'start_date': _to_display_date(equity.index[0]),
                'end_date': _to_display_date(equity.index[-1]),
                'rebalance_count': rebalance_count,
                'benchmark_name': '池内等权持有',
            },
            'series': {
                'dates': [_to_display_date(d) for d in equity.index],
                'equity': _round_list(equity.values),
                'drawdown': _round_list(drawdown.values),
                'benchmark_equity': _round_list(bench_equity.values),
                'benchmark_drawdown': _round_list(bench_drawdown.values),
            },
            'metrics': metrics,
            'benchmark_metrics': bench_metrics,
            'ranking': ranking,
            'holdings': holding_log,
            'heatmap': heatmap,
            'warnings': warnings,
        }

    @staticmethod
    def _build_heatmap(score: pd.DataFrame, usable: List[str], name_map: Dict[str, str]) -> Dict[str, Any]:
        """风险调整动量的时间 × 标的热力图数据（按月取每月最后一个交易日）。

        区间太短（< 200 天）时按月采样只剩几个点、什么都看不出来，此时保留全部交易日。
        """
        if score.empty:
            return {'symbols': [], 'names': [], 'dates': [], 'values': []}

        sampled = score
        span_days = (score.index[-1] - score.index[0]).days
        if span_days >= HEATMAP_MIN_SPAN_DAYS:
            monthly = score.groupby([score.index.year, score.index.month]).tail(1)
            if len(monthly) >= 2:
                sampled = monthly

        # 截断极端值：低波动标的的 score 可能到 ±10，会把色阶压成一片同色。
        # 这里只截断**展示用**的副本，不影响排名与回测（那两处用的是原始 score）。
        clamped = sampled.clip(lower=-HEATMAP_CLAMP, upper=HEATMAP_CLAMP)

        values = []
        for sym in usable:
            row = clamped[sym] if sym in clamped.columns else pd.Series(dtype='float64')
            values.append([
                round(float(v), 4) if pd.notna(v) else None for v in row.reindex(sampled.index)
            ])

        return {
            'symbols': list(usable),
            'names': [name_map.get(s, s) for s in usable],
            'dates': [_to_display_date(d) for d in sampled.index],
            'values': values,
            'clamp': HEATMAP_CLAMP,
        }


def _rebalance_positions(total: int, start_i: int, step: int) -> set:
    """所有调仓日的位置集合（含起点当天，即建仓日）。"""
    return set(range(start_i, total, max(1, step)))


def _to_display_date(value) -> str:
    """统一成 YYYY-MM-DD 字符串（与 portfolio_backtest_service 的展示口径一致）。"""
    try:
        return pd.Timestamp(value).strftime('%Y-%m-%d')
    except Exception:
        return str(value)
