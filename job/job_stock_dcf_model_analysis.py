"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import json

from llms import get_model_by_setting
from utils.logger import logger
from utils.common import get_today, get_date_by_n
from service import StockService, FactorValueService, MarketNewsService
from service import ResearchReportService, JobService
from utils.redis_obj import redis_obj
from utils.data_loader import databull
from pathlib import Path
from string import Template
from config import finance_report_date_limit, dcf_report_date_limit

# 获取当前 Python 文件所在目录
CURRENT_DIR = Path(__file__).parent

prompt_template = Path(CURRENT_DIR / './prompt_stock_dcf_analysis.md').read_text(encoding='utf-8')


def get_stock_detail(_stock_code, market):
    return databull.get_company(_stock_code, market)


def job_stock_dcf_model_analysis(_stock_code, skip_interval=False, send_notification=False):
    # 分析间隔控制：非强制(force)时，若该股票近 interval_days 天内已生成过同类型深度研报，
    # 则跳过整段分析，避免重复消耗大模型算力（默认每月仅分析一次）。
    if not skip_interval and ResearchReportService.has_recent_report(_stock_code, report_type=1, days=dcf_report_date_limit):
        logger.info(
            f"[{_stock_code}] 近 {dcf_report_date_limit} 天内已生成深度研报，本次跳过"
            f"（如需强制刷新请传 force=True）。"
        )
        return False

    staff = get_model_by_setting(_setting_name='stock_dcf_analysis')
    staff.role_base = '你需要根据客户提供的资料对股票进行DCF估值分析，请使用Markdown输出'
    staff.set_response_text()

    trade_date = FactorValueService.get_latest_trading_date()
    stock_info = databull.get_company(_stock_code)
    stock_name = stock_info.get('company_name')

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

    # 2 获取股票基础信息
    stock_detail = get_stock_detail(_stock_code=_stock_code, market=stock_info.get('market'))

    # 3 获取关联新闻供LLM分析
    relative_news = MarketNewsService.search(stock_code=_stock_code, page_size=30)

    # 获取财务报告数据
    report_pershare_index = databull.get_stock_financial_data(symbol=_stock_code,
                                                              start_date=get_date_by_n(finance_report_date_limit * 365),
                                                              end_date=get_today(), report_type='PershareIndex')

    # 4 大模型汇总输出分析报告
    template = Template(prompt_template)

    prompt = template.safe_substitute(
        stock_name=stock_name,
        stock_code=_stock_code,
        stock_detail=stock_detail,
        today=trade_date,
        market_data=market_data.to_csv(),
        relative_news=relative_news,
        report_pershare_index=report_pershare_index
    )

    logger.info(f"传入大模型进行DCF分析：{stock_name}【{_stock_code}】，大模型版本：{staff.model}")

    content = staff.ask(question=prompt)

    # completion_resp = staff.create_completion_with_tools(messages=[
    #     {'role': 'system', 'content': staff.role_base},
    #     {'role': 'user', 'content': prompt}
    # ], )
    # content = completion_resp.get('final_answer')

    # 提取报告里面的股价预测数据
    report_extra = dcf_report_extra(_stock_code, content)

    # 1. 单条插入
    data = {
        "report_type": 1,
        "stock_code": _stock_code,
        "stock_name": stock_name,
        "title": f"{_stock_code}-{stock_name}-dcf-report.md",
        "broker_name": staff.model,
        "analyst_name": "llm",
        "publish_time": get_today(),
        "content_text": content,
        "content_json": report_extra,
        "rating": "-",
    }

    result = ResearchReportService.add(data)

    # logger.info(content)

    return True


def job_stock_dcf_model_analysis_daily(override=False):
    # 删除dcf的缓存
    redis_obj.delete('dcf_valuation_report')

    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)

    # 循环对个股进行每日挖掘
    for stock in stocks:
        # 发送分析任务到MQ
        JobService.send_job({
            'job_func': 'job_stock_dcf_model_analysis',
            'job_args': {
                '_stock_code': stock['symbol'],
                'skip_interval': False,
                'send_notification': False
            }
        })
        logger.info(f"send dcf analysis of {stock['symbol']}")


def dcf_report_extra(_stock_code, report_content):
    """
    从dcf报告提取股价预期
    :param _stock_code:
    :param report_content:
    :return:
    """
    staff = get_model_by_setting(_setting_name='stock_dcf_analysis_extra')
    staff.role_base = '你需要从dcf报告提取股价预期，使用JSON输出'
    question = f"""
    请严格输出具体的价格，不要给35-40这样子模棱两可的数据
    价格输出不要用任何单位，就纯数字输出
    报告原文：{report_content},"""
    question += """输出JSON格式参考！
    {
        "每股内在价值": {
          "中性情景": "40",
          "保守情景": "28",
          "乐观情景": "55"
        }，
        "当前股价": "54.77",
        "估值判断": "当前股价合理偏低，但未出现显著低估，安全边际较薄。建议逢低布局，关注回调至40-45元区间的加仓机会。"
    }
    """
    staff.set_response_json()
    res_json = staff.ask(question)
    return json.loads(res_json)


if __name__ == '__main__':
    stock_code = '600549'
    job_stock_dcf_model_analysis(stock_code, skip_interval=True)

    # job_stock_dcf_model_analysis_daily(override=False)
