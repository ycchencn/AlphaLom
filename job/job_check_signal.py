"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""
import json
import re

from service import JobService
from service import StockService, FactorValueService, FactorSelectorService, ResearchReportService
from service.factor_desc import factor_descriptions
from llms import get_model_by_setting
from utils.logger import logger
from utils.common import get_date_by_n, get_today, extract_json_object
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


def _brief_factor_descriptions(tech_factors):
    """
    把因子说明压成紧凑版，避免把整份 factor_descriptions 全量塞进 prompt：
    1) 只保留「当前股票实际存在的因子」；
    2) 去掉 formula / usage 两栏（对技术面研判基本是废信息），仅留中文名 + 一句话描述。
    """
    if not isinstance(tech_factors, dict):
        return '（无可用因子）'
    present = set(tech_factors.keys())
    brief = []
    for item in factor_descriptions:
        if not isinstance(item, dict):
            continue
        if item.get('field') in present:
            brief.append(f"{item.get('name')}({item.get('field')})：{item.get('description', '')}")
    return '\n'.join(brief) if brief else '（无可用因子）'


def _trim_dcf_report(dcf_report):
    """
    从 DCF 深度研报里只抽「估值结论」，避免把整篇 markdown 研报（content_text）塞进 prompt。
    技术面分析只需要：投资评级 + 三情景内在价值 + 当前股价 + 估值判断。
    """
    if not dcf_report:
        return '（暂无 DCF 深度研报，请仅依据技术面与行情判断）'
    parts = [f"投资评级：{dcf_report.get('rating') or '（未评级）'}"]
    cj = dcf_report.get('content_json')
    if isinstance(cj, dict):
        val = cj.get('每股内在价值')
        if isinstance(val, dict):
            parts.append(
                f"每股内在价值（中性/保守/乐观）："
                f"{val.get('中性情景')}/{val.get('保守情景')}/{val.get('乐观情景')}"
            )
        if cj.get('当前股价'):
            parts.append(f"DCF 模型参考股价：{cj.get('当前股价')}")
        if cj.get('估值判断'):
            parts.append(f"估值结论：{cj.get('估值判断')}")
    title = dcf_report.get('title')
    if title:
        parts.append(f"（来源研报：{title}）")
    return '\n'.join(parts)


def _extract_json_object(text):
    """
    容忍地提取 JSON 对象。实现已收口到 utils.common.extract_json_object
    （与 job_news_digest 共用同一份，避免两处各自漂移），这里保留原名做转发。
    """
    return extract_json_object(text)


def job_check_signal(_stock_code):

    stock_info = StockService.get_stock_by_symbol(symbol=_stock_code)
    assert stock_info is not None

    # 获取最新交易日的因子数据
    trade_date = FactorValueService.get_latest_trading_date()
    factors = FactorSelectorService.get_tech_factors_for_stock(_stock_code, trade_date)

    # 获取 DCF 深度研报（只抽估值结论，避免把整篇 markdown 塞进 prompt）
    dcf_report = ResearchReportService.get_by_code(stock_code=_stock_code, report_type=1)

    staff = get_model_by_setting(_setting_name='stock_tech_analysis')
    staff.role_base = (
        '你是一位资深技术分析师与量化交易专家。'
        '请使用系统挂载的 MCP 工具主动获取实时行情、新闻与市场情绪数据后再做分析，'
        '最终严格按用户要求的 JSON 格式返回；涉及实时股价请务必调用 get_stock_history 核实，不要编造数据。'
    )
    # agent 循环用 text 模式：保证模型可自由调用工具（json_object 模式在某些平台会抑制工具调用）。
    # 最终 JSON 由 _extract_json_object 容忍解析；失败时降级 ask() 切回 json 模式兜底。
    staff.set_response_text()

    stock_name = stock_info.get('name')

    # 公司基本信息
    # SDK 的 get_company_profile 返回 {code, data} 信封，取内层 data 交给大模型
    _profile_resp = databull.get_company_profile(_stock_code, stock_info.get('market'))
    profile = _profile_resp.get('data') if isinstance(_profile_resp, dict) else _profile_resp

    # 1 紧凑的近期行情快照：仅作「模型未调用工具 / 工具失败时」的兜底基线，
    #    避免把 360 天 CSV 全量塞进 prompt（既省 token，也规避工具默认区间过时问题）。
    #    完整行情由 agent 通过 get_stock_history 工具按需拉取。
    recent_end = trade_date.strftime('%Y%m%d')
    recent_start = get_date_by_n(-30, _format='%Y%m%d')
    recent_quotes = None
    try:
        recent_quotes = databull.get_stock_history(
            symbol=_stock_code, start_date=recent_start, end_date=recent_end,
            market=stock_info.get('market')
        ).reset_index()
    except Exception as e:
        logger.warning(f"[{_stock_code}] 紧凑行情快照获取失败（将不提供兜底基线）：{e}")
    history_hint = (
        f"建议通过 get_stock_history 拉取 {recent_start} ~ {recent_end}"
        f"（可扩展到近 250 个交易日）的日线，用于判断均线/形态/量价与确认当前股价"
    )

    # 2 组装 prompt 并交给大模型（agent 模式：模型可调用 MCP 工具自主多轮取数）
    template = Template(prompt_template)
    prompt = template.safe_substitute(
        stock_name=stock_name,
        stock_code=_stock_code,
        today=trade_date,
        tech_factors=factors,
        factor_descriptions=_brief_factor_descriptions(factors),
        dcf_report=_trim_dcf_report(dcf_report),
        profile=profile,
        recent_quotes=recent_quotes.to_csv() if recent_quotes is not None else '（未获取到）',
        history_hint=history_hint,
    )

    logger.info(f"传入大模型进行技术面分析（agent模式）：{stock_name}【{_stock_code}】，模型：{staff.model}")

    content = ''
    try:
        resp = staff.create_completion_with_tools(messages=[
            {'role': 'system', 'content': staff.role_base},
            {'role': 'user', 'content': prompt},
        ])
        content = (resp.get('final_answer') or '').strip()
        tool_calls = resp.get('tool_calls') or []
        if tool_calls:
            summary = ', '.join(
                f"{t['function_name']}({json.dumps(t['parameters'], ensure_ascii=False)})"
                for t in tool_calls
            )
            logger.info(f"[{_stock_code}] 技术面 Agent 共 {len(tool_calls)} 次工具调用：{summary}")
        else:
            logger.info(f"[{_stock_code}] 技术面 Agent 未使用工具（直接作答）")
        if resp.get('truncated'):
            logger.warning(f"[{_stock_code}] 技术面 Agent 达到工具调用轮数上限，结论可能不完整")
    except Exception as e:
        # agent 模式异常（如 MCP 不可达 / json 与工具冲突）时降级为单轮 ask（json 模式兜底），
        # 保证研报仍可产出
        logger.warning(f"[{_stock_code}] 技术面 Agent 调用失败，降级为单轮模式：{e}")
        staff.set_response_json()
        content = staff.ask(question=prompt)

    content_json = _extract_json_object(content)
    if content_json is None:
        logger.error(f"[{_stock_code}] 技术面分析未产出合法 JSON，跳过入库")
        return

    # "吸筹阶段|洗盘阶段|拉升阶段|出货阶段"
    tech_diag = content_json.get('技术面深度诊断') or {}
    main_force_behavior_phase_str = (tech_diag.get('主力行为阶段') or '').replace(' ', '')

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

    stock_code = '600362'
    job_check_signal(_stock_code=stock_code)

    # job_check_signal_daily()
