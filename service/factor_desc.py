"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

financial_factor_descriptions = [
    {
        "field": "net_profit_parent",
        "name": "归母净利润",
        "description": "归属于母公司股东的净利润，剔除少数股东损益后的核心盈利。",
        "formula": "净利润 - 少数股东损益",
        "usage": "衡量上市公司真实可分配利润，是估值和分红的基础。"
    },
    {
        "field": "operating_revenue",
        "name": "营业总收入",
        "description": "企业在报告期内通过主营业务及其他业务取得的全部收入。",
        "formula": "主营业务收入 + 其他业务收入",
        "usage": "反映公司整体经营规模和市场地位。"
    },
    {
        "field": "operating_cost",
        "name": "营业成本",
        "description": "与营业收入直接相关的成本支出，包括原材料、人工、制造费用等。",
        "formula": "直接材料 + 直接人工 + 制造费用",
        "usage": "用于计算毛利率，评估成本控制能力。"
    },
    {
        "field": "net_profit",
        "name": "净利润",
        "description": "企业税后总利润，包含少数股东损益。",
        "formula": "利润总额 - 所得税费用",
        "usage": "总盈利能力指标，但可能受非经常性项目干扰。"
    },
    {
        "field": "net_profit_excl_non_recurring",
        "name": "扣非净利润",
        "description": "扣除非经常性损益后的净利润，反映持续经营能力。",
        "formula": "净利润 - 非经常性损益净额",
        "usage": "更真实反映主营业务盈利质量，避免一次性收益/损失干扰。"
    },
    {
        "field": "total_equity",
        "name": "股东权益合计(净资产)",
        "description": "企业资产扣除负债后的剩余权益，即净资产。",
        "formula": "资产总计 - 负债总计",
        "usage": "用于计算 ROE、PB 等核心估值与杠杆指标。"
    },
    {
        "field": "goodwill",
        "name": "商誉",
        "description": "并购时支付对价超过被收购方可辨认净资产公允价值的部分。",
        "formula": "并购成本 - 可辨认净资产公允价值",
        "usage": "高商誉可能带来未来减值风险，需警惕资产泡沫。"
    },
    {
        "field": "operating_cash_flow",
        "name": "经营现金流量净额",
        "description": "经营活动产生的现金流入与流出的净额。",
        "formula": "销售商品收到现金 - 支付给供应商及员工等",
        "usage": "验证净利润含金量，现金流比利润更难操纵。"
    },
    {
        "field": "basic_eps",
        "name": "基本每股收益",
        "description": "归属于普通股股东的净利润除以加权平均普通股股数。",
        "formula": "归母净利润 / 加权平均普通股股数",
        "usage": "衡量每股盈利能力，是市盈率（PE）计算的基础。"
    },
    {
        "field": "bps",
        "name": "每股净资产",
        "description": "股东权益合计除以期末总股本。",
        "formula": "total_equity / 期末总股本",
        "usage": "用于计算市净率（PB），评估安全边际和估值水平。"
    },
    {
        "field": "cash_flow_per_share",
        "name": "每股现金流",
        "description": "经营活动现金流量净额除以总股本。",
        "formula": "operating_cash_flow / 总股本",
        "usage": "反映每股创造现金的能力，常用于现金流估值模型。"
    },
    {
        "field": "roe",
        "name": "净资产收益率(ROE)",
        "description": "归母净利润与净资产的比率，衡量股东回报效率。",
        "formula": "net_profit_parent / total_equity",
        "usage": "杜邦分析起点，核心盈利能力指标，>15% 通常视为优质。"
    },
    {
        "field": "roa",
        "name": "总资产报酬率(ROA)",
        "description": "净利润与总资产的比率，衡量资产利用效率。",
        "formula": "net_profit / 总资产",
        "usage": "评估管理层使用全部资产创造利润的能力，跨行业可比性较强。"
    },
    {
        "field": "gross_margin",
        "name": "毛利率",
        "description": "毛利占营业收入的比例，反映产品或服务的定价能力。",
        "formula": "(operating_revenue - operating_cost) / operating_revenue",
        "usage": "高毛利率通常意味着强竞争优势或成本优势。"
    },
    {
        "field": "net_profit_margin",
        "name": "销售净利率",
        "description": "净利润占营业收入的比例，反映从收入到利润的转化效率。",
        "formula": "net_profit / operating_revenue",
        "usage": "综合体现企业成本控制、费用管理和盈利能力。"
    },
    {
        "field": "period_expense_ratio",
        "name": "期间费用率",
        "description": "销售、管理、研发、财务费用合计占营业收入的比例。",
        "formula": "(销售费用 + 管理费用 + 研发费用 + 财务费用) / operating_revenue",
        "usage": "费用率过高可能侵蚀利润，需结合行业判断合理性。"
    },
    {
        "field": "debt_to_asset_ratio",
        "name": "资产负债率",
        "description": "总负债占总资产的比例，衡量财务杠杆水平。",
        "formula": "总负债 / 总资产",
        "usage": ">70% 通常视为高风险，金融/地产行业除外。"
    },
    {
        "field": "diluted_eps",
        "name": "稀释每股收益",
        "description": "考虑潜在普通股（如期权、可转债）转换后的每股收益。",
        "formula": "(归母净利润 + 可转换证券利息*(1-税率)) / (加权平均股数 + 潜在股数)",
        "usage": "比基本 EPS 更保守，适用于存在大量潜在稀释工具的公司。"
    },
    {
        "field": "fully_diluted_eps_latest_shares",
        "name": "摊薄每股收益_最新股数",
        "description": "基于最新总股本（含限售股等）计算的摊薄 EPS。",
        "formula": "归母净利润 / 最新总股本",
        "usage": "反映当前实际每股收益水平，适用于股权结构变动频繁的公司。"
    },
    {
        "field": "fully_diluted_bps_end_shares",
        "name": "摊薄每股净资产_期末股数",
        "description": "基于期末总股本计算的每股净资产。",
        "formula": "total_equity / 期末总股本",
        "usage": "与 BPS 类似，但强调使用期末确切股数，避免加权平均偏差。"
    },
    {
        "field": "adjusted_bps_end_shares",
        "name": "调整每股净资产_期末股数",
        "description": "剔除商誉、长期待摊等虚资产后的每股净资产。",
        "formula": "(total_equity - 商誉 - 其他虚资产) / 期末总股本",
        "usage": "更真实反映可变现净资产，适用于重资产或高商誉公司。"
    },
    {
        "field": "bps_latest_shares",
        "name": "每股净资产_最新股数",
        "description": "基于最新披露总股本计算的每股净资产。",
        "formula": "total_equity / 最新总股本",
        "usage": "用于实时 PB 计算，尤其适用于增发/回购后未更新加权股数的情形。"
    },
    {
        "field": "operating_cash_flow_per_share",
        "name": "每股经营现金流",
        "description": "经营现金流量净额除以总股本。",
        "formula": "operating_cash_flow / 总股本",
        "usage": "衡量每股创造经营现金的能力，是自由现金流的基础。"
    },
    {
        "field": "net_cash_flow_per_share",
        "name": "每股现金流量净额",
        "description": "三大活动（经营、投资、筹资）现金净额合计除以总股本。",
        "formula": "（经营+投资+筹资现金流净额）/ 总股本",
        "usage": "反映公司整体现金增减情况，但不如经营现金流稳定。"
    },
    {
        "field": "fcff_per_share",
        "name": "每股企业自由现金流量",
        "description": "企业自由现金流（FCFF）除以总股本，代表可供所有资本提供者的现金流。",
        "formula": "(经营现金流 - 资本开支) / 总股本",
        "usage": "DCF 估值核心输入，适用于企业价值（EV）评估。"
    },
    {
        "field": "fcfe_per_share",
        "name": "每股股东自由现金流量",
        "description": "股东自由现金流（FCFE）除以总股本，代表可分配给股东的现金。",
        "formula": "FCFF - 利息*(1-税率) + 净借债 / 总股本",
        "usage": "用于股权估值，尤其适用于高分红或回购公司。"
    },
    {
        "field": "retained_earnings_per_share",
        "name": "每股未分配利润",
        "description": "未分配利润除以总股本，反映可转增股本或分红的潜力。",
        "formula": "未分配利润 / 总股本",
        "usage": "高值公司具备送股或现金分红能力。"
    },
    {
        "field": "capital_reserve_per_share",
        "name": "每股资本公积金",
        "description": "资本公积除以总股本，主要来自股票溢价发行。",
        "formula": "资本公积 / 总股本",
        "usage": "可用于转增股本，但不能用于分红。"
    },
    {
        "field": "surplus_reserve_per_share",
        "name": "每股盈余公积金",
        "description": "法定或任意盈余公积除以总股本。",
        "formula": "盈余公积 / 总股本",
        "usage": "反映利润积累，可用于弥补亏损或转增资本。"
    },
    {
        "field": "retained_surplus_per_share",
        "name": "每股留存收益",
        "description": "盈余公积与未分配利润之和除以总股本。",
        "formula": "(盈余公积 + 未分配利润) / 总股本",
        "usage": "综合反映公司利润再投资能力。"
    },
    {
        "field": "revenue_per_share",
        "name": "每股营业收入",
        "description": "营业总收入除以总股本。",
        "formula": "operating_revenue / 总股本",
        "usage": "衡量每股创收能力，常用于零售、互联网等轻资产行业。"
    },
    {
        "field": "operating_revenue_per_share",
        "name": "每股营业总收入",
        "description": "同“每股营业收入”，强调营业口径。",
        "formula": "operating_revenue / 总股本",
        "usage": "与 revenue_per_share 含义一致，用于标准化比较。"
    },
    {
        "field": "ebit_per_share",
        "name": "每股息税前利润",
        "description": "息税前利润（EBIT）除以总股本。",
        "formula": "EBIT / 总股本",
        "usage": "剔除资本结构和税率影响，便于跨公司比较经营效率。"
    },
    {
        "field": "fully_diluted_roe",
        "name": "摊薄净资产收益率",
        "description": "基于摊薄后净资产计算的 ROE。",
        "formula": "net_profit_parent / (total_equity + 潜在权益调整)",
        "usage": "更保守的 ROE 估计，适用于存在可转债等工具的公司。"
    },
    {
        "field": "avg_roe",
        "name": "净资产收益率_平均",
        "description": "使用期初期末净资产平均值计算的 ROE，更准确。",
        "formula": "net_profit_parent / ((期初权益 + 期末权益)/2)",
        "usage": "避免期末权益突变（如增发）导致的 ROE 失真。"
    },
    {
        "field": "avg_roe_excl_non_recurring",
        "name": "净资产收益率_平均_扣除非经常损益",
        "description": "基于扣非净利润和平均净资产计算的 ROE。",
        "formula": "net_profit_excl_non_recurring / ((期初权益 + 期末权益)/2)",
        "usage": "最真实的持续盈利能力指标，推荐作为核心筛选条件。"
    },
    {
        "field": "fully_diluted_roe_excl_non_recurring",
        "name": "摊薄净资产收益率_扣除非经常损益",
        "description": "摊薄且扣非后的 ROE，双重保守估计。",
        "formula": "net_profit_excl_non_recurring / 摊薄后平均净资产",
        "usage": "适用于严格质量筛选，如养老金或保险资金选股。"
    },
    {
        "field": "ebit_margin",
        "name": "息税前利润率",
        "description": "EBIT 占营业收入的比例。",
        "formula": "EBIT / operating_revenue",
        "usage": "剔除融资和税务影响，纯粹衡量经营盈利能力。"
    },
    {
        "field": "roa_alt",
        "name": "总资产报酬率",
        "description": "与 roa 含义相同，可能使用不同净利润口径（如含少数股东）。",
        "formula": "净利润（含少数股东）/ 总资产",
        "usage": "若与 roa 并存，建议优先使用 roa（归母口径）。"
    },
    {
        "field": "return_on_capital",
        "name": "总资本回报率",
        "description": "税后营业利润与总资本（债务+权益）的比率。",
        "formula": "NOPAT / (有息负债 + 股东权益)",
        "usage": "类似 ROIC，衡量全部资本的使用效率。"
    },
    {
        "field": "roic",
        "name": "投入资本回报率",
        "description": "税后净营业利润与投入资本的比率，衡量资本配置效率。",
        "formula": "NOPAT / (有息负债 + 股东权益 - 现金及等价物)",
        "usage": "优于 ROE，因考虑了所有资本成本，适合跨行业比较。"
    },
    {
        "field": "after_tax_roa_avg",
        "name": "息前税后总资产报酬率_平均",
        "description": "使用平均总资产和税后 EBIT 计算的 ROA。",
        "formula": "EBIT * (1 - 税率) / 平均总资产",
        "usage": "更精确的资产回报率，适用于资本密集型行业分析。"
    },
    {
        "field": "cost_expense_profit_ratio",
        "name": "成本费用利润率",
        "description": "利润总额与成本费用总额的比率。",
        "formula": "利润总额 / (营业成本 + 期间费用 + 税金等)",
        "usage": "反映每单位成本费用带来的利润，越高越好。"
    },
    {
        "field": "operating_profit_margin",
        "name": "营业利润率",
        "description": "营业利润占营业收入的比例。",
        "formula": "营业利润 / operating_revenue",
        "usage": "衡量核心业务盈利能力，不含营业外收支。"
    },
    {
        "field": "net_asset_return_avg",
        "name": "总资产净利率_平均",
        "description": "净利润与平均总资产的比率。",
        "formula": "net_profit / ((期初总资产 + 期末总资产)/2)",
        "usage": "比单点 ROA 更平滑，减少季节性波动影响。"
    },
    {
        "field": "net_asset_return_avg_with_minority",
        "name": "总资产净利率_平均(含少数股东损益)",
        "description": "含少数股东损益的净利润与平均总资产的比率。",
        "formula": "(净利润) / 平均总资产",
        "usage": "适用于集团型企业，但归母口径更常用。"
    },
    {
        "field": "revenue_growth_yoy",
        "name": "营业总收入增长率",
        "description": "本期营业总收入相比上年同期的增长率。",
        "formula": "(本期营收 - 去年同期营收) / abs(去年同期营收)",
        "usage": "衡量公司成长性，高增长通常受市场青睐。"
    },
    {
        "field": "net_profit_parent_growth_yoy",
        "name": "归属母公司净利润增长率",
        "description": "本期归母净利润相比上年同期的增长率。",
        "formula": "(本期归母净利 - 去年同期) / abs(去年同期)",
        "usage": "核心成长指标，需结合扣非净利润判断质量。"
    },
    {
        "field": "ocf_to_revenue",
        "name": "经营活动净现金/销售收入",
        "description": "经营现金流与营业收入的比率。",
        "formula": "operating_cash_flow / operating_revenue",
        "usage": "衡量每元收入带来的现金，>0.1 通常较好。"
    },
    {
        "field": "ocf_to_operating_revenue",
        "name": "经营性现金净流量/营业总收入",
        "description": "同 ocf_to_revenue，强调营业口径。",
        "formula": "operating_cash_flow / operating_revenue",
        "usage": "与 ocf_to_revenue 含义一致。"
    },
    {
        "field": "cost_expense_ratio",
        "name": "成本费用率",
        "description": "营业成本与期间费用合计占营业收入的比例。",
        "formula": "(营业成本 + 期间费用) / operating_revenue",
        "usage": "越低越好，反映成本控制和运营效率。"
    },
    {
        "field": "cost_of_sales_ratio",
        "name": "销售成本率",
        "description": "营业成本占营业收入的比例。",
        "formula": "operating_cost / operating_revenue",
        "usage": "与毛利率互补，1 - 销售成本率 = 毛利率。"
    },
    {
        "field": "ocf_to_net_profit_parent",
        "name": "经营活动净现金/归属母公司的净利润",
        "description": "经营现金流与归母净利润的比值，衡量盈利质量。",
        "formula": "operating_cash_flow / net_profit_parent",
        "usage": "比值 >1 表示利润含金量高，<0.5 需警惕。"
    },
    {
        "field": "income_tax_to_total_profit",
        "name": "所得税/利润总额",
        "description": "所得税费用占利润总额的比例，反映实际税负。",
        "formula": "所得税费用 / 利润总额",
        "usage": "异常低可能享受税收优惠，异常高需核查合规性。"
    },
    {
        "field": "current_ratio",
        "name": "流动比率",
        "description": "流动资产与流动负债的比率，衡量短期偿债能力。",
        "formula": "流动资产 / 流动负债",
        "usage": "一般 >1.5 较安全，过高可能资产效率低。"
    },
    {
        "field": "quick_ratio",
        "name": "速动比率",
        "description": "（流动资产 - 存货）与流动负债的比率，更严格的短期偿债指标。",
        "formula": "(流动资产 - 存货) / 流动负债",
        "usage": "剔除变现较慢的存货，反映即时偿债能力。"
    },
    {
        "field": "conservative_quick_ratio",
        "name": "保守速动比率",
        "description": "（货币资金 + 交易性金融资产 + 应收账款）与流动负债的比率。",
        "formula": "(现金 + 短期投资 + 应收账款) / 流动负债",
        "usage": "最保守的短期偿债能力指标，仅包含高流动性资产。"
    },
    {
        "field": "equity_multiplier",
        "name": "权益乘数",
        "description": "总资产与股东权益的比率，反映财务杠杆水平。",
        "formula": "总资产 / total_equity",
        "usage": "杜邦分析中的杠杆因子，越高风险越大。"
    },
    {
        "field": "equity_multiplier_with_minority",
        "name": "权益乘数(含少数股权的净资产)",
        "description": "总资产与含少数股东权益的净资产之比。",
        "formula": "总资产 / (total_equity + 少数股东权益)",
        "usage": "适用于集团合并报表场景，但归母口径更常用。"
    },
    {
        "field": "equity_ratio",
        "name": "产权比率",
        "description": "负债总额与股东权益的比率，衡量资本结构风险。",
        "formula": "总负债 / total_equity",
        "usage": "越低越稳健，金融行业通常较高。"
    },
    {
        "field": "cash_ratio",
        "name": "现金比率",
        "description": "货币资金与流动负债的比率，最严格的短期偿债指标。",
        "formula": "货币资金 / 流动负债",
        "usage": ">0.2 通常可接受，过高说明现金利用效率低。"
    },
    {
        "field": "ar_turnover",
        "name": "应收账款周转率",
        "description": "营业收入与平均应收账款的比率，反映回款速度。",
        "formula": "operating_revenue / 平均应收账款",
        "usage": "越高越好，说明销售回款快，坏账风险低。"
    },
    {
        "field": "ar_turnover_days",
        "name": "应收账款周转天数",
        "description": "平均应收账款回收所需天数。",
        "formula": "365 / ar_turnover",
        "usage": "天数越短越好，制造业通常 <60 天。"
    },
    {
        "field": "inventory_turnover",
        "name": "存货周转率",
        "description": "营业成本与平均存货的比率，反映库存管理效率。",
        "formula": "operating_cost / 平均存货",
        "usage": "过高可能缺货，过低可能滞销。"
    },
    {
        "field": "inventory_turnover_days",
        "name": "存货周转天数",
        "description": "存货从购入到售出的平均天数。",
        "formula": "365 / inventory_turnover",
        "usage": "零售业通常 <30 天，重工业可能 >100 天。"
    },
    {
        "field": "total_asset_turnover",
        "name": "总资产周转率",
        "description": "营业收入与平均总资产的比率，衡量资产创收能力。",
        "formula": "operating_revenue / 平均总资产",
        "usage": "轻资产公司通常更高，重资产公司较低。"
    },
    {
        "field": "total_asset_turnover_days",
        "name": "总资产周转天数",
        "description": "总资产周转一次所需的平均天数。",
        "formula": "365 / total_asset_turnover",
        "usage": "辅助理解资产使用效率，越短越好。"
    },
    {
        "field": "current_asset_turnover",
        "name": "流动资产周转率",
        "description": "营业收入与平均流动资产的比率。",
        "formula": "operating_revenue / 平均流动资产",
        "usage": "衡量流动资产使用效率，过高可能营运资金紧张。"
    },
    {
        "field": "current_asset_turnover_days",
        "name": "流动资产周转天数",
        "description": "流动资产周转一次所需的平均天数。",
        "formula": "365 / current_asset_turnover",
        "usage": "辅助评估营运资金管理效率。"
    },
    {
        "field": "ap_turnover",
        "name": "应付账款周转率",
        "description": "营业成本与平均应付账款的比率，反映付款节奏。",
        "formula": "operating_cost / 平均应付账款",
        "usage": "过低可能占用供应商资金，过高可能丧失信用优惠。"
    }
]

factor_descriptions = [
    # ========== 动量类 ==========
    {
        "field": "mom_10",
        "name": "10日动量",
        "description": "过去10个交易日的累计收益率，衡量短期价格趋势强度。",
        "formula": "mom_10 = close / close.shift(10) - 1",
        "usage": "捕捉短期上涨或下跌动能，常用于趋势跟踪策略。"
    },
    {
        "field": "mom_20",
        "name": "20日动量",
        "description": "过去20个交易日的累计收益率，反映中期价格动量。",
        "formula": "mom_20 = close / close.shift(20) - 1",
        "usage": "比10日更平滑，减少噪音，适用于中期交易信号。"
    },
    {
        "field": "mom_50",
        "name": "50日动量",
        "description": "过去50个交易日的累计收益率，代表中长期趋势。",
        "formula": "mom_50 = close / close.shift(50) - 1",
        "usage": "用于识别主升浪或长期下跌趋势，适合配置型策略。"
    },
    {
        "field": "mom_composite",
        "name": "复合动量",
        "description": "10日、20日和50日动量的等权平均值，综合多周期动量信息。",
        "formula": "mom_composite = mean(mom_10, mom_20, mom_50)",
        "usage": "平衡短、中、长期动量，提升因子稳健性。"
    },

    # ========== 波动率类 ==========
    {
        "field": "vol_10",
        "name": "10日年化波动率",
        "description": "基于过去10日收益率的标准差，年化处理（乘以√252），衡量短期风险。",
        "formula": "vol_10 = std(close.pct_change(), window=10) * sqrt(252)",
        "usage": "高波动可能预示变盘，低波动可能预示盘整。"
    },
    {
        "field": "vol_20",
        "name": "20日年化波动率",
        "description": "过去20日收益率的年化标准差，反映中期市场波动水平。",
        "formula": "vol_20 = std(close.pct_change(), window=20) * sqrt(252)",
        "usage": "常用于风险控制、仓位调整。"
    },
    {
        "field": "vol_50",
        "name": "50日年化波动率",
        "description": "过去50日收益率的年化标准差，代表中长期波动特征。",
        "formula": "vol_50 = std(close.pct_change(), window=50) * sqrt(252)",
        "usage": "用于评估资产长期风险属性。"
    },
    {
        "field": "vol_composite",
        "name": "复合波动率",
        "description": "10日、20日、50日波动率的等权平均，综合多尺度风险度量。",
        "formula": "vol_composite = mean(vol_10, vol_20, vol_50)",
        "usage": "提供更稳定的波动率估计，避免单一窗口偏差。数值范围0~1。"
    },

    # ========== 乖离率（BIAS）==========
    {
        "field": "bias_10",
        "name": "10日乖离率",
        "description": "当前价格相对于10日均线的偏离百分比，反映超买超卖状态。",
        "formula": "bias_10 = (close - MA(close, 10)) / MA(close, 10)",
        "usage": "正值过大可能超买，负值过大可能超卖。"
    },
    {
        "field": "bias_20",
        "name": "20日乖离率",
        "description": "当前价格相对于20日均线的偏离程度。",
        "formula": "bias_20 = (close - MA(close, 20)) / MA(close, 20)",
        "usage": "比10日更稳定，适用于震荡市中的反转信号。"
    },
    {
        "field": "bias_50",
        "name": "50日乖离率",
        "description": "当前价格相对于50日均线的偏离程度，反映中长期估值偏离。",
        "formula": "bias_50 = (close - MA(close, 50)) / MA(close, 50)",
        "usage": "用于判断长期趋势是否过热或过度悲观。"
    },
    {
        "field": "bias_composite",
        "name": "复合乖离率",
        "description": "10日、20日、50日乖离率的等权平均。",
        "formula": "bias_composite = mean(bias_10, bias_20, bias_50)",
        "usage": "综合多周期偏离信号，提高反转判断准确性。"
    },

    # ========== RSI ==========
    {
        "field": "rsi_14",
        "name": "14日相对强弱指数",
        "description": "基于14日涨跌幅平均值计算的动量振荡器，范围0-100。",
        "formula": "RS = avg_gain / avg_loss; RSI = 100 - 100 / (1 + RS)",
        "usage": "RSI > 70 为超买，RSI < 30 为超卖，常用于反转策略。"
    },

    # ========== 多头排列 ==========
    {
        "field": "is_ma_bullish",
        "name": "是否多头排列",
        "description": "判断多个均线的排列情况",
        "formula": "",
        "usage": "is_ma_bullish = 1 为多头排列，is_ma_bullish = 0 不是多头排列。"
    },

    # ========== MACD ==========
    {
        "field": "macd",
        "name": "MACD线",
        "description": "12日指数移动平均与26日指数移动平均之差，反映短期与长期趋势差异。",
        "formula": "MACD = EMA(close, 12) - EMA(close, 26)",
        "usage": "上穿信号线为买入信号，下穿为卖出信号。"
    },
    {
        "field": "macd_signal",
        "name": "MACD信号线",
        "description": "MACD线的9日指数移动平均，作为触发线。",
        "formula": "Signal = EMA(MACD, 9)",
        "usage": "与MACD线交叉形成交易信号。"
    },
    {
        "field": "macd_hist",
        "name": "MACD柱状图",
        "description": "MACD线与信号线之差，反映动量加速或减速。",
        "formula": "Histogram = MACD - Signal",
        "usage": "柱状图放大表示趋势加强，缩小表示动能衰减。"
    },

    # ========== 换手活跃度（简化版）==========
    {
        "field": "turnover_5",
        "name": "5日平均成交量",
        "description": "过去5个交易日的平均成交量，衡量短期交易活跃度。",
        "formula": "turnover_5 = mean(volume, window=5)",
        "usage": "放量上涨/下跌更具可信度。"
    },
    {
        "field": "turnover_10",
        "name": "10日平均成交量",
        "description": "过去10日平均成交量，反映中期资金参与度。",
        "formula": "turnover_10 = mean(volume, window=10)",
        "usage": "用于确认突破有效性。"
    },
    {
        "field": "turnover_20",
        "name": "20日平均成交量",
        "description": "过去20日平均成交量，代表月度平均交投水平。",
        "formula": "turnover_20 = mean(volume, window=20)",
        "usage": "判断当前成交是否显著高于/低于常态。"
    },
    {
        "field": "turnover_composite",
        "name": "复合换手活跃度",
        "description": "5日、10日、20日平均成交量的等权平均。",
        "formula": "turnover_composite = mean(turnover_5, turnover_10, turnover_20)",
        "usage": "综合评估交易热度，避免单窗口噪声。"
    },
    {
        "field": "mom_5",
        "name": "5日动量",
        "description": "过去5个交易日的累计收益率，衡量超短期价格动能。",
        "formula": "mom_5 = close / close.shift(5) - 1",
        "usage": "捕捉超短线爆发力，噪声较大，通常与更长周期动量配合使用。"
    },
    {
        "field": "mom_acc",
        "name": "动量加速度",
        "description": "短周期动量相对长周期动量的差值，衡量动能是加速还是衰减。",
        "formula": "mom_acc = (mom_5 - ((1+mom_20)^(1/4) - 1)) * 10",
        "usage": "正值表示短期动能强于中期（加速），负值表示动能衰减。"
    },
    {
        "field": "mom_risk_adj_5",
        "name": "5日风险调整动量",
        "description": "5日动量除以同期日收益率标准差（中性化），衡量单位风险下的收益。",
        "formula": "mom_risk_adj_5 = mom_5 / (std(ret, 5) * sqrt(5) + 1e-8)",
        "usage": "比原始动量更公平地比较不同波动水平标的的趋势质量。"
    },
    {
        "field": "mom_risk_adj_10",
        "name": "10日风险调整动量",
        "description": "10日动量除以同期日收益率标准差，衡量单位风险下的收益。",
        "formula": "mom_risk_adj_10 = mom_10 / (std(ret, 10) * sqrt(10) + 1e-8)",
        "usage": "用于识别「稳健上涨」与「高波动虚涨」的区别。"
    },
    {
        "field": "mom_risk_adj_20",
        "name": "20日风险调整动量",
        "description": "20日动量除以同期日收益率标准差，衡量单位风险下的收益。",
        "formula": "mom_risk_adj_20 = mom_20 / (std(ret, 20) * sqrt(20) + 1e-8)",
        "usage": "中期趋势质量的衡量，常用于趋势策略的因子暴露。"
    },
    {
        "field": "mom_risk_adj_50",
        "name": "50日风险调整动量",
        "description": "50日动量除以同期日收益率标准差，衡量单位风险下的收益。",
        "formula": "mom_risk_adj_50 = mom_50 / (std(ret, 50) * sqrt(50) + 1e-8)",
        "usage": "中长期趋势质量的衡量。"
    },
    {
        "field": "atr_14",
        "name": "ATR真实波幅(14)",
        "description": "14日平均真实波幅，衡量价格的平均波动幅度（绝对值，单位同股价）。",
        "formula": "ATR = SMA(TR, 14)，TR = max(high-low, |high-prev_close|, |low-prev_close|)",
        "usage": "常用于设定动态止损（如 现价 - 2×ATR）与仓位管理。"
    },
    {
        "field": "atr_14_annualized",
        "name": "年化ATR波幅",
        "description": "ATR(14) 的年化处理值（乘以 √252），便于跨标的、跨周期比较波动水平。",
        "formula": "atr_14_annualized = ATR * sqrt(252)",
        "usage": "与 vol_* 同为波动率度量，但基于真实波幅而非收益率标准差。"
    },
    {
        "field": "closing_strength",
        "name": "收盘强度",
        "description": "收盘价在当日最高最低区间中的相对位置，衡量多头在尾盘的掌控力。",
        "formula": "closing_strength = (close - low) / (high - low)",
        "usage": "接近 1 表示尾盘强势收在高位；接近 0 表示收在低位，常与量能结合判断。"
    },
    {
        "field": "52week_high",
        "name": "52周最高价",
        "description": "过去52周（约一年）内的最高交易价格。",
        "formula": "MAX(high_price, 252日)",
        "usage": "衡量股票的长期压力位，价格接近此位置可能面临回调压力。"
    },
    {
        "field": "52week_low",
        "name": "52周最低价",
        "description": "过去52周（约一年）内的最低交易价格。",
        "formula": "MIN(low_price, 252日)",
        "usage": "衡量股票的长期支撑位，价格接近此位置可能触发超跌反弹。"
    },
    {
        "field": "52week_position",
        "name": "52周相对位置",
        "description": "当前价格在52周价格区间内的相对位置，**取值 0~100**（百分比）。",
        "formula": "(close - 52week_low) / (52week_high - 52week_low) * 100",
        "usage": "50 为中位；>80 为高位（可能超买）；<20 为低位（可能超卖）。"
    }
]

# 1. 提取字段名
financial_fields = [item['field'] for item in financial_factor_descriptions]
technical_fields = [item['field'] for item in factor_descriptions]

# 2. 合并成全量因子列表
ALL_FACTOR_FIELDS = financial_fields + technical_fields

# 3. (可选) 去重 (如果两个列表中有重复的字段，比如 'roe' 可能都存在)
ALL_FACTOR_FIELDS = list(set(ALL_FACTOR_FIELDS))
