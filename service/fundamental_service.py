

# ========================= 基本面打分模块 v2 =========================
# 适配 PershareIndex 实际字段，单表搞定
# 放置位置：放在 get_stock_scores() 之前，与上一版函数名相同，直接覆盖

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

def compute_all_fundamental_scores(
        stock_list: List[Dict],
        start_time: str = "20240101",
        end_time: str = "20251231",
        nan_replacement: Any = None,
) -> Dict[str, float]:
    """
    批量计算所有股票的基本面评分（单表 PershareIndex）

    @param stock_list: [{"stock_code": "600519.SH", "stock_name": "贵州茅台"}, ...]
    @param start_time: 财报起始 YYYYMMDD
    @param end_time:   财报截止 YYYYMMDD
    @param nan_replacement: 空值替换（建议 None，由打分函数处理）

    @return: {stock_code: fundamental_score (0~100)}
    """
    log("  📊 开始批量计算基本面评分（PershareIndex）...")
    t0 = time.time()

    raw_factors = []
    total = len(stock_list)

    for i, stock in enumerate(stock_list, 1):
        code = stock["stock_code"]
        try:
            # 只拉一张表，速度最快
            ps_list = get_stock_financial_data(
                code, "PershareIndex", start_time, end_time, nan_replacement=nan_replacement
            )
            latest = _get_latest_report(ps_list)

            if not latest:
                raise ValueError("无财报数据")

            # ---- 提取因子原始值 ----
            roe = latest.get(PS_FIELDS["roe"], 0) or 0.0
            # 如果 du_return_on_equity 为空，用 equity_roe 兜底
            if roe == 0 or pd.isna(roe):
                roe = latest.get(PS_FIELDS["roe_weighted"], 0) or 0.0

            profit_growth = latest.get(PS_FIELDS["profit_growth"], 0) or 0.0

            cash_quality = latest.get(PS_FIELDS["cash_quality"], 0) or 0.0
            # 如果 sales_cash_flow 为空，用 ocfps/bps 近似
            if cash_quality == 0 or pd.isna(cash_quality):
                ocfps = latest.get(PS_FIELDS["ocfps"], 0) or 0.0
                eps = latest.get(PS_FIELDS["eps_basic"], 0) or 0.0
                if eps > 0:
                    cash_quality = ocfps / eps  # 经营现金流 / 净利润 近似

            debt_ratio = latest.get(PS_FIELDS["debt_ratio"], 50.0) or 50.0

            # 计算pe
            _tick = get_single_tick(code)
            eps = latest.get(PS_FIELDS["eps_basic"], 0) or 0.0
            pe = _calc_pe_from_eps(_tick['lastPrice'], eps)

            raw_factors.append({
                "code": code,
                "roe": float(roe),
                "profit_growth": float(profit_growth),
                "cash_quality": float(cash_quality),
                "pe": float(pe),
                "debt_ratio": float(debt_ratio),
            })

        except Exception as e:
            log(f"    ✗ {code} 基本面计算失败: {e}")
            raw_factors.append({
                "code": code,
                "roe": 0, "profit_growth": 0,
                "cash_quality": 0, "pe": 999, "debt_ratio": 50,
            })

        if i % 50 == 0:
            log(f"    基本面进度: {i}/{total}")

    # ---------- 分位数打分 ----------
    df = pd.DataFrame(raw_factors)
    if len(df) == 0:
        log("    ⚠ 无有效基本面数据，全部返回 50 分")
        return {s["stock_code"]: 50.0 for s in stock_list}

    log(f"  📊 对 {len(df)} 只股票进行分位数打分...")

    df["roe_score"] = _percentile_score(df["roe"], ascending=False)
    df["growth_score"] = _percentile_score(df["profit_growth"], ascending=False)
    df["cash_score"] = _percentile_score(df["cash_quality"], ascending=False)
    df["pe_score"] = _percentile_score(df["pe"], ascending=True)  # PE 越低越好
    df["debt_score"] = _percentile_score(df["debt_ratio"], ascending=True)  # 负债率越低越好

    # ---------- 加权合成 ----------
    w = FUNDAMENTAL_WEIGHTS
    df["fundamental"] = (
            df["roe_score"] * w["roe"]
            + df["growth_score"] * w["profit_growth"]
            + df["cash_score"] * w["cash_quality"]
            + df["pe_score"] * w["pe"]
            + df["debt_score"] * w["debt_ratio"]
    ).round(2).clip(0, 100)

    log(f"  ✅ 基本面评分完成，耗时 {time.time() - t0:.1f}s  "
        f"均值={df['fundamental'].mean():.1f}  "
        f"最高={df['fundamental'].max():.1f}  "
        f"最低={df['fundamental'].min():.1f}")

    return dict(zip(df["code"], df["fundamental"]))