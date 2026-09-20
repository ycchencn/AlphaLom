"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
import numpy as np
from service import FactorValueService, StockService
from utils.logger import logger
from utils.common import is_etf

class FactorCalService:

    # 52 周 = 252 个交易日。取数窗口必须覆盖它，否则 rolling(min_periods=1) 会静默退化成
    # 「最近 N 个交易日的区间」而仍然算得出数（旧日更任务只取 120 个自然日 ≈ 82 根 K 线，
    # 于是 52 周低点实际是 82 日低点）。因子本身照算，但不足窗口时打警告。
    WEEK52_TRADING_DAYS = 252

    @staticmethod
    def _prepare_data(stock_code: str, start_date: str, end_date: str,
                      asset_type: str = None) -> pd.DataFrame:

        """统一获取并标准化行情数据

        :param asset_type: 'etf' / 'stock'，显式指定取数接口。批量任务本来就知道标的是哪一类，
            显式传入可绕开 `is_etf` 的号段启发式（历史上 562xxx 漏在白名单外，被当个股取数、
            结果只拿到 2 根 K 线、因子全被 dropna 掉）。为 None 时按代码推断。
        """

        from utils.data_loader import databull

        is_fund = is_etf(stock_code) if asset_type is None else (asset_type == 'etf')

        if is_fund:
            df = databull.get_etf_history(stock_code, start_date, end_date)
        else:
            # stock = StockService.get_stock_by_symbol(stock_code)
            # assert stock is not None
            df = databull.get_history(stock_code, start_date, end_date, period='d', market='cn')

        df = df.reset_index()

        if df.empty:
            raise ValueError("❌ 未获取到数据，请检查股票代码和日期")

        required_cols = ['date', 'open', 'high', 'low', 'close']
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"缺失必要列: {missing}. 请确保 MarketDataService 返回 OHLC 数据。")

        df = df[required_cols + (['volume'] if 'volume' in df.columns else [])].copy()
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df.sort_values('date').reset_index(drop=True)
        return df

    @staticmethod
    def update_atr_factor(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """
        ATR (Average True Range) 平均真实波动幅度因子

        原理:
        1. 计算真实范围 (True Range): max(High-Low, |High-Close_prev|, |Low-Close_prev|)
        2. 计算 TR 的移动平均值 (SMA)

        Args:
            df: 包含 'high', 'low', 'close' 列的 DataFrame
            window: 计算周期，默认为 14

        Returns:
            pd.DataFrame: 增加了 'atr_window' 和 'atr_anualized' 列的 DataFrame
        """
        if len(df) < window + 1:
            print(f"⚠️ 警告：数据量 ({len(df)}) 不足 {window} 天，无法计算 ATR")
            return df

        # 1. 计算前一日的收盘价
        close_prev = df['close'].shift(1)

        # 2. 计算三个差值
        high_low = df['high'] - df['low']
        high_close_prev = abs(df['high'] - close_prev)
        low_close_prev = abs(df['low'] - close_prev)

        # 3. 计算真实范围 (TR)
        df['tr'] = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)

        # 4. 计算 ATR (简单移动平均 SMA)
        df[f'atr_{window}'] = df['tr'].rolling(window=window, min_periods=1).mean()

        # 5. (可选) 年化 ATR (类似 vol_factor 的处理方式，方便跨资产比较)
        # 注意：ATR 是绝对数值，年化通常乘以 sqrt(252)，但在实际应用中直接看原始 ATR 或相对值更多
        # 这里提供年化版本供参考，如果不需要可删除
        df[f'atr_{window}_annualized'] = df[f'atr_{window}'] * np.sqrt(252)

        # 清理中间变量 tr
        df.drop(columns=['tr'], inplace=True)

        return df

    @staticmethod
    def update_mom_factor(df: pd.DataFrame) -> pd.DataFrame:
        """动量因子：过去 N 日收益率"""
        windows = [5, 10, 20, 50]
        for w in windows:
            df[f'mom_{w}'] = df['close'] / df['close'].shift(w) - 1
            # 计算日收益率（若没有）
        if 'ret' not in df.columns:
            df['ret'] = df['close'].pct_change()
            # 风险调整动量：用对应窗口的波动率调整（窗口长度 w 个交易日）
        for w in windows:
            # 滚动标准差（注意：不要包含当天收益率，否则有未来信息嫌疑，见下文）
            # 保守做法：用过去 w 天的日收益率标准差（不含当天）
            roll_std = df['ret'].shift(1).rolling(w).std()  # shift(1) 排除了当日收益率
            # 年化波动率（可选）
            # roll_vol_ann = roll_std * np.sqrt(252)
            # 风险调整动量 = 动量 / (波动率 * sqrt(w))
            df[f'mom_risk_adj_{w}'] = df[f'mom_{w}'] / (roll_std * np.sqrt(w) + 1e-8)  # 避免除零

        # 也可以基于动量复合指标
        df['mom_composite'] = df[['mom_10', 'mom_20', 'mom_50']].mean(axis=1)

        # 动量加速度
        df['mom_acc'] = (df['mom_5'] - ((1 + df['mom_20']) ** (1 / 4) - 1)) * 10

        # 清理中间变量 tr
        df.drop(columns=['ret'], inplace=True)

        return df

    @staticmethod
    def update_closing_strength(df: pd.DataFrame) -> pd.DataFrame:
        """收盘强度因子"""
        df['closing_strength'] = (df['close'] - df['low']) / (df['high'] - df['low'])
        return df

    @staticmethod
    def update_vol_factor(df: pd.DataFrame) -> pd.DataFrame:
        """波动率因子：过去 N 日收益率标准差"""
        df['ret'] = df['close'].pct_change()
        windows = [10, 20, 50]
        for w in windows:
            df[f'vol_{w}'] = df['ret'].rolling(window=w).std() * np.sqrt(252)  # 年化波动率
        df['vol_composite'] = df[['vol_10', 'vol_20', 'vol_50']].mean(axis=1)
        df.drop(columns=['ret'], inplace=True)
        return df

    @staticmethod
    def update_bias_factor(df: pd.DataFrame) -> pd.DataFrame:
        """乖离率 BIAS = (Close - MA(N)) / MA(N)"""
        windows = [10, 20, 50]
        for w in windows:
            ma = df['close'].rolling(window=w).mean()
            df[f'bias_{w}'] = (df['close'] - ma) / ma
        df['bias_composite'] = df[['bias_10', 'bias_20', 'bias_50']].mean(axis=1)
        return df

    @staticmethod
    def update_rsi_factor(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """RSI 相对强弱指数"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        df[f'rsi_{window}'] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def update_macd_factor(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        """MACD: (EMA_fast - EMA_slow), Signal, Histogram"""
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        return df

    @staticmethod
    def update_turnover_factor(df: pd.DataFrame) -> pd.DataFrame:
        """简化版换手率因子：使用成交量（若无流通股本，仅用 volume 代表活跃度）"""
        if 'volume' not in df.columns:
            print("⚠️ 警告：缺少 'volume' 列，跳过 turnover 因子")
            return df
        # 可选：计算过去 N 日平均成交量
        windows = [5, 10, 20]
        for w in windows:
            df[f'turnover_{w}'] = df['volume'].rolling(window=w).mean()
        df['turnover_composite'] = df[[f'turnover_{w}' for w in windows]].mean(axis=1)
        return df

    def update_is_ma_bullish_debug(df, short=5, mid=10, long=20, confirm_days=3):
        """
        带详细调试信息的均线多头排列计算
        """
        # 1. 计算均线
        ma_short = df['close'].rolling(window=short).mean()
        ma_mid = df['close'].rolling(window=mid).mean()
        ma_long = df['close'].rolling(window=long).mean()

        # 2. 基础判断：短 > 中 > 长
        # 注意：这里会产生 True/False
        is_bull_basic = (ma_short > ma_mid) & (ma_mid > ma_long)

        # 3. 持续性确认
        # rolling(sum) 会计算过去 N 天里 True 的个数
        bull_sum = is_bull_basic.rolling(window=confirm_days).sum()

        # 最终结果：过去 N 天每一天都是 True，和才等于 N
        is_confirmed = (bull_sum == confirm_days)

        # --- 调试输出区域 ---
        print(f"--- 🛠️ 调试信息 (最近 10 条数据) ---")
        # 取出最后 10 行数据用于展示，方便查看变化
        debug_df = df.iloc[-10:].copy()
        debug_df['ma_s'] = ma_short.iloc[-10:]
        debug_df['ma_m'] = ma_mid.iloc[-10:]
        debug_df['ma_l'] = ma_long.iloc[-10:]
        debug_df['is_bull_basic'] = is_bull_basic.iloc[-10:]
        debug_df['rolling_sum'] = bull_sum.iloc[-10:]
        debug_df['is_confirmed'] = is_confirmed.iloc[-10:]

        # 格式化输出，保留4位小数，方便观察大小关系
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.float_format', lambda x: '%.4f' % x)

        print(debug_df[['close', 'ma_s', 'ma_m', 'ma_l', 'is_bull_basic', 'rolling_sum', 'is_confirmed']])

        # 额外检查：是否存在 NaN
        if debug_df['ma_l'].isna().any():
            print("\n⚠️ 警告：检测到 NaN 值（通常是因为数据量不足，例如数据少于 20 行）。")

        # 检查是否有“假”多头（即满足大小关系，但均线在向下）
        # 这是一个常见的视觉误区
        ma_long_slope = ma_long.diff()
        debug_df['ma_l_slope'] = ma_long_slope.iloc[-10:]
        print(f"\n💡 提示：如果 ma_s > ma_m > ma_l 为 True，但 ma_l_slope < 0，说明长期趋势还在向下（反弹而非反转）。")
        print(debug_df[['ma_l_slope']].tail(10).to_string(float_format=lambda x: f"{x:.4f}"))

        # --- 正式赋值 ---
        df['is_ma_bullish'] = is_confirmed.astype(int)

        return df

    @staticmethod
    def update_is_ma_bullish(df, short=5, mid=10, long=20, confirm_days=3):
        """
        优化版：增加持续性确认
        """
        # 1. 计算均线
        ma_short = df['close'].rolling(window=short).mean()
        ma_mid = df['close'].rolling(window=mid).mean()
        ma_long = df['close'].rolling(window=long).mean()

        # 2. 基础判断：短 > 中 > 长
        is_bull_basic = (ma_short > ma_mid) & (ma_mid > ma_long)

        # 3. 持续性确认：使用 rolling sum 检查过去 N 天是否都满足条件
        # 如果 confirm_days=3，则只有连续3天满足条件，今天才记为 1
        df['is_ma_bullish'] = is_bull_basic.rolling(window=confirm_days).sum() == confirm_days

        # 转为整数
        df['is_ma_bullish'] = df['is_ma_bullish'].astype(int)

        return df

    @staticmethod
    def update_52week_range(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算52周价格范围因子（最高价和最低价）。

        Args:
            df: 包含 'high' 和 'low' 列的行情数据

        Returns:
            pd.DataFrame: 增加了 52week_low / 52week_high / 52week_position 列的 DataFrame
        """
        window = FactorCalService.WEEK52_TRADING_DAYS

        # 不足 252 根时 min_periods=1 仍让算式成立（次新标的不至于整段缺失），但此时得到的是
        # 「上市以来」区间而非 52 周区间 —— 显式告警，避免被当成真的 52 周高低。
        if len(df) < window:
            logger.warning(
                f"52周区间：行情仅 {len(df)} 根 K 线（< {window}），"
                f"当前值为「最近 {len(df)} 个交易日」区间；请检查取数窗口是否过短"
            )

        # 计算过去 252 个交易日 (约52周) 的最低价
        df['52week_low'] = df['low'].rolling(window=window, min_periods=1).min()

        # 计算过去 252 个交易日 (约52周) 的最高价
        df['52week_high'] = df['high'].rolling(window=window, min_periods=1).max()

        # 计算当前价格在52周区间的位置 (0-100之间)
        # (收盘价 - 52周最低) / (52周最高 - 52周最低) * 100
        # 区间宽度为 0（单根 K 线 / 长期停牌）会让分母为 0 得到 inf，DECIMAL(18,6) 存不下；
        # 换成 NaN，由 save_factor_records_to_db 的 notna 判断自然过滤掉。
        span = (df['52week_high'] - df['52week_low']).replace(0, np.nan)
        df['52week_position'] = (df['close'] - df['52week_low']) / span * 100

        return df

    @classmethod
    def calculate_all_factors(cls, stock_code: str, start_date: str, end_date: str,
                              asset_type: str = None) -> list:
        """
        计算所有支持的因子，并返回 record 格式的列表（每行一个 dict）

        :param asset_type: 'etf' / 'stock'，透传给 _prepare_data；None 时按代码前缀推断
        """

        df = cls._prepare_data(stock_code, start_date, end_date, asset_type=asset_type)

        # 依次添加因子

        # 计算动量
        df = cls.update_mom_factor(df)

        df = cls.update_vol_factor(df)

        df = cls.update_bias_factor(df)

        df = cls.update_rsi_factor(df)

        df = cls.update_macd_factor(df)

        df = cls.update_turnover_factor(df)

        df = cls.update_52week_range(df)

        df = cls.update_closing_strength(df)

        # 计算ATR
        df = cls.update_atr_factor(df, window=14)

        # 新增：均线多头排列
        df = cls.update_is_ma_bullish(df, short=5, mid=10, long=20)

        # 所有因子列（除去原始 OHLCV）
        factor_cols = [col for col in df.columns if col not in ['open', 'high', 'low', 'close', 'volume']]

        # 转为 record 格式，去除 NaN
        result = df[factor_cols].dropna().to_dict(orient='records')

        return result

    @staticmethod
    def save_factor_records_to_db(stock_code: str, factor_results: list):
        """
        将 calculate_all_factors 返回的宽表因子数据（list[dict]）转为长表并入库。

        参数:
            stock_code (str): 股票/ETF 代码，如 "515290"
            factor_results (list[dict]): 来自 calculate_all_factors 的返回值，
                                         每个 dict 包含 'date' 和多个因子字段
        """

        records = []
        for row in factor_results:
            trade_date = row['date']
            for factor_name, value in row.items():
                if factor_name == 'date':
                    continue
                if pd.notna(value) and value is not None:  # 过滤 NaN / None
                    records.append({
                        'ticker': stock_code,
                        'trade_date': trade_date,
                        'factor_name': factor_name,
                        'value': float(value)
                    })

        # logger.info((f"{stock_code}, 因子入库中... len(records): {len(records)}")
        if FactorValueService.bulk_create(records):
            logger.info(f"✅ {stock_code} 共 {len(records)} 条因子记录已入库")

if __name__ == '__main__':

    pass
