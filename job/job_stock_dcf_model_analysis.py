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
    stock = databull.get_stock_info(_stock_code, market)
    profile = stock.get('profile', {})
    return profile


def check_analysis_interval(stock_code, interval=3):
    """
    @brief 检查指定个股的分析间隔是否满足要求

    @param stock_code: 个股代码，如"600519.SH"
    @type stock_code: str
    @param interval: 最小分析间隔天数，默认3天
    @type interval: int

    @return: 如果可以进行分析返回True，否则返回False
    @rtype: bool

    @throws: ValueError: 当stock_code为空或interval<=0时抛出

    @example:
        # 检查贵州茅台是否可以进行新一轮分析（间隔至少3天）
        if check_analysis_interval("600519.SH", interval=3):
            logger.info("可以进行DCF分析")
        else:
            logger.info("上次分析时间未满3天，暂缓分析")
    """
    # 参数校验
    if not stock_code or not isinstance(stock_code, str):
        raise ValueError("个股代码不能为空，且必须为字符串类型")
    if interval <= 0:
        raise ValueError(f"分析间隔必须大于0，当前值: {interval}")

    try:
        # 查询该个股最近一次的分析报告
        report = ResearchReportService.get_by_code(stock_code=stock_code, report_type=1)

        # 如果没有历史报告，说明从未分析过，可以进行分析
        if report is None or report.get('content_json') is None:
            logger.info(f"[{stock_code}] 无历史分析记录，允许进行分析")
            return True

        # 处理时间字段为空的情况
        if not report.get('created_at'):
            logger.info(f"[{stock_code}] 历史分析记录缺少创建时间，视为无有效记录，允许进行分析")
            return True

        # 解析时间字符串
        created_at_str = report['created_at']  # 格式: '2026-05-17T12:27:21'
        try:
            from datetime import datetime

            # 处理多种日期格式
            if 'T' in created_at_str:
                # ISO 8601格式: 2026-05-17T12:27:21
                last_analysis_time = datetime.fromisoformat(created_at_str)
            elif ' ' in created_at_str:
                # 常见格式: 2026-05-17 12:27:21
                last_analysis_time = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
            else:
                # 纯日期格式: 2026-05-17
                last_analysis_time = datetime.strptime(created_at_str, '%Y-%m-%d')
        except (ValueError, TypeError) as e:
            logger.info(f"[{stock_code}] 时间格式解析失败: {created_at_str}, 错误: {e}")
            # 如果解析失败，为了安全起见，允许进行分析
            return True

        # 计算时间差
        now = datetime.now()
        time_diff = now - last_analysis_time

        # 检查是否超过指定间隔天数
        if time_diff.days >= interval:
            logger.info(f"[{stock_code}] 距上次分析已过去{time_diff.days}天(≥{interval}天)，允许进行分析")
            return True
        else:
            # 计算还需等待的天数
            remaining_days = interval - time_diff.days
            remaining_hours = int((interval - time_diff.days) * 24 - time_diff.seconds / 3600)
            logger.info(
                f"[{stock_code}] 距上次分析仅{time_diff.days}天(<{interval}天)，还需等待{remaining_days}天{remaining_hours}小时")
            return False

    except Exception as e:
        # 捕获其他未预期的异常，记录日志并返回True（允许分析，避免阻塞流程）
        logger.info(f"[{stock_code}] 检查分析间隔时出现异常: {e}")
        # 可在此处添加日志记录到文件
        return True


def job_stock_dcf_model_analysis(_stock_code, skip_interval=False, send_notification=False):
    if not skip_interval and not check_analysis_interval(_stock_code, interval=dcf_report_date_limit):
        logger.info(f"下一次分析间隔未到，跳过分析，{_stock_code}")
        return False

    staff = get_model_by_setting(_setting_name='stock_dcf_analysis')
    staff.role_base = '你需要根据客户提供的资料对股票进行DCF估值分析，请使用Markdown输出'
    staff.set_response_text()

    trade_date = FactorValueService.get_latest_trading_date()
    stock_info = StockService.get_stock_by_symbol(symbol=_stock_code)
    stock_name = stock_info.get('name')
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
    report_pershare_index = databull.get_stock_financial_data(symbol=_stock_code, start_date=get_date_by_n(finance_report_date_limit * 365), end_date=get_today(), report_type='PershareIndex')

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

    # stock_code = '600667'
    # job_stock_dcf_model_analysis(stock_code, skip_interval=True)

    job_stock_dcf_model_analysis_daily(override=False)
