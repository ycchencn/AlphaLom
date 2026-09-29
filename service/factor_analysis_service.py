"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股技术面「专业分析」服务：把落库的因子从「裸数值」加工成「可研判的信息」。

设计原则：
1. **只读**：本服务不写任何数据，全部基于现有 `factor_values` 计算，不引入新表、不引入新 job。
2. **历史分位是核心**：一个 RSI=68 本身没有意义，只有「在自身历史里排第 76 百分位」才有意义。
   故所有对外数值都尽量附带 `percentile`（0~100）。
3. **分组固化在代码里**：因子 → 中文分组（动量/波动/乖离/量能/超买超卖/区间位置）是**代码级约定**，
   不给用户在页面上增删改 —— 与项目既有「固定话题」的取舍一致。
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy import func

from models import FactorValue
from models.database import db_session
from utils.logger import logger


# ==================== 技术因子分组（代码级约定） ====================
# key 为前端分组标识，fields 为该组包含的因子（顺序即展示顺序）。
TECH_FACTOR_GROUPS: List[Dict[str, Any]] = [
    {
        'key': 'momentum',
        'label': '动量',
        'desc': '衡量价格趋势的强弱与持续性',
        'fields': ['mom_5', 'mom_10', 'mom_20', 'mom_50', 'mom_composite', 'mom_acc'],
    },
    {
        'key': 'risk_adj_momentum',
        'label': '风险调整动量',
        'desc': '单位风险下的趋势质量（去波动后的动量）',
        'fields': ['mom_risk_adj_5', 'mom_risk_adj_10', 'mom_risk_adj_20', 'mom_risk_adj_50'],
    },
    {
        'key': 'volatility',
        'label': '波动率',
        'desc': '年化波动水平，越高风险越大',
        'fields': ['vol_10', 'vol_20', 'vol_50', 'vol_composite', 'atr_14', 'atr_14_annualized'],
    },
    {
        'key': 'bias',
        'label': '乖离率',
        'desc': '价格偏离均线的程度，过高/过低常有回归压力',
        'fields': ['bias_10', 'bias_20', 'bias_50', 'bias_composite'],
    },
    {
        'key': 'overbought',
        'label': '超买超卖',
        'desc': 'RSI 等强弱指标，判断短期过热或过冷',
        'fields': ['rsi_14', 'closing_strength'],
    },
    {
        'key': 'volume',
        'label': '量能',
        'desc': '成交量活跃度（注：无流通股本，以成交量均值近似）',
        'fields': ['turnover_5', 'turnover_10', 'turnover_20', 'turnover_composite'],
    },
    {
        'key': 'position',
        'label': '区间位置',
        'desc': '价格在 52 周区间中的相对位置与技术形态',
        'fields': ['52week_position'],
    },
]

# 反向因子：值越低越「好」（用于「好不好」的统一着色，不改变原始值展示）。
# ⚠️ 仅用于前端配色提示，不参与任何计算。
LOWER_IS_BETTER = {'vol_10', 'vol_20', 'vol_50', 'vol_composite', 'atr_14', 'atr_14_annualized', 'bias_composite'}

# 前端「因子看板」直接展示的分组（去掉重复的原始 atr，保留主指标）
PRIMARY_GROUPS = TECH_FACTOR_GROUPS


class FactorAnalysisService:
    """个股技术面专业分析（只读）。"""

    # ==================== 基础：一次取该股全部技术因子序列 ====================
    @staticmethod
    def _load_series(ticker: str, fields: List[str], lookback_days: int = 400) -> Dict[str, List[Dict[str, Any]]]:
        """
        一次性把该股若干因子的时间序列读出来，按因子名分组。
        ⚠️ 只查一次库（`factor_name IN (...)` + `ticker=`），避免每个因子一次往返。
        """
        if not fields:
            return {}
        start = date.today() - timedelta(days=lookback_days)
        try:
            rows = (
                db_session.query(
                    FactorValue.factor_name,
                    FactorValue.trade_date,
                    FactorValue.value,
                )
                .filter(
                    FactorValue.ticker == ticker,
                    FactorValue.factor_name.in_(fields),
                    FactorValue.trade_date >= start,
                    FactorValue.value.isnot(None),
                )
                .order_by(FactorValue.factor_name, FactorValue.trade_date)
                .all()
            )
        except Exception as e:
            logger.error(f"[FactorAnalysis] 读取因子序列失败 ticker={ticker}: {e}")
            return {}

        out: Dict[str, List[Dict[str, Any]]] = {f: [] for f in fields}
        for name, d, v in rows:
            out.setdefault(name, []).append({'date': d.isoformat(), 'value': float(v)})
        return {k: v for k, v in out.items() if v}

    # ==================== 分位数：值在自身历史中的位置 ====================
    @staticmethod
    def _percentile(series: List[float], value: float) -> Optional[float]:
        """
        返回 value 在 series 中的百分位（0~100）。
        用「小于等于的比例」定义；序列为空返回 None。
        """
        if not series:
            return None
        n_le = sum(1 for x in series if x <= value)
        return round(n_le / len(series) * 100, 1)

    # ==================== L0：因子看板 ====================
    @classmethod
    def get_factor_board(cls, ticker: str, lookback_days: int = 400) -> Dict[str, Any]:
        """
        因子看板数据：该股全部技术因子的最新值 + 历史分位 + 分组。
        """
        all_fields = [f for g in TECH_FACTOR_GROUPS for f in g['fields']]
        # 52week_low/high 供前端画区间条，也要取
        extra = ['52week_low', '52week_high']
        series_map = cls._load_series(ticker, list(dict.fromkeys(all_fields + extra)), lookback_days)

        from service.factor_desc import factor_descriptions
        meta = {it['field']: it for it in factor_descriptions if isinstance(it, dict)}

        groups_out = []
        for g in TECH_FACTOR_GROUPS:
            items = []
            for f in g['fields']:
                s = series_map.get(f) or []
                if not s:
                    continue
                latest = s[-1]
                values = [p['value'] for p in s]
                items.append({
                    'field': f,
                    'name': meta.get(f, {}).get('name', f),
                    'description': meta.get(f, {}).get('description', ''),
                    'value': round(latest['value'], 6),
                    'date': latest['date'],
                    'percentile': cls._percentile(values, latest['value']),
                    'lower_is_better': f in LOWER_IS_BETTER,
                    'count': len(values),
                })
            if items:
                groups_out.append({'key': g['key'], 'label': g['label'], 'desc': g['desc'], 'items': items})

        # 52 周区间（供前端画位置条）
        range_info = cls._build_52week_range(series_map)

        return {
            'ticker': ticker,
            'asof': series_map.get('rsi_14', [{}])[-1].get('date') if series_map.get('rsi_14') else None,
            'lookback_days': lookback_days,
            'groups': groups_out,
            'range_52week': range_info,
        }

    @staticmethod
    def _build_52week_range(series_map: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        lows = series_map.get('52week_low') or []
        highs = series_map.get('52week_high') or []
        pos = series_map.get('52week_position') or []
        if not lows or not highs:
            return None
        # ⚠️ 52week_position 在库里是 0~100（百分比），不是 0~1，别再 /100。
        return {
            'low': round(lows[-1]['value'], 4),
            'high': round(highs[-1]['value'], 4),
            'position': round(pos[-1]['value'], 4) if pos else None,
            'position_is_percent': True,
            'date': lows[-1]['date'],
        }

    # ==================== L0：多因子时间序列（画曲线用） ====================
    @classmethod
    def get_factor_series(cls, ticker: str, fields: List[str], lookback_days: int = 250) -> Dict[str, Any]:
        """多因子时间序列（按日期对齐），供前端画对比曲线。"""
        series_map = cls._load_series(ticker, fields, lookback_days)
        return {'ticker': ticker, 'series': series_map}

    # ==================== L1：关键位 / 量价健康度 / 均线 / 阶段 ====================
    @classmethod
    def get_dashboard(cls, ticker: str) -> Dict[str, Any]:
        """
        技术面仪表盘：把 L1 需要的派生信息一次性算好。
        包含：动量-波动象限落点、量价健康度、均线排列、关键支撑压力位、ATR 动态止损、
        超买超卖热度、主力行为阶段序列。
        """
        import pandas as pd
        from utils.data_loader import databull

        # 1) 取日线（用于均线、关键位、ATR 现价）
        df = None
        try:
            from utils.common import get_date_by_n, get_today
            # ⚠️ databull.get_stock_history(symbol, start_date, end_date) 三个参数都是必填，
            # 想用默认区间也必须显式传日期（与 routes/stock.py 的调用保持一致）。
            start = get_date_by_n(-400, _format='%Y-%m-%d')
            end = get_today()
            raw = databull.get_stock_history(symbol=ticker, start_date=start, end_date=end)
            df = raw.reset_index()
            # 兼容不同返回：日期可能落在 index 或 'date' 列
            if 'date' not in df.columns:
                first = df.columns[0]
                df = df.rename(columns={first: 'date'})
            df.columns = [str(c).lower() for c in df.columns]
        except Exception as e:
            logger.warning(f"[FactorAnalysis] 行情获取失败 ticker={ticker}: {e}")

        quotes = cls._quotes_summary(df, ticker)
        ma = cls._ma_status(df)
        levels = cls._key_levels(df, ticker)
        trend_quadrant = cls._trend_quadrant(ticker)
        phase = cls._phase_series(ticker)
        heat = cls._overbought_heat(ticker)

        return {
            'ticker': ticker,
            'quotes': quotes,
            'ma_status': ma,
            'key_levels': levels,
            'quadrant': trend_quadrant,
            'phase_series': phase,
            'heat': heat,
        }

    @staticmethod
    def _quotes_summary(df, ticker: str) -> Optional[Dict[str, Any]]:
        if df is None or df.empty:
            # 无行情时退化：用因子里的 52 周位置/ATR 兜底（至少不报错）
            return None
        try:
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            close = float(last['close'])
            prev_close = float(prev['close'])
            chg_pct = (close / prev_close - 1) * 100 if prev_close else 0.0
            return {
                'date': str(last['date'])[:10],
                'close': round(close, 3),
                'chg_pct': round(chg_pct, 2),
                'high': round(float(last['high']), 3),
                'low': round(float(last['low']), 3),
                'volume': float(last.get('volume', 0) or 0),
            }
        except Exception as e:
            logger.warning(f"[FactorAnalysis] 行情摘要失败 ticker={ticker}: {e}")
            return None

    @staticmethod
    def _ma_status(df) -> Optional[Dict[str, Any]]:
        """均线排列状态：MA5/10/20/60/120/250 + 多头/空头/纠缠判定。"""
        if df is None or len(df) < 20:
            return None
        try:
            close = df['close']
            periods = [5, 10, 20, 60, 120, 250]
            mas = {}
            for p in periods:
                if len(close) >= p:
                    mas[p] = float(close.rolling(p).mean().iloc[-1])
            cur = float(close.iloc[-1])

            # 排列判定：只看有值的相邻均线
            ordered = [(p, mas[p]) for p in periods if p in mas]
            seq = [v for _, v in ordered]
            if all(seq[i] > seq[i + 1] for i in range(len(seq) - 1)):
                state = 'bull'
                label = '多头排列'
            elif all(seq[i] < seq[i + 1] for i in range(len(seq) - 1)):
                state = 'bear'
                label = '空头排列'
            else:
                state = 'mixed'
                label = '均线纠缠'

            # 连续确认天数：短>中>长(5>10>20) 连续成立的天数
            s = close.rolling(5).mean()
            m = close.rolling(10).mean()
            l = close.rolling(20).mean()
            basic = (s > m) & (m > l)
            cnt = 0
            for v in reversed(basic.tolist()):
                if v:
                    cnt += 1
                else:
                    break

            return {
                'state': state,
                'label': label,
                'ma': {str(p): round(v, 3) for p, v in mas.items()},
                'close': round(cur, 3),
                'bull_days': cnt,
                # 价格相对各均线乖离（%）
                'bias_pct': {str(p): round((cur / v - 1) * 100, 2) for p, v in mas.items()},
            }
        except Exception as e:
            logger.warning(f"[FactorAnalysis] 均线状态失败: {e}")
            return None

    @staticmethod
    def _key_levels(df, ticker: str) -> Optional[Dict[str, Any]]:
        """
        关键位识别：52周高低 / 近期成交密集区（简易：近 60 日收盘价分位）/ ATR 动态止损。
        """
        import pandas as pd
        if df is None or df.empty:
            return None
        try:
            close = df['close']
            cur = float(close.iloc[-1])
            # 52 周高低（约 252 交易日）
            win = df.tail(252)
            hi52 = float(win['high'].max())
            lo52 = float(win['low'].min())

            # 成交密集区：近 60 日「收盘价 × 成交量」加权中位数区间（用价格分位近似）
            recent = df.tail(60)
            if 'volume' in recent.columns and recent['volume'].sum() > 0:
                prices = recent['close'].astype(float)
                weights = recent['volume'].astype(float)
                order = prices.argsort()
                prices_sorted = prices.iloc[order].values
                weights_sorted = weights.iloc[order].values
                cumw = weights_sorted.cumsum() / weights_sorted.sum()
                p25 = float(prices_sorted[(cumw >= 0.25).argmax()])
                p75 = float(prices_sorted[(cumw >= 0.75).argmax()])
            else:
                p25 = p75 = None

            # ATR(14) 动态止损
            atr = None
            try:
                h, l, c = df['high'], df['low'], df['close']
                tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
                atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
            except Exception:
                atr = None

            return {
                'close': round(cur, 3),
                'high_52w': round(hi52, 3),
                'low_52w': round(lo52, 3),
                'dense_zone': [round(p25, 3), round(p75, 3)] if (p25 and p75) else None,
                'atr14': round(atr, 3) if atr else None,
                'stop_loss_2atr': round(cur - 2 * atr, 3) if atr else None,
                'stop_loss_3atr': round(cur - 3 * atr, 3) if atr else None,
                'resistance': round(hi52, 3),
                'support': round(max(lo52, p25) if p25 else lo52, 3),
            }
        except Exception as e:
            logger.warning(f"[FactorAnalysis] 关键位失败 ticker={ticker}: {e}")
            return None

    @staticmethod
    def _trend_quadrant(ticker: str) -> Optional[Dict[str, Any]]:
        """动量-波动象限：取近 60 个交易日的 (动量分位, 波动分位) 轨迹 + 当前落点。"""
        series = FactorAnalysisService._load_series(
            ticker, ['mom_20', 'vol_20', 'mom_composite', 'vol_composite'], lookback_days=400
        )
        moms = series.get('mom_composite') or series.get('mom_20') or []
        vols = series.get('vol_composite') or series.get('vol_20') or []
        if len(moms) < 10 or len(vols) < 10:
            return None
        # 以各自全序列算分位，再取最近 60 个点的轨迹
        mom_vals = [p['value'] for p in moms]
        vol_vals = [p['value'] for p in vols]
        # 按日期对齐（两者都以交易日推进，取较短的尾部对齐）
        n = min(len(moms), len(vols), 60)
        by_date_mom = {p['date']: p['value'] for p in moms}
        by_date_vol = {p['date']: p['value'] for p in vols}
        common = sorted(set(by_date_mom) & set(by_date_vol))[-n:]
        track = []
        for d in common:
            track.append({
                'date': d,
                'mom_pct': FactorAnalysisService._percentile(mom_vals, by_date_mom[d]),
                'vol_pct': FactorAnalysisService._percentile(vol_vals, by_date_vol[d]),
            })
        cur = track[-1] if track else None
        return {
            'track': track,
            'current': cur,
            'x_label': '动量分位',
            'y_label': '波动分位',
        }

    @staticmethod
    def _phase_series(ticker: str, lookback_days: int = 400) -> Optional[Dict[str, Any]]:
        """主力行为阶段序列（近 250 交易日）。"""
        s = FactorAnalysisService._load_series(ticker, ['main_force_behavior_phase'], lookback_days)
        arr = (s.get('main_force_behavior_phase') or [])[-250:]
        if not arr:
            return None
        # 压成「连续区间」以便前端画时间轴
        NAME = {0: '未知', 1: '吸筹', 2: '洗盘', 3: '拉升', 5: '出货(初)', 6: '出货(末)'}
        segments = []
        for p in arr:
            code = int(round(p['value']))
            label = NAME.get(code, '未知')
            if segments and segments[-1]['code'] == code:
                segments[-1]['end'] = p['date']
                segments[-1]['days'] += 1
            else:
                segments.append({'code': code, 'label': label, 'start': p['date'], 'end': p['date'], 'days': 1})
        return {
            'segments': segments,
            'current': segments[-1] if segments else None,
            'name_map': NAME,
        }

    @staticmethod
    def _overbought_heat(ticker: str) -> Optional[Dict[str, Any]]:
        """超买超卖热度：RSI + 52周位置 + 乖离 三合一。"""
        s = FactorAnalysisService._load_series(
            ticker, ['rsi_14', '52week_position', 'bias_composite'], lookback_days=400
        )
        rsi = s.get('rsi_14') or []
        pos = s.get('52week_position') or []
        bias = s.get('bias_composite') or []
        if not rsi:
            return None
        cur_rsi = round(rsi[-1]['value'], 1)
        # 用分位统一到 0~100
        rsi_pct = FactorAnalysisService._percentile([p['value'] for p in rsi], rsi[-1]['value'])
        pos_pct = FactorAnalysisService._percentile([p['value'] for p in pos], pos[-1]['value']) if pos else None
        bias_pct = FactorAnalysisService._percentile([p['value'] for p in bias], bias[-1]['value']) if bias else None
        parts = [rsi_pct, pos_pct, bias_pct]
        parts = [p for p in parts if p is not None]
        heat = round(sum(parts) / len(parts), 1) if parts else None

        if cur_rsi >= 80:
            tag = '超买'
        elif cur_rsi <= 20:
            tag = '超卖'
        else:
            tag = '中性'
        return {
            'rsi': cur_rsi,
            'rsi_percentile': rsi_pct,
            'position_percentile': pos_pct,
            'bias_percentile': bias_pct,
            'heat': heat,
            'tag': tag,
        }

    # ==================== L2：雷达 + 横向对比 ====================
    RADAR_FIELDS = ['mom_20', 'mom_risk_adj_20', 'rsi_14', '52week_position', 'turnover_20', 'vol_20']

    @classmethod
    def get_radar(cls, ticker: str) -> Dict[str, Any]:
        """因子雷达：核心因子全部转 0~100 分位，用于与自身历史/同行业对比。"""
        series_map = cls._load_series(ticker, cls.RADAR_FIELDS, lookback_days=400)
        from service.factor_desc import factor_descriptions
        meta = {it['field']: it for it in factor_descriptions if isinstance(it, dict)}
        axes = []
        for f in cls.RADAR_FIELDS:
            s = series_map.get(f) or []
            if not s:
                continue
            vals = [p['value'] for p in s]
            pct = cls._percentile(vals, s[-1]['value'])
            if f in LOWER_IS_BETTER and pct is not None:
                pct = round(100 - pct, 1)  # 反向因子翻转：低波动 = 高分
            axes.append({
                'field': f,
                'name': meta.get(f, {}).get('name', f),
                'value': round(s[-1]['value'], 6),
                'score': pct,
            })
        return {'ticker': ticker, 'axes': axes}

    @classmethod
    def get_industry_rank(cls, ticker: str, factor_names: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        行业内因子排名：该股各因子在所属行业个股中的分位。
        依赖 `stocks.industry` 做行业成分股映射（同行业个股列表）。
        """
        from service import StockService
        me = StockService.get_stock_by_symbol(symbol=ticker)
        if not me:
            return None
        industry = me.get('industry')
        if not industry:
            return None
        peers = StockService.search_stocks(securities_type='stock', industry=industry, per_page=10000) or []
        peer_symbols = [p['symbol'] for p in peers if p.get('symbol')]
        if len(peer_symbols) < 3:
            return None

        names = factor_names or ['mom_20', 'rsi_14', '52week_position', 'vol_20', 'turnover_20', 'bias_20']
        # 取同行业全部个股在这些因子上的最新值
        latest = FactorValueService_get_latest(peer_symbols, names)  # {(ticker, factor): value}

        from service.factor_desc import factor_descriptions
        meta = {it['field']: it for it in factor_descriptions if isinstance(it, dict)}

        rows = []
        for f in names:
            peer_vals = [float(v) for (t, fn), v in latest.items() if fn == f and v is not None]
            my_v = latest.get((ticker, f))
            if not peer_vals or my_v is None:
                continue
            my_v = float(my_v)
            pct = round(sum(1 for x in peer_vals if x <= my_v) / len(peer_vals) * 100, 1)
            rows.append({
                'field': f,
                'name': meta.get(f, {}).get('name', f),
                'value': round(my_v, 6),
                'peer_median': round(sorted(peer_vals)[len(peer_vals) // 2], 6),
                'percentile': pct,
                # 反向因子（波动/ATR 等）越低越好，「优于同业」要反过来读
                'lower_is_better': f in LOWER_IS_BETTER,
                'peer_count': len(peer_vals),
            })
        if not rows:
            return None
        return {'ticker': ticker, 'industry': industry, 'peer_count': len(peer_symbols), 'rows': rows}


# 避免循环导入：在函数内引用
def FactorValueService_get_latest(tickers, names):
    from service.factor_service import FactorValueService
    return FactorValueService.get_latest_factor_values(tickers, names)
