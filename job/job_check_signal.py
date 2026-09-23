"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import json

from service import JobService
from service import StockService, FactorValueService, FactorSelectorService, ResearchReportService
from service.factor_desc import factor_descriptions
from llms import get_model_by_setting
from utils.logger import logger
from utils.common import get_date_by_n, get_today
from pathlib import Path
from string import Template
from utils.data_loader import databull

# 获取当前 Python 文件所在目录
CURRENT_DIR = Path(__file__).parent

prompt_template = Path(CURRENT_DIR / './prompt_stock_tech_analysis.md').read_text(encoding='utf-8')

# 定义映射字典：将中文阶段映射为数字
PHASE_MAPPING = {
    "吸筹阶段": 1,
    "洗盘阶段": 2,
    "拉升阶段": 3,
    "出货阶段(初期)": 5,
    "出货阶段 (初期)": 5,
    "出货阶段(末期)": 6,
    "出货阶段 (末期)": 6
}

def job_check_signal(_stock_code):

    stock_info = StockService.get_stock_by_symbol(symbol=_stock_code)
    assert stock_info is not None

    # 获取最新交易日的因子数据
    trade_date = FactorValueService.get_latest_trading_date()
    factors = FactorSelectorService.get_tech_factors_for_stock(_stock_code, trade_date)

    # 获取分析报告
    dcf_report = ResearchReportService.get_by_code(stock_code=_stock_code, report_type=1)

    staff = get_model_by_setting(_setting_name='stock_tech_analysis')
    staff.set_response_json()

    trade_date = FactorValueService.get_latest_trading_date()
    stock_name = stock_info.get('name')
    start_date = get_date_by_n(-360, _format='%Y%m%d') # 获取120天的行情
    end_date = FactorValueService.get_latest_trading_date().strftime('%Y%m%d')

    # 公司基本信息
    # SDK 的 get_company_profile 返回 {code, data} 信封，取内层 data 交给大模型
    _profile_resp = databull.get_company_profile(_stock_code, stock_info.get('market'))
    profile = _profile_resp.get('data') if isinstance(_profile_resp, dict) else _profile_resp

    # 1 数据预处理 - 入库行情、新闻、题材、财报、技术因子、动量数据
    try:
        market_data = databull.get_stock_history(
            symbol=_stock_code,
            start_date=start_date,
            end_date=end_date,
            market=stock_info.get('market')
        )
        # 需要重置索引，否则输出的数据没有日期
        market_data = market_data.reset_index()
    except Exception as e:
        raise f"数据获取失败: {e}"

    # 4 大模型汇总输出分析报告
    template = Template(prompt_template)

    prompt = template.safe_substitute(
        stock_name=stock_name,
        stock_code=_stock_code,
        today=trade_date,
        market_data=market_data.to_csv(),
        tech_factors=factors,
        factor_descriptions=factor_descriptions,
        dcf_report=dcf_report,
        profile=profile
    )

    logger.info(f"传入大模型进行分析：{stock_name}【{_stock_code}】，大模型版本：{staff.model}")

    content = staff.ask(question=prompt)
    content_json = json.loads(content)

    # "吸筹阶段|洗盘阶段|拉升阶段|出货阶段"
    main_force_behavior_phase_str = content_json['技术面深度诊断'].get('主力行为阶段', '')
    main_force_behavior_phase_str = main_force_behavior_phase_str.replace(' ', '')

    # 如果匹配不到，默认设为 0 (代表未知/其他)
    main_force_behavior_phase_int = PHASE_MAPPING.get(main_force_behavior_phase_str, 0)

    # 主力行为阶段写入因子库
    FactorValueService.create(
        trade_date,
        ticker=_stock_code,
        factor_name='main_force_behavior_phase',
        value=main_force_behavior_phase_int
    )

    logger.info(content_json)

    # 刷新股票概念
    StockService.upsert_stock({
        'symbol': _stock_code,
        'concepts': content_json.get('股票概念', {}),
    })

    # 1. 单条插入
    data = {
        "report_type": 2,
        "stock_code": _stock_code,
        "stock_name": stock_name,
        "title": f"{_stock_code}-{stock_name}-tech-report.md",
        "broker_name": staff.model,
        "analyst_name": "llm",
        "publish_time": get_today(),
        "content_json": content_json,
        "rating": "-",
    }

    result = ResearchReportService.add(data)

def job_check_signal_daily():

    stocks = StockService.search_stocks(securities_type='stock', monitoring=1, per_page=10000)

    # 循环对个股进行每日挖掘
    for stock in stocks:
        JobService.send_job({
            'job_func': 'job_check_signal',
            'job_args': {
                '_stock_code': stock['symbol'],
            }
        })
        logger.info(f"send signal analysis of {stock['symbol']}")

if __name__ == '__main__':

    # stock_code = '600362'
    # job_check_signal(_stock_code=stock_code)

    job_check_signal_daily()
