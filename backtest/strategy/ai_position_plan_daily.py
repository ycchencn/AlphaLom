"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import json
from llms import get_model_by_setting
from service import FactorValueService
from service import InvestmentPortfolioService, PortfolioAssetsService, StockService, MarketNewsService
from utils.common import get_today, get_date_by_n
from string import Template
from utils.common import send_feishu_markdown_message
from typing import List, Dict
from utils.gen_feishu_report import generate_feishu_report
from config import strategy_setting
from utils.data_loader import databull
from service.dialogue_manager import DialogueManager
from utils.logger import logger

prompt_quant_decision = """
'你现在是一名金融分析师，你对股票市场、金融市场、投资策略和财务规划有深厚的理解。'
'你能基于用户的基础数据给出股票投资决策帮助，请在这个角色下为我解答以下问题。'
'请以JSON格式输出'
"""


def adjust_position_plan(position_plan, holding_assets_dict):
    assert 'actions' in position_plan

    for action in position_plan['actions']:

        # {'action': 'sell', 'reason': '持仓亏损，技术形态偏弱，且行业竞争加剧，为控制风险分批减仓。', 'quantity': 10, 'stock_code': '688256', 'stock_name': '寒武纪'}
        if action['quantity'] == 0:
            continue

        lot_size = get_lot_size(action['stock_code'])

        # 获取当前持仓数量
        if action['stock_code'] in holding_assets_dict:
            current_qty = holding_assets_dict[action['stock_code']]['position_size']
        else:
            current_qty = 0

        # 计算调整后数量（向下取整到最接近的LOT_SIZE）
        adjusted_qty = (action['quantity'] // lot_size) * lot_size

        # 对于卖出操作，不能超过当前持仓
        if action['action'] == 'sell':
            adjusted_qty = min(adjusted_qty, current_qty)

        # 确保至少为1手（除非清仓）
        if adjusted_qty <= 0 and current_qty > 0:
            adjusted_qty = lot_size if current_qty >= lot_size else current_qty

        # 修正操作手数
        action['quantity'] = adjusted_qty

    return position_plan


def get_lot_size(stock_code):
    """根据股票代码获取市场手数"""
    if stock_code.startswith('688'): return 200  # 沪市
    if stock_code.startswith(('6', '9')):
        return 100  # 沪市
    elif stock_code.startswith(('0', '3')):
        return 100  # 深市
    else:
        return 100  # 默认


def job_position_plan_daily(portfolio_id=None, send_feishu=False):
    if portfolio_id is None:
        return False

    chat_id = f"prof_analysis_chat_{portfolio_id}"
    index_data = databull.get_index_history(index_code='000001', start_date=get_date_by_n(-30), end_date=get_today())

    # 获取持仓信息
    investment_info = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    holding_assets = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    holding_assets_dict = {ass['stock_code']: ass for ass in holding_assets}

    # 调仓计划
    position_plan_old = investment_info.get('position_plan')

    # 大模型设置
    llm_setting = investment_info.get('llm_setting')

    # 根据策略获取大模型对象
    staff = get_model_by_setting(_setting=llm_setting)
    staff.role_base = prompt_quant_decision
    staff.set_response_json()

    # 大模型提示词
    llm_prompt_str = investment_info.get('llm_prompt')

    # 可用资金
    available_money = int(investment_info.get('current_cash'))

    # 股票池
    stock_pool = StockService.get_monitoring_stock_pool(per_page=strategy_setting.get('stock_pool'))

    # 近期新闻
    recent_news = MarketNewsService.get_by_time_range(limit=strategy_setting.get('news_limit'))

    template = Template(llm_prompt_str)
    holdings_text = format_holdings_text(holding_assets)
    stock_pool_text = format_stock_pool_text(stock_pool)

    logger.info(f"#{portfolio_id}, 传入大模型进行调仓分析，大模型版本：{staff.model}")

    # 1. 获取历史上下文
    history = DialogueManager.get_context(chat_id)
    # history = []

    if len(history) == 0:
        # 用户预设 prompt
        prompt = template.safe_substitute(
            current_date=get_today(),
            market_data_csv=index_data,
            holdings_text=holdings_text,
            stock_pool_text=stock_pool_text,
            available_money=available_money,
            stock_position_limit=strategy_setting.get('stock_position_limit', 8),
            position_plan=position_plan_old,
            recent_news=json.dumps(recent_news, ensure_ascii=False)
        )
    else:
        index_last = databull.get_last_tick(symbol='000001', tick_type='index')
        prompt = (f"今天是：{get_today()}\n"
                  f"当前持仓：{holdings_text}\n"
                  f"可用资金：{available_money}\n"
                  f"上证指数最新数据：{index_last}\n"
                  f"继续思考调仓计划")

    # 2. 构建请求消息列表（包含 system 和历史 + 当前消息）
    messages = history.copy()
    messages.append({"role": "user", "content": prompt})

    # 请求大模型
    assistant_reply = staff.create_completion(messages=messages)
    reply_content = assistant_reply.choices[0].message.content

    # 4. 将新的一轮对话追加到上下文
    new_messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": reply_content}
    ]
    # messages.append({"role": "assistant", "content": reply_content})

    # 记录上下文
    DialogueManager.append_messages(chat_id, new_messages)

    ai_ans = reply_content.replace("```json", "")
    ai_ans = ai_ans.replace("```", "")
    answer_json = json.loads(ai_ans)

    logger.info(answer_json)

    logger.info(f"#{portfolio_id}, 分析完成，调仓建议写入数据库，模型版本：{staff.model}")

    position_plan = adjust_position_plan(answer_json, holding_assets_dict)

    InvestmentPortfolioService.update_by_portfolio_id(portfolio_id, {
        'position_plan': position_plan,
        'desc': position_plan.get('position_style'),
    })

    if send_feishu:
        report_md = generate_feishu_report(position_plan)
        send_feishu_markdown_message(f"{investment_info.get('name')} - 交易复盘与策略", markdown_text=report_md)

    return True


def format_holdings_text(holdings: List[Dict]) -> str:
    if not holdings:
        return "无持仓。"
    lines = []
    for h in holdings:
        line = (
            f"- {h['stock_code']} ({h['asset_name']}): "
            f"持仓 {h['position_size']} 股，成本 {h['cost_price']:.2f} 元，最新收盘价 {h['position_price']:.2f} 元"
        )
        lines.append(line)
    return "\n".join(lines)


def format_stock_pool_text(stock_pool: List[Dict]) -> str:
    if not stock_pool:
        return "空池（无可用标的）"
    items = [f"{s['symbol']} ({s['name']})" for s in stock_pool]
    return ", ".join(items)


def job_position_plan_daily_all(trade_day_override=False):
    """
    交易日运行策略
    """

    # 判断交易日
    if FactorValueService.is_trading_day() is False and trade_day_override is False:
        return

    portfolios = InvestmentPortfolioService.get_all()

    for prof in portfolios:
        # 跳过没有设置大模型的策略
        if prof.get('llm_setting') is None:
            continue
        if prof.get('position_plan') is not None and len(prof.get('position_plan')) > 0:
            logger.info(f"调仓计划已存在，跳过。#{prof.get('portfolio_id')}")
            continue
        try:
            job_position_plan_daily(portfolio_id=prof.get('portfolio_id'))
        except Exception as e:
            logger.warn(f"调仓计划运行失败：{e}")
            continue


if __name__ == '__main__':

    job_position_plan_daily_all(trade_day_override=True)

    # job_position_plan_daily(portfolio_id=1, send_feishu=False)
