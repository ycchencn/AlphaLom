"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

组合回测（等权 · 买入持有）

第一阶段的能力边界，动手前请先读这段，避免按「完整策略回测」的预期使用：

1. **只有买入持有**：起点一次性等权建仓，区间内不再调整。没有再平衡、没有信号、没有择时。
2. **等权是唯一权重**：每只 1/N。自定义权重留给后续阶段。
3. **计算的是「相对净值」**：`init_cash` 只影响展示用的金额换算，不影响收益率曲线。
   组合净值 ≡ mean(P_i(t) / P_i(起点))，因此买多少份、手续费、滑点都不参与计算。
4. **不落库**：纯计算，请求即算，没有回测任务表。

已知的失真点（不是 bug，是上游数据的限制，前端要如实提示）：

- ⚠️ **上游行情无复权**。分红除权日价格会「凭空」掉一截，长期持有高分红标的的收益会被低估。
  这与项目里其它用到历史行情的地方（52 周区间、因子计算）是同一个已知限制。
- **停牌 → 前值填充**：当日无行情的标的沿用上一有效收盘价，等价于「停牌期间不涨不跌」。
- **区间内退市/长期停牌 → 按最后有效价一直持有**，不会按 0 清算，会高估收益。
- 日期对齐用**并集**：不同标的的交易日不完全一致（实测 510300 比 600519 少 1 天），
  取「所有标的都有数据的第一个交易日」作为共同起点；起点之后缺失的用前值填充。

年化口径：收益年化按**自然日跨度 / 365.25**，波动率与夏普按 **252 交易日**。无风险利率取 0。
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from databull import DataBullError
from utils.common import get_date_by_n, get_today, is_etf
from utils.data_loader import databull
from utils.logger import logger

# 一次回测最多几只标的。实测单只取数约 0.13s（2.7 年区间），串行 30 只约 4s；
# 上限主要是防止 URL/上游调用被滥用，不是为了性能。
MAX_SYMBOLS = 30

# 可选基准清单。
# ⚠️ 这里是前后端共用的**唯一来源**（前端下拉从 /portfolio_backtest_benchmarks 拉），
# 不要在前端再写一份 code→name 映射 —— 两处各写一份必然漂移，
# 早前「沪深300 卡片长期不渲染」就是前端有名字而后端不返回导致的。
# 全部在线上实测有日线数据（2026-09 验证）；中证2000(932000) 实测返回空，故未收录。
BENCHMARK_OPTIONS = (
    {'code': '000300', 'name': '沪深300'},
    {'code': '000001', 'name': '上证指数'},
    {'code': '399001', 'name': '深证成指'},
    {'code': '399006', 'name': '创业板指'},
    {'code': '000905', 'name': '中证500'},
    {'code': '000852', 'name': '中证1000'},
    {'code': '000016', 'name': '上证50'},
    {'code': '000688', 'name': '科创50'},
)

_BENCHMARK_NAME_MAP = {item['code']: item['name'] for item in BENCHMARK_OPTIONS}

DEFAULT_BENCHMARK = '000300'
DEFAULT_BENCHMARK_NAME = _BENCHMARK_NAME_MAP[DEFAULT_BENCHMARK]

# 默认回测区间：近 1 年（与 /stock_history 的默认窗口保持一致）
DEFAULT_WINDOW_DAYS = 365

TRADING_DAYS_PER_YEAR = 252


class BacktestError(ValueError):
    """入参或数据不满足回测前提。路由层转成 400 返回，不要把栈打给前端。"""


def _to_compact_date(value: str, field: str) -> str:
    """把 YYYY-MM-DD / YYYYMMDD / datetime 统一成 YYYYMMDD（上游只认这个）。"""
    if value is None:
        raise BacktestError(f'{field} 不能为空')
    text = str(value).strip()
    if not text:
        raise BacktestError(f'{field} 不能为空')
    text = text.replace('-', '').replace('/', '')
    if len(text) != 8 or not text.isdigit():
        raise BacktestError(f'{field} 格式应为 YYYYMMDD 或 YYYY-MM-DD，收到：{value}')
    return text


def _to_display_date(value) -> str:
    """统一输出 YYYY-MM-DD，前端不用再猜格式。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def _normalize_symbols(symbols) -> List[str]:
    """把逗号/空格分隔的字符串或列表统一成去重后的代码列表（保持用户输入顺序）。

    ⚠️ 保留顺序是有意义的：前端按顺序展示持仓明细，用户按输入顺序读。
    """
    # ⚠️ 不要在这里 `return []` 了事：「没有标的」是调用方的入参错误，
    # 静默返回空列表会让它一路走到「所选标的在区间内都没有行情数据」那个报错上，
    # 错误信息指向数据而不是入参，排查要绕一大圈。
    if symbols is None:
        raise BacktestError('请至少选择一个标的')
    if isinstance(symbols, str):
        raw = symbols.replace('，', ',').replace(';', ',').split(',')
    elif isinstance(symbols, (list, tuple, set)):
        raw = []
        for item in symbols:
            if item is None:
                continue
            raw.extend(str(item).replace('，', ',').split(','))
    else:
        raise BacktestError('symbols 应为逗号分隔的字符串或数组')

    result: List[str] = []
    for item in raw:
        code = str(item).strip().upper()
        if not code:
            continue
        # 容忍带交易所后缀的写法（600519.SH / 000300.SZ），上游同样会自动剥离
        code = code.split('.')[0]
        if len(code) != 6 or not code.isdigit():
            raise BacktestError(f'标的代码应为 6 位数字，收到：{item}')
        if code not in result:
            result.append(code)

    if not result:
        raise BacktestError('请至少选择一个标的')
    if len(result) > MAX_SYMBOLS:
        raise BacktestError(f'一次最多回测 {MAX_SYMBOLS} 个标的，当前 {len(result)} 个')
    return result


def _fetch_close_series(symbol: str, start_date: str, end_date: str) -> Optional[pd.Series]:
    """取单只标的的收盘价序列（按日期升序）。取不到数据返回 None（由调用方计入 skipped）。

    ⚠️ 个股和 ETF 走的是两个不同端点，`is_etf` 是唯一判据（与全项目一致）。
    ⚠️ 两者的第 4 个位置参数含义不同：get_stock_history 是 period、get_etf_history 是 market。
    这里全部用关键字/固定值调用，不要图省事传位置参数。
    """
    if is_etf(symbol):
        frame = databull.get_etf_history(symbol, start_date, end_date)
    else:
        frame = databull.get_stock_history(symbol, start_date, end_date, period='d')

    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    if 'close' not in frame.columns:
        return None

    series = pd.to_numeric(frame['close'], errors='coerce').astype('float64')
    series.index = pd.to_datetime(frame.index)
    series = series[series > 0]  # 0 价是脏数据，按缺失处理，否则归一化时会除零
    series = series[~series.index.duplicated(keep='last')].sort_index()
    if series.empty:
        return None
    series.name = symbol
    return series


def _max_drawdown_detail(equity: pd.Series) -> Dict[str, object]:
    """最大回撤及其起止：峰值日 → 谷底日 → 修复日（未修复则为 None）。"""
    if equity.empty:
        return {'value': 0.0, 'start': None, 'end': None, 'recovery': None}

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    trough_ts = drawdown.idxmin()
    value = float(drawdown.loc[trough_ts])

    peak_ts = equity.loc[:trough_ts].idxmax()
    after_trough = equity.loc[trough_ts:]
    recovered = after_trough[after_trough >= float(equity.loc[peak_ts])]
    recovery_ts = recovered.index[0] if len(recovered) else None

    return {
        'value': value,
        'start': _to_display_date(peak_ts),
        'end': _to_display_date(trough_ts),
        'recovery': _to_display_date(recovery_ts) if recovery_ts is not None else None,
    }


def _performance_metrics(equity: pd.Series) -> Dict[str, object]:
    """由净值序列算绩效指标。equity 的起点不必是 1.0，函数内部自己归一。"""
    if equity is None or len(equity) < 2:
        raise BacktestError('有效交易日不足 2 天，无法计算绩效指标')

    equity = equity.astype('float64')
    first, last = float(equity.iloc[0]), float(equity.iloc[-1])
    total_return = last / first - 1.0

    span_days = (equity.index[-1] - equity.index[0]).days
    years = span_days / 365.25 if span_days > 0 else 0.0
    # 区间过短时（如 10 天）年化会被放大成荒谬的数字，这里照实算但前端要提示；
    # 单点/不足一天直接不年化（years=0 → annual_return=0）。
    annual_return = (last / first) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    daily = equity.pct_change().dropna()
    daily = daily[daily.notna() & ~daily.isin([float('inf'), float('-inf')])]

    volatility = float(daily.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily) > 1 else 0.0
    # 无风险利率取 0：夏普 = 年化日收益均值 / 年化波动
    sharpe = float(daily.mean() * TRADING_DAYS_PER_YEAR / volatility) if volatility > 0 else 0.0

    drawdown = _max_drawdown_detail(equity)
    max_dd = float(drawdown['value'])
    calmar = float(annual_return / abs(max_dd)) if max_dd < 0 else 0.0

    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'volatility': volatility,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'max_drawdown_start': drawdown['start'],
        'max_drawdown_end': drawdown['end'],
        'max_drawdown_recovery': drawdown['recovery'],
        'calmar': calmar,
        'win_rate': float((daily > 0).mean()) if len(daily) else 0.0,
        'best_day': float(daily.max()) if len(daily) else 0.0,
        'worst_day': float(daily.min()) if len(daily) else 0.0,
        'trading_days': int(len(equity)),
        'span_days': int(span_days),
    }


def _round_series(series: pd.Series, digits: int = 6) -> List[float]:
    return [round(float(v), digits) for v in series.tolist()]


class PortfolioBacktestService:
    """等权买入持有组合回测。全部是纯计算 + 上游取数，不读写数据库。"""

    @staticmethod
    def run(
        symbols,
        start_date: str = None,
        end_date: str = None,
        init_cash: float = 1_000_000.0,
        benchmark: str = DEFAULT_BENCHMARK,
    ) -> Dict[str, object]:
        """执行一次组合回测。

        :param symbols: 标的代码，逗号分隔字符串或数组（股票与 ETF 可混选）
        :param start_date: 起始日 YYYYMMDD / YYYY-MM-DD，留空取近 1 年
        :param end_date: 结束日 YYYYMMDD / YYYY-MM-DD，留空取今天
        :param init_cash: 初始资金，仅用于金额换算（不影响收益率）
        :param benchmark: 基准指数裸码，传空字符串则不取基准
        """
        codes = _normalize_symbols(symbols)

        end_compact = _to_compact_date(end_date, '结束日期') if end_date else get_today()
        start_compact = (
            _to_compact_date(start_date, '起始日期') if start_date else get_date_by_n(-DEFAULT_WINDOW_DAYS)
        )
        if start_compact >= end_compact:
            raise BacktestError('起始日期必须早于结束日期')

        try:
            init_cash = float(init_cash)
        except (TypeError, ValueError):
            raise BacktestError('初始资金必须是数字')
        if init_cash <= 0:
            raise BacktestError('初始资金必须大于 0')

        # ---- 1. 逐只取收盘价 ----
        skipped: List[Dict[str, str]] = []
        closes: Dict[str, pd.Series] = {}
        for code in codes:
            try:
                series = _fetch_close_series(code, start_compact, end_compact)
            except DataBullError as e:
                # 新 SDK 失败即抛异常（旧客户端是 print 后返回 None）：
                # 单只失败不能拖垮整次回测，记进 skipped 让前端如实展示。
                logger.warning(f'[portfolio_backtest] 取数失败 {code}: {e}')
                skipped.append({'symbol': code, 'reason': f'行情接口报错（{getattr(e, "status", "")}）'})
                continue
            except Exception as e:  # noqa: BLE001 - 上游形态多变，兜底成「跳过该标的」
                logger.warning(f'[portfolio_backtest] 取数异常 {code}: {e}')
                skipped.append({'symbol': code, 'reason': '行情取数异常'})
                continue

            if series is None:
                skipped.append({'symbol': code, 'reason': '区间内无行情数据'})
                continue
            closes[code] = series

        if not closes:
            raise BacktestError('所选标的在区间内都没有行情数据，请调整标的或日期区间')

        # ---- 2. 对齐交易日 ----
        # 列 = 标的，索引 = 交易日并集。ffill 处理停牌；共同起点之前必然全为 NaN，
        # 因此「第一行全部有效」就是所有标的都能建仓的第一天。
        prices = pd.DataFrame(closes).sort_index().ffill()
        valid_rows = prices.notna().all(axis=1)
        if not valid_rows.any():
            raise BacktestError('所选标的在区间内没有共同交易日（可能长期停牌或退市），无法构建组合')
        start_ts = prices.index[valid_rows][0]
        prices = prices.loc[start_ts:].ffill().dropna()

        if len(prices) < 2:
            raise BacktestError('共同交易日不足 2 天，无法回测')

        usable = list(prices.columns)

        # ---- 3. 等权买入持有 ----
        # 组合净值 = mean(P_i(t) / P_i(起点))，起点恒为 1.0。
        normalized = prices / prices.iloc[0]
        equity = normalized.mean(axis=1)
        weight = 1.0 / len(usable)

        # 回撤序列（供水下图）：相对历史高点的跌幅，恒 <= 0
        drawdown = equity / equity.cummax() - 1.0

        warnings: List[str] = []
        if skipped:
            warnings.append(
                f"有 {len(skipped)} 个标的没有可用行情已剔除，实际按 {len(usable)} 只等权计算"
                f"（每只 {weight * 100:.1f}%）"
            )
        if len(prices) < 30:
            warnings.append('有效交易日不足 30 天，年化收益/夏普等指标的参考意义有限')
        warnings.append('行情为不复权价，分红除权会造成收益低估')

        # ---- 4. 基准 ----
        benchmark_payload = None
        benchmark_code = (benchmark or '').strip().split('.')[0]
        if benchmark_code:
            benchmark_payload = PortfolioBacktestService._benchmark_payload(
                benchmark_code, equity, start_compact, end_compact, warnings
            )

        # ---- 5. 持仓明细 ----
        # 等权买入持有下，单只贡献 = 权重 × 该只收益率，各项之和恰好等于组合总收益。
        holdings = []
        for code in usable:
            symbol_return = float(normalized[code].iloc[-1]) - 1.0
            holdings.append({
                'symbol': code,
                # ⚠️ 权重**不要** round：界面上写的「贡献 = 权重 × 区间收益」要精确成立，
                # round 到 6 位后 1/3 与 0.333333 的差会让等式对不上（前端自己按需格式化）
                'weight': weight,
                'total_return': symbol_return,
                'contribution': weight * symbol_return,
                'asset_type': 'etf' if is_etf(code) else 'stock',
            })

        metrics = _performance_metrics(equity)

        logger.info(
            f"[portfolio_backtest] {len(usable)} 只 等权买入持有 "
            f"{_to_display_date(prices.index[0])} ~ {_to_display_date(prices.index[-1])} | "
            f"总收益 {metrics['total_return'] * 100:.2f}% | 最大回撤 {metrics['max_drawdown'] * 100:.2f}%"
        )

        return {
            'meta': {
                'strategy': 'equal_weight_buy_and_hold',
                'strategy_label': '等权买入持有',
                'symbols': usable,
                'weight_per_symbol': weight,  # 同上：不 round，保持 Σweight == 1 精确成立
                'init_cash': init_cash,
                'start_date': _to_display_date(prices.index[0]),
                'end_date': _to_display_date(prices.index[-1]),
                'requested_start_date': _to_display_date(pd.Timestamp(start_compact)),
                'requested_end_date': _to_display_date(pd.Timestamp(end_compact)),
                'skipped_start_days': int(
                    (prices.index[0] - pd.Timestamp(start_compact)).days
                ),
                'benchmark': benchmark_code or None,
                'benchmark_name': _BENCHMARK_NAME_MAP.get(benchmark_code, benchmark_code) if benchmark_code else None,
            },
            'series': {
                'dates': [_to_display_date(d) for d in prices.index],
                'equity': _round_series(equity),
                'drawdown': _round_series(drawdown),
                'benchmark_equity': _round_series(benchmark_payload['equity']) if benchmark_payload else [],
                'benchmark_drawdown': _round_series(benchmark_payload['drawdown']) if benchmark_payload else [],
            },
            'metrics': metrics,
            'benchmark_metrics': benchmark_payload['metrics'] if benchmark_payload else None,
            'holdings': holdings,
            'skipped': skipped,
            'warnings': warnings,
        }

    # ------------------------------------------------------------------ 内部工具

    @staticmethod
    def _benchmark_payload(
        benchmark_code: str,
        equity: pd.Series,
        start_compact: str,
        end_compact: str,
        warnings: List[str],
    ) -> Optional[Dict[str, object]]:
        """取基准指数并对其到组合的交易日。失败不影响主结果，只加一条 warning。"""
        try:
            frame = databull.get_index_history(benchmark_code, start_compact, end_compact)
        except DataBullError as e:
            logger.warning(f'[portfolio_backtest] 基准 {benchmark_code} 取数失败: {e}')
            warnings.append(f'基准指数 {benchmark_code} 取数失败，本次不展示基准对比')
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f'[portfolio_backtest] 基准 {benchmark_code} 取数异常: {e}')
            warnings.append(f'基准指数 {benchmark_code} 取数异常，本次不展示基准对比')
            return None

        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty or 'close' not in frame.columns:
            warnings.append(f'基准指数 {benchmark_code} 无数据，本次不展示基准对比')
            return None

        try:
            close = pd.to_numeric(frame['close'], errors='coerce').astype('float64')
            close.index = pd.to_datetime(frame.index)
            # 基准的交易日与组合不一定完全一致，按组合的日期轴重采样后前值填充，
            # 保证两条曲线共用同一个横轴、起点同为 1.0。
            aligned = close[~close.index.duplicated(keep="last")].sort_index().reindex(equity.index).ffill()
            if aligned.isna().any() or len(aligned) < 2:
                warnings.append(f'基准指数 {benchmark_code} 与组合的交易日对不齐，本次不展示基准对比')
                return None
            bench_equity = aligned / float(aligned.iloc[0])
        except Exception as e:  # noqa: BLE001
            logger.warning(f'[portfolio_backtest] 基准 {benchmark_code} 对齐失败: {e}')
            warnings.append(f'基准指数 {benchmark_code} 对齐失败，本次不展示基准对比')
            return None

        return {
            'equity': bench_equity,
            'drawdown': bench_equity / bench_equity.cummax() - 1.0,
            'metrics': _performance_metrics(bench_equity),
        }
