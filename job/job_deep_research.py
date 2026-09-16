"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import re
import json

from llms import get_model_by_setting
from utils.logger import logger
from utils.common import get_today, get_date_by_n, extract_html
from service import FactorValueService, MarketNewsService
from utils.data_loader import databull
from pathlib import Path
from string import Template
from service.research_report_service import ResearchReportService
from service.stock import StockService
from config import finance_report_date_limit

# 获取当前 Python 文件所在目录
CURRENT_DIR = Path(__file__).parent

prompt_template = Path(CURRENT_DIR / './prompt_deep_research.md').read_text(encoding='utf-8')

# 复用已沉淀的研报 HTML 模板（样式/结构/图表设计固定，仅替换数据）
deep_research_template = Path(CURRENT_DIR / './template_deep_research.html').read_text(encoding='utf-8')

# 注入给大模型的“结构骨架”：只给关键 class 与章节顺序，不塞整份 34k 模板，
# 避免模型被巨型示例带偏、只产出 TL;DR 而不写六大章节。真实样式仍由上方模板在代码侧注入。
deep_research_skeleton = Path(CURRENT_DIR / './template_deep_research_skeleton.md').read_text(encoding='utf-8')


def job_deep_research(_stock_code, save_local_html=False, force=False, interval_days=30):
    # 分析间隔控制：非强制(force)时，若该股票近 interval_days 天内已生成过同类型深度研报，
    # 则跳过整段分析，避免重复消耗大模型算力（默认每月仅分析一次）。
    if not force and ResearchReportService.has_recent_report(_stock_code, report_type=3, days=interval_days):
        logger.info(
            f"[{_stock_code}] 近 {interval_days} 天内已生成深度研报，本次跳过"
            f"（如需强制刷新请传 force=True）。"
        )
        return False

    staff = get_model_by_setting(_setting_name='stock_dcf_analysis')
    staff.role_base = '你需要根据客户提供的资料对股票进行分析'
    staff.set_response_text()
    # 深度研究研报：模型需输出 TL;DR + 六大章节 + 财务趋势 + 免责声明（含 5 个 data-chart），
    # 给到 24K 输出预算，避免长研报被截断在章节中途。
    staff.set_max_tokens(24576)

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
        report_pershare_index=report_pershare_index,
        deep_research_skeleton=deep_research_skeleton
    )

    logger.info(f"传入大模型进行分析：{stock_name}【{_stock_code}】，大模型版本：{staff.model}")

    content = staff.ask(question=prompt)

    report_html = _assemble_report(extract_html(content), stock_name, _stock_code, trade_date)

    if save_local_html:
        with open(f'{_stock_code}_deep_research.html', 'w', encoding='utf-8') as f:
            f.write(report_html)
        with open(f'{_stock_code}_deep_research_raw.html', 'w', encoding='utf-8') as f:
            f.write(content)

    data = {
        "report_type": 3,
        "stock_code": _stock_code,
        "stock_name": stock_name,
        "title": f"{_stock_code}-{stock_name}_deep_research.md",
        "broker_name": staff.model,
        "analyst_name": "llm",
        "publish_time": get_today(),
        "content_text": report_html,
        "content_json": {},
        "rating": "-",
    }

    result = ResearchReportService.add(data)

    return True


def _esc(s):
    """转义 HTML 特殊字符，避免公司名中的 & < > 破坏结构。"""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _fmt_date(d):
    if not d:
        return ''
    try:
        return f"{d.year}年{d.month}月{d.day}日"
    except AttributeError:
        return str(d)[:10]


def _build_header(stock_name, stock_code, trade_date):
    """代码确定性生成标题块：container + header + h1 + 副标题。
    不依赖模型是否记得包裹外层标签或正确替换示例标题，彻底避免
    “container 丢失” 与 “标题照搬模板” 两类问题。"""
    return (
        '<div class="container">\n'
        '<header class="report-header">\n'
        f'<h1>{_esc(stock_name)}（{stock_code}）</h1>\n'
        f'<div class="subtitle">深度研究报告 · 卖方研究员级框架 · {_fmt_date(trade_date)}</div>\n'
        '</header>\n'
    )


def _ensure_container(body):
    """确保正文被 <div class="container"> 包裹（模型可能漏写，导致布局/卡片样式失效）。"""
    if '<div class="container">' in body:
        return body
    return '<div class="container">\n' + body + '\n</div>'


def _ensure_header_wrapper(body):
    """若模型未用 <header> 包裹标题（直接给 <h1> + <div class="subtitle">），
    则把开头的标题块包进 <header class="report-header">，保证标题样式生效。"""
    if '<header' in body:
        return body
    pat = re.compile(
        r'(\s*<h1>.*?</h1>\s*(?:<div class="subtitle">.*?</div>\s*)*)'
        r'(?=<div class="section"|<div class="tldr-card"|<!--|\Z)',
        re.S,
    )
    return pat.sub(lambda mm: f'<header class="report-header">{mm.group(1).strip()}</header>\n', body, count=1)


def _strip_model_shell(body):
    """去掉模型可能自带的开头外壳（<div class="container"> + 标题块 header/h1/副标题），
    避免与代码生成的标题块重复或嵌套。"""
    had_container = False
    m = re.match(r'\s*<div class="container">', body)
    if m:
        body = body[m.end():]
        had_container = True
    # 去掉 <header>?<h1>...</h1>?副标题?</header>?
    pat = re.compile(
        r'^\s*(<header[^>]*>)?\s*<h1>.*?</h1>\s*'
        r'(?:<div class="subtitle">.*?</div>\s*)*(</header>)?',
        re.S,
    )
    body = pat.sub('', body, count=1).strip()
    # 去掉原 container 对应的结尾 </div>
    if had_container:
        idx = body.rfind('</div>')
        if idx != -1:
            body = body[:idx] + body[idx + 6:]
    return body


def _repair_json(raw):
    """对括号做容错重平衡：丢弃无法配对的闭合括号，再按剩余未闭合括号逆序补齐。
    用于修复模型偶尔输出的『少写/错位括号』（如 series 数组漏了 ']'）。"""
    stack = []
    out = []
    for ch in raw:
        if ch in '[{':
            stack.append(ch)
            out.append(ch)
        elif ch in ']}':
            if stack and ((ch == ']' and stack[-1] == '[') or (ch == '}' and stack[-1] == '{')):
                stack.pop()
                out.append(ch)
            # 无法配对的闭合括号直接丢弃
        else:
            out.append(ch)
    while stack:
        o = stack.pop()
        out.append(']' if o == '[' else '}')
    return ''.join(out)


def _safe_chart_json(raw):
    """校验并尽力修复模型输出的 data-chart JSON。

    模型偶尔会漏写/错位括号（如 series 数组少了 ']'），导致前端 JSON.parse 抛错、
    图表显示『解析失败』。这里先尝试直接解析；失败则用 _repair_json 容错重平衡；
    若仍无法解析，降级为 empty，由渲染器显示『暂无数据』而非报错。
    """
    try:
        json.loads(raw)
        return raw  # 已是合法 JSON，原样返回
    except Exception:
        pass
    try:
        repaired = _repair_json(raw)
        json.loads(repaired)
        return repaired
    except Exception:
        return '{"empty":true,"msg":"图表数据生成异常，已跳过渲染"}'


def _assemble_report(model_content, stock_name, stock_code, trade_date):
    """将模型生成的研报正文与模板的静态外壳（<head> 样式 + 图表渲染脚本）合并为完整 HTML。

    设计原则：图表脚本（读取 data-chart 属性绘制 ECharts）与标题外壳
    （container / header / h1 / 副标题）**均由代码确定性生成**，不依赖模型是否记得
    包裹外层标签或正确替换示例标题。模型只负责从『核心结论(TL;DR)』开始的正文内容。
    彻底避免：
      - 生成结果没有图表 JS（脚本恒定由模板注入）
      - <div class="container"> 丢失导致显示异常
      - 标题照搬模板示例（中国海洋石油 600938）
    """
    template = deep_research_template
    # 1) 取模型内容中的 <body> 内部；若没有 <body> 标签则把整体当作正文
    m = re.search(r'<body[^>]*>(.*?)</body>', model_content, re.S)
    body = m.group(1) if m else re.sub(r'</?(?:html|head|body)[^>]*>', '', model_content, flags=re.S)
    # 兜底：若模型在最外层夹带了说明性文字（如“以下是研报：”），丢弃正文之前的
    # 非标签内容，避免裸文本出现在标题块与 TL;DR 之间。
    body = re.sub(r'^\s*[^<]+', '', body)
    # 2) 去掉模型可能夹带的 <script>（图表脚本由模板统一注入）
    body = re.sub(r'<script.*?</script>', '', body, flags=re.S).strip()
    # 3) 去掉模型可能自带的标题外壳（防止与代码生成标题重复 / 照搬模板）
    body = _strip_model_shell(body)
    # 4) 代码确定性生成标题块（container + header + h1 + 副标题）
    body = _build_header(stock_name, stock_code, trade_date) + body
    # 5) 双重保险：确保 container 与 header 一定存在
    body = _ensure_container(body)
    body = _ensure_header_wrapper(body)
    # 5.5) 校验并尽力修复模型输出中损坏的 data-chart JSON（模型偶尔漏写/错位括号），
    # 避免前端 JSON.parse 抛错显示『解析失败』；无法修复的降级为 empty 由渲染器显示『暂无数据』。
    body = re.sub(r"data-chart='([^']*)'",
                  lambda m: "data-chart='" + _safe_chart_json(m.group(1)) + "'",
                  body)
    # 6) 模板的 <head>（含 <style> 与 ECharts CDN）与通用渲染脚本
    head = re.search(r'<head>.*?</head>', template, re.S).group(0)
    renderer = re.search(r'<script id="chart-renderer">.*?</script>', template, re.S).group(0)
    return ('<!DOCTYPE html>\n<html lang="zh-CN">\n' + head +
            '\n<body>\n' + body + '\n</body>\n' + renderer + '\n</html>\n')


if __name__ == '__main__':

    # codes = ['603195', '600938', '000001']
    # job_deep_research(_stock_code='000001')

    stocks = StockService.get_monitoring_stock_pool(market='cn', per_page=10000)
    for s in stocks:
        job_deep_research(_stock_code=s['symbol'])
