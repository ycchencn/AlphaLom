import pandas as pd
import json
import quantstats as qs
import tempfile
import os

def generate_html_report_string(equity, title="策略报告", **kwargs):
    """
    生成 quantstats HTML 报告并返回字符串。
    参数 equity: pd.Series 归一化后的净值曲线
    返回: str HTML 报告内容
    """
    # 创建临时文件（不自动删除，便于手动控制）
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        # 将报告写入临时文件
        qs.reports.html(equity,
                        prepare_returns=True,
                        output=tmp_path,
                        title=title,
                        **kwargs)
        # 读取文件内容
        with open(tmp_path, 'r', encoding='utf-8') as f:
            html_str = f.read()
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return html_str

if __name__ == "__main__":
    # 扩展 pandas 显示

    # 1. 加载你的 JSON 数据（假设保存在文件 portfolio.json 中）
    with open('report.json', 'r') as f:
        raw_data = json.load(f)

    # 2. 转换为 DataFrame，只取日期和总资产
    df = pd.DataFrame(raw_data)
    df['date'] = pd.to_datetime(df['date'])  # 确保是 datetime 格式
    df = df.set_index('date').sort_index()  # 设为索引并按时间排序
    equity = df['total_assets']  # 净资产序列

    # 你的归一化净值序列 equity
    html_content = generate_html_report_string(equity, title="量化策略绩效报告")