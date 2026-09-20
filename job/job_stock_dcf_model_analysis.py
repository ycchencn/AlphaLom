"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import json
import re

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

    # 获取财务报告数据 PershareIndex
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

    ResearchReportService.add(data)

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


def _clean_numeric_string(value):
    """清洗大模型返回的「带单位 / 含杂质」的数字字符串，仅保留可转 float 的数字。
    例：'11.16元' -> '11.16'；'约 132.6 元/股' -> '132.6'；'58.7' -> '58.7'。
    无法提取有效数字时原样返回，交由下游继续报错（fail-safe，避免静默成 0）。"""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    # 已经是干净数字则直接返回
    try:
        float(s)
        return s
    except ValueError:
        pass
    # 去掉常见单位 / 货币符号 / 空白（注意：不含「万」，避免每股价格被错误缩放）
    cleaned = re.sub(r'[元/股￥¥$人民币RMB港元港币美元美圆块刀\s]', '', s, flags=re.IGNORECASE)
    # 提取第一个合法数字片段（支持负数、小数）
    m = re.search(r'[-+]?\d*\.?\d+', cleaned)
    return m.group(0) if m else value


def _sanitize_dcf_report_extra(obj):
    """对 dcf_report_extra 返回的估值 JSON 做数值清洗：
    把每股内在价值的三种情景与当前股价中的单位 / 杂质剥离，保证下游 float() 不报错。"""
    if not isinstance(obj, dict):
        return obj
    valuation = obj.get('每股内在价值')
    if isinstance(valuation, dict):
        for key in ('乐观情景', '中性情景', '保守情景'):
            if key in valuation:
                valuation[key] = _clean_numeric_string(valuation[key])
    if '当前股价' in obj:
        obj['当前股价'] = _clean_numeric_string(obj['当前股价'])
    return obj


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
    价格一律只输出纯数字字符串，禁止出现「元」「元/股」「￥」「$」「万」等任何单位或货币符号
    若原文为区间（如35-40），请取单一代表值
    只输出 JSON，不要附加任何解释文字
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
    try:
        parsed = json.loads(res_json)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"[{_stock_code}] dcf_report_extra JSON 解析失败，估值数据降级为空: {e}")
        return {}
    return _sanitize_dcf_report_extra(parsed)


if __name__ == '__main__':
    stock_code = '002185'
    job_stock_dcf_model_analysis(stock_code, skip_interval=True)

    # job_stock_dcf_model_analysis_daily(override=False)
