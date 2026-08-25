"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from utils.data_loader import databull
from utils.logger import logger

# ---------- 基本面因子权重 ----------
FUNDAMENTAL_WEIGHTS = {
    "roe": 0.25,  # 盈利能力（ROE）
    "profit_growth": 0.20,  # 成长性（净利润同比）
    "cash_quality": 0.15,  # 盈利质量（销售现金/营收）
    "pe": 0.25,  # 估值（PE-TTM 近似）
    "debt_ratio": 0.15,  # 财务健康（资产负债率）
}

# PershareIndex 字段映射
PS_FIELDS = {
    "roe": "du_return_on_equity",  # 净资产收益率（杜邦）
    "roe_weighted": "equity_roe",  # 加权ROE（备用）
    "profit_growth": "inc_net_profit_rate",  # 归母净利润同比增长
    "cash_quality": "sales_cash_flow",  # 销售现金流/营业收入
    "gross_margin": "gross_profit",  # 毛利率（备用因子）
    "debt_ratio": "gear_ratio",  # 资产负债比率
    "eps_basic": "s_fa_eps_basic",  # 基本每股收益
    "ocfps": "s_fa_ocfps",  # 每股经营现金流
    "bps": "s_fa_bps",  # 每股净资产
    "report_date": "m_timetag",
    "announce_date": "m_anntime",
}


def compute_fundamental_scores(
        stock_code: str,
        start_date: str = "20240101",
        end_date: str = "20251231",
        nan_replacement: Any = None,
) -> Dict:
    """
    批量计算所有股票的基本面评分（单表 PershareIndex）

    @param stock_code: 股票代码
    @param start_time: 财报起始 YYYYMMDD
    @param end_time:   财报截止 YYYYMMDD
    @param nan_replacement: 空值替换（建议 None，由打分函数处理）

    @return: {stock_code: fundamental_score (0~100)}
    """

    try:
        # 只拉一张表，速度最快
        # 获取财务报告数据
        report_pershare_index = databull.get_stock_financial_data(
            symbol=stock_code,
            start_date=start_date,
            end_date=end_date,
            report_type='PershareIndex'
        )
        latest_report = report_pershare_index['data'][0]['report_table']

        if not latest_report:
            raise ValueError("无财报数据")

        # ---- 提取因子原始值 ----
        roe = latest_report.get(PS_FIELDS["roe"], 0) or 0.0
        # 如果 du_return_on_equity 为空，用 equity_roe 兜底
        if roe == 0 or pd.isna(roe):
            roe = latest_report.get(PS_FIELDS["roe_weighted"], 0) or 0.0

        profit_growth = latest_report.get(PS_FIELDS["profit_growth"], 0) or 0.0

        cash_quality = latest_report.get(PS_FIELDS["cash_quality"], 0) or 0.0
        # 如果 sales_cash_flow 为空，用 ocfps/bps 近似
        if cash_quality == 0 or pd.isna(cash_quality):
            ocfps = latest_report.get(PS_FIELDS["ocfps"], 0) or 0.0
            eps = latest_report.get(PS_FIELDS["eps_basic"], 0) or 0.0
            if eps > 0:
                cash_quality = ocfps / eps  # 经营现金流 / 净利润 近似

        debt_ratio = latest_report.get(PS_FIELDS["debt_ratio"], 50.0) or 50.0

        # 计算pe
        _tick = databull.get_last_tick(stock_code)
        eps = latest_report.get(PS_FIELDS["eps_basic"], 0) or 0.0
        pe = _calc_pe_from_eps(_tick['lastPrice'], eps)

        raw_factor = {
            "code": stock_code,
            "roe": float(roe),
            "profit_growth": float(profit_growth),
            "cash_quality": float(cash_quality),
            "pe": float(pe),
            "debt_ratio": float(debt_ratio),
        }

    except Exception as e:
        logger.info(f"    ✗ {stock_code} 基本面计算失败: {e}")
        raw_factor = {
            "code": stock_code,
            "roe": 0, "profit_growth": 0,
            "cash_quality": 0, "pe": 999, "debt_ratio": 50,
        }

    raw_factor['composite_score'] = score_single_fundamental(raw_factor)

    return raw_factor


# ---------- 2. 单只打分层（绝对阈值，不依赖全池） ----------
def score_single_fundamental(factors: Dict[str, Any]) -> float:
    """
    对单只股票的因子 dict 做绝对阈值打分，返回 0~100 综合分

    用于：实时单票评估、无法拿到全池数据时的兜底
    """
    w = FUNDAMENTAL_WEIGHTS
    factors["roe_score"] = _absolute_score(factors["roe"], (5, 10, 15, 20), ascending=False)
    factors["profit_growth_score"] = _absolute_score(factors["profit_growth"], (0, 10, 20, 30), ascending=False)
    factors["cash_quality_score"] = _absolute_score(factors["cash_quality"], (0.3, 0.6, 1.0, 1.5), ascending=False)
    factors["pe_score"] = _absolute_score(factors["pe"], (10, 20, 30, 50), ascending=True)
    factors["debt_ratio_score"] = _absolute_score(factors["debt_ratio"], (30, 50, 70, 85), ascending=True)
    composite = (
            factors["roe_score"] * w["roe"]
            + factors["profit_growth_score"] * w["profit_growth"]
            + factors["cash_quality_score"] * w["cash_quality"]
            + factors["pe_score"] * w["pe"]
            + factors["debt_ratio_score"] * w["debt_ratio"]
    )
    return round(composite, 2)


def _percentile_score(series: pd.Series, ascending: bool = True) -> pd.Series:
    """
    分位数排名打分，输出 0~100
    ascending=True  → 值越小分越低（PE、负债率）
    ascending=False → 值越大分越高（ROE、增速）
    自动去极值（Winsorize 3σ），NaN 填 50
    """
    s = series.copy().replace([np.inf, -np.inf], np.nan)
    valid = s.dropna()
    if len(valid) == 0:
        return pd.Series(50.0, index=series.index)

    mean, std = valid.mean(), valid.std()
    if std > 0:
        s = s.clip(mean - 3 * std, mean + 3 * std)

    if ascending:
        ranked = s.rank(pct=True, na_option="keep") * 100
    else:
        ranked = (1 - s.rank(pct=True, na_option="keep")) * 100

    result = pd.Series(50.0, index=series.index)
    result.loc[ranked.index] = ranked
    return result


def _absolute_score(value: float, thresholds: tuple, ascending: bool = True) -> float:
    """
    绝对阈值打分（0~100），四级分段
    thresholds: (差, 中, 良, 优)
    """
    if pd.isna(value) or value is None:
        return 50.0

    if ascending:
        # 值越小越好（PE、负债率）
        if value <= thresholds[0]:
            return 100.0
        elif value <= thresholds[1]:
            return 75.0
        elif value <= thresholds[2]:
            return 50.0
        elif value <= thresholds[3]:
            return 25.0
        else:
            return 10.0
    else:
        # 值越大越好（ROE、增速、现金质量）
        if value >= thresholds[3]:
            return 100.0
        elif value >= thresholds[2]:
            return 75.0
        elif value >= thresholds[1]:
            return 50.0
        elif value >= thresholds[0]:
            return 25.0
        else:
            return 10.0


def _get_latest_report(fin_list: List[Dict]) -> Optional[Dict]:
    """
    取最新一期财报数据
    优先年报（1231），兜底取最新
    """
    if not fin_list:
        return None
    annual = [d for d in fin_list if str(d.get("report_date", "")).endswith("1231")]
    if annual:
        return annual[-1]['report_table']
    return fin_list[-1]['report_table']


def _calc_pe_from_eps(close_price: float, eps: float) -> float:
    """
    PE = 股价 / 每股收益
    负值或零 → 返回 999（打分时会排到末尾）
    """
    if close_price is None or eps is None:
        return 999.0
    try:
        close_price = float(close_price)
        eps = float(eps)
    except (TypeError, ValueError):
        return 999.0

    if eps <= 0 or close_price <= 0:
        return 999.0
    return close_price / eps
