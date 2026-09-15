"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import json, re
from bs4 import BeautifulSoup
from llms import get_model_by_setting
from utils.logger import logger
from utils.common import get_today, get_date_by_n
from service import StockService, FactorValueService, MarketNewsService
from utils.data_loader import databull
from pathlib import Path
from string import Template
from config import finance_report_date_limit

# 获取当前 Python 文件所在目录
CURRENT_DIR = Path(__file__).parent

prompt_template = Path(CURRENT_DIR / './prompt_deep_research.md').read_text(encoding='utf-8')


def extract_html(llm_response: str, prefer_code_block: bool = True) -> str:
    """
    从大模型回复中提取 HTML 内容

    Args:
        llm_response: 大模型的原始回复文本
        prefer_code_block: 是否优先提取 ```html 代码块
    """
    if prefer_code_block:
        # 优先匹配 ```html 代码块
        pattern = r"```\s*(?:html)?\s*\n?(.*?)```"
        match = re.search(pattern, llm_response, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # 尝试匹配完整 HTML 文档
    full_html = re.search(
        r"(<!DOCTYPE[^>]*>\s*)?<html[^>]*>.*?</html>",
        llm_response, re.DOTALL | re.IGNORECASE
    )
    if full_html:
        return full_html.group(0)

    # 尝试匹配 <body>...</body>
    body = re.search(r"<body[^>]*>.*?</body>", llm_response, re.DOTALL | re.IGNORECASE)
    if body:
        return body.group(0)

    # 最后用 BeautifulSoup 兜底，提取看起来像 HTML 的部分
    soup = BeautifulSoup(llm_response, "html.parser")
    # 找第一个 HTML 标签作为起点
    for tag in soup.find_all(True):
        if tag.name in ('html', 'body', 'div', 'main', 'section'):
            return str(tag)

    # 如果什么都没找到，返回去空白后的原文
    return llm_response.strip()


def job_deep_research(_stock_code):

    staff = get_model_by_setting(_setting_name='stock_dcf_analysis')
    staff.role_base = '你需要根据客户提供的资料对股票进行分析'
    staff.set_response_text()
    # 深度研究研报较长，显式提高输出 token 上限，避免被截断
    staff.set_max_tokens(8192 * 5)

    stock_info = databull.get_company(_stock_code)
    stock_name = stock_info.get('company_name')
    trade_date = FactorValueService.get_latest_trading_date()
    start_date = get_date_by_n(-120, _format='%Y%m%d')  # 获取120天的行情
    end_date = FactorValueService.get_latest_trading_date().strftime('%Y%m%d')

    # 1 数据预处理 - 入库行情、新闻、题材、财报、技术因子、动量数据
    try:
        market_data = databull.get_history(
            symbol=_stock_code,
            start_date=start_date,
            end_date=end_date)
        # 需要重置索引，否则输出的数据没有日期
        market_data = market_data.reset_index()
    except Exception as e:
        raise f"数据获取失败: {e}"

    # 3 获取关联新闻供LLM分析
    relative_news = MarketNewsService.search(stock_code=_stock_code, page_size=30)

    # 获取财务报告数据
    report_pershare_index = databull.get_stock_financial_data(
        symbol=_stock_code,
        start_date=get_date_by_n(finance_report_date_limit * 365),
        end_date=get_today(), report_type='PershareIndex'
    )

    # 4 大模型汇总输出分析报告
    template = Template(prompt_template)

    prompt = template.safe_substitute(
        stock_name=stock_name,
        stock_code=_stock_code,
        today=trade_date,
        market_data=market_data.to_csv(),
        relative_news=relative_news,
        report_pershare_index=report_pershare_index
    )

    logger.info(f"传入大模型进行分析：{stock_name}【{_stock_code}】，大模型版本：{staff.model}")

    content = staff.ask(question=prompt)

    with open('rs.html', 'w', encoding='utf-8') as f:
        f.write( extract_html(content))

    return True


if __name__ == '__main__':
    job_deep_research(_stock_code='600938')
