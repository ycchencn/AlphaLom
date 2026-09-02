"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pandas as pd
import quantstats as qs
import tempfile
import os
from typing import Dict, Any
from service import PortfolioDailySummaryService


def generate_strategy_performance_json(equity: pd.Series, title="策略报告", **kwargs) -> Dict[str, Any]:
    """
    提取QuantStats报告所有核心指标，生成结构化字典，可直接序列化存JSON
    所有指标和generate_html_report_string生成的HTML报告完全对齐
    """
    # show sharpe ratio
    return {
        'sharpe': float(qs.stats.sharpe(equity)),
        'max_drawdown': float(qs.stats.max_drawdown(equity))
    }


def generate_html_report_string(equity, title="策略报告", **kwargs):
    """
    你原有生成HTML报告的逻辑 + 可选自动导出关键数据JSON
    :param save_perf_json_path: 传入路径即可自动把关键绩效JSON存到对应文件，例如 ./20260902_strategy_perf.json
    """
    # 先提取结构化绩效数据
    perf_json = generate_strategy_performance_json(equity, title, **kwargs)

    # 原有生成HTML报告逻辑完全不变
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        qs.reports.html(equity,
                        prepare_returns=True,
                        output=tmp_path,
                        title=title,
                        **kwargs)
        with open(tmp_path, 'r', encoding='utf-8') as f:
            html_str = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return html_str, perf_json  # 同时返回HTML字符串和结构化字典，可直接写入数据库


if __name__ == "__main__":
    # 获取策略交易记录
    summary_list = PortfolioDailySummaryService.get_all_by_portfolio_id(portfolio_id=1)

    # 2. 转换为 DataFrame，只取日期和总资产
    df = pd.DataFrame(summary_list)
    df['date'] = pd.to_datetime(df['date'])  # 确保是 datetime 格式
    df = df.set_index('date').sort_index()  # 设为索引并按时间排序
    equity = df['total_assets']  # 净资产序列

    # 生成HTML同时自动保存关键绩效JSON
    html_content, perf_data = generate_html_report_string(
        equity,
        title="量化策略绩效报告"
    )

    print(perf_data)

    # 如果需要直接把绩效数据入库，直接用返回的perf_data字典存即可，不用二次IO读取文件
