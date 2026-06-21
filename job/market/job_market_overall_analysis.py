"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from llms import get_model_by_setting
from pathlib import Path
from string import Template
from service import FactorValueService, MarketNewsService
from utils.common import send_feishu_markdown_message, get_date_by_n, get_today
from utils.data_loader import databull

# 获取当前 Python 文件所在目录
CURRENT_DIR = Path(__file__).parent

prompt_quant_decision = ""

prompt_template = Path(CURRENT_DIR / './prompt_market_overall_analysis.md').read_text(encoding='utf-8')

def job_market_overall_analysis(send_feishu=False):

    staff = get_model_by_setting(_setting_name='stock_tech_analysis')
    staff.set_response_text()

    trade_date = FactorValueService.get_latest_trading_date()
    staff.role_base = prompt_quant_decision

    # 获取大盘数据
    sh_index_data = databull.get_index_history("000001", get_date_by_n(-1 * 30), get_today())

    # 4 大模型汇总输出分析报告
    template = Template(prompt_template)

    # 3 获取关联新闻供LLM分析
    relative_news = MarketNewsService.search(keyword='美联储', page_size=30).get('items')
    relative_news = relative_news + MarketNewsService.search(keyword='央行', page_size=30).get('items')
    relative_news = relative_news + MarketNewsService.search(keyword='股市', page_size=30).get('items')

    prompt = template.safe_substitute(
        trade_date=trade_date,
        relative_news=relative_news,
        report_title='宏观策略展望',
        sh_index_data=sh_index_data.to_csv()
    )

    content = staff.ask(question=prompt)

    if send_feishu:
        send_feishu_markdown_message(
            f'AI每日宏观分析 - {trade_date}',
            markdown_text=content
        )

    print(content)

if __name__ == '__main__':

    job_market_overall_analysis(send_feishu=False)
