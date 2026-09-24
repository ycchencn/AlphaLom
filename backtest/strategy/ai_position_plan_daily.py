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
from databull import DataBullError
from utils.data_loader import databull
from service.dialogue_manager import DialogueManager
from utils.logger import logger
from config import llm_max_tokens

prompt_quant_decision = """
'你现在是一名金融分析师，你对股票市场、金融市场、投资策略和财务规划有深厚的理解。'
'你能基于用户的基础数据给出股票投资决策帮助，请在这个角色下为我解答以下问题。'
'请以JSON格式输出'
"""

# ===== Agent 调研阶段 =====
# 设计：两阶段而不是一阶段。
#   阶段一（调研）：挂 MCP 工具，模型自由决定查什么，多轮直到自己收口 → 得到一段自然语言结论。
#   阶段二（决策）：沿用原来的单轮调用，要求严格 JSON → 保证落库契约不变。
# 为什么不合并成一阶段：`response_format=json_object` 与 `tools` 同时下发时，
#   部分平台会让模型「直接编一个 JSON」而完全不调工具（工具形同虚设），且解析失败风险高。
#   拆开后，落库链路（json.loads → adjust_position_plan → update）一行都不用改，回归面最小。
prompt_agent_research = """你是一名资深 A 股投资经理，正在为「$portfolio_name」这个组合做调仓前的调研。

## 组合当前状态
- 当前持仓：
$holdings_text
- 可用资金：$available_money 元
- 组合定位：$portfolio_desc

## 你要做的事
在给出调仓结论之前，**先自己去查数据**。你可以调用工具获取行情、财务与个股详情。
请围绕下面这些问题做调研：

1. 持仓中每只标的**最近 20 个交易日**的走势如何？是否跌破关键均线、是否放量下跌？
2. 大盘（上证指数 000001）近期是偏强还是偏弱？当前处于什么位置？
3. 对考虑买入/卖出的标的，确认它最近的**收盘价与涨跌幅**，不要凭记忆猜价格。
4. 如果某只标的基本面可疑（业绩、负债、行业景气度），查一下它的财务数据。

## ⚠️ 日期纪律（最重要，务必遵守）
**今天是 $current_date。** 查行情时必须让查询区间**覆盖到最近这几天**。

工具的 start_date / end_date 参数有各自的默认值，**不要依赖默认值，也不要凭想象填**。
请显式传入形如 `start_date=$recent_start, end_date=$current_compact` 的区间，
即「从最近一段时间的起点 一直查到今天」。

反面例子（会导致你拿到一份**过时的**数据、进而做出错误判断）：
- 只传一个过去的 date，或把区间填在几个月甚至一年前；
- 不传 end_date 就以为它等于今天（它有自己的默认值）。

每查到一份数据，先瞄一眼返回里的日期，确认它确实是**最近的交易日**再往下用。

## 输出要求
用**中文自然语言**输出你的调研结论，包含：
- 每只持仓标的的近期走势判断（用你查到的真实数字，**并标明该数字对应的日期**）
- 大盘环境判断
- 你认为接下来应该重点考虑买入、卖出还是继续持有，以及理由

⚠️ 只基于你**实际查到**的数据下结论。查不到的就明说「未获取到」，**不要编造数字**。
⚠️ 调研要克制：不要为了填满内容而反复查同样的数据，通常 5~10 次工具调用足够。
"""


def adjust_position_plan(position_plan, holding_assets_dict):
    assert 'actions' in position_plan

    valid_actions = []
    for action in position_plan['actions']:
        # {'action': 'sell', 'reason': '持仓亏损，技术形态偏弱，且行业竞争加剧，为控制风险分批减仓。', 'quantity': 10, 'stock_code': '688256', 'stock_name': '寒武纪'}
        
        # 过滤掉无效的 action：quantity 为 0、None 或负数
        if not action.get('quantity') or action['quantity'] <= 0:
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

        # 再次检查调整后的数量是否有效
        if adjusted_qty <= 0:
            continue

        # 修正操作手数
        action['quantity'] = adjusted_qty
        valid_actions.append(action)

    # 用过滤后的 actions 替换原来的
    position_plan['actions'] = valid_actions
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


def run_agent_research(staff, portfolio_info, holdings_text, available_money):
    """
    阶段一：Agent 调研。

    挂上 MCP 工具让大模型自主多轮取数，返回 (调研结论文本, 工具调用轨迹)。
    失败一律降级为「返回空结论」而不是抛异常 —— 调研是增强项，
    它挂掉不应该让整次调仓分析跟着失败（调用方据此退回原来的单轮模式）。

    :return: (research_text, tool_calls)；research_text 为空字符串表示调研未成功
    """
    template = Template(prompt_agent_research)
    today = get_today()                      # 形如 20260923
    recent_start = get_date_by_n(-30)        # 覆盖约 20 个交易日
    prompt = template.safe_substitute(
        portfolio_name=portfolio_info.get('name') or '',
        holdings_text=holdings_text,
        available_money=available_money,
        portfolio_desc=portfolio_info.get('desc') or '（未描述）',
        current_date=today,
        current_compact=today,
        recent_start=recent_start,
    )

    try:
        # ⚠️ 阿里云百炼（qwen）在 response_format=json_object 时**强制校验 prompt 里必须出现
        # "json" 字样**，否则直接 400 InvalidParameter：
        #   "'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'"
        # 调研阶段的本意是自然语言作答，但 staff 在进入本函数前已被 set_response_json() 改过，
        # 这里临时切回 text，避免把 JSON 模式强加给一次「散文式调研」。
        # （此前若不切，调研段 100% 400 并静默降级 —— 表面上不报错，实际 agent 从未生效。）
        prev_format = staff.response_format
        staff.set_response_text()
        try:
            result = staff.create_completion_with_tools([{'role': 'user', 'content': prompt}])
        finally:
            # 恢复 JSON 模式，阶段二的决策调用仍然要严格 JSON
            staff.response_format = prev_format
    except Exception as e:
        logger.warning(f"Agent 调研阶段失败，降级为单轮模式：{e}")
        return '', []

    tool_calls = result.get('tool_calls') or []
    research_text = (result.get('final_answer') or '').strip()

    if result.get('truncated'):
        logger.warning("Agent 调研达到工具调用轮数上限，结论可能不完整")

    # 轨迹写进日志：排查「模型到底查了什么、据此下了什么结论」时这是唯一证据
    if tool_calls:
        summary = ', '.join(
            f"{t['function_name']}({json.dumps(t['parameters'], ensure_ascii=False)})"
            for t in tool_calls
        )
        logger.info(f"Agent 调研共 {len(tool_calls)} 次工具调用：{summary}")
        _warn_if_queries_are_stale(tool_calls, today)
    else:
        logger.info("Agent 调研未产生工具调用（模型直接作答）")

    return research_text, tool_calls


def _warn_if_queries_are_stale(tool_calls, today):
    """
    巡检模型查行情时用的日期区间是否「过时」，只告警不改行为。

    ⚠️ 为什么需要这个：MCP 的 get_stock_history / get_index_history 的 start_date、
    end_date **各自有默认值**（实测默认落在 2025-01-01 ~ 2026-12-31 这种固定区间）。
    模型很可能只传 symbol 而让日期走默认，于是拿到一份几个月前、甚至一年前的行情，
    却照样写出言之凿凿的结论 —— 表面上「有数据」，实际是**在拿旧价格做今天的决策**。

    这种失败不抛异常、不报错，是本次改造里最危险的一类静默错误，所以专门巡检一次。
    """
    today_compact = str(today).replace('-', '')
    try:
        today_int = int(today_compact)
    except ValueError:
        return

    stale = []
    for call in tool_calls:
        params = call.get('parameters') or {}
        # 只看行情类工具：财务数据的报告期本来就滞后，不算过时
        if call.get('function_name') not in ('get_stock_history', 'get_index_history'):
            continue
        end = str(params.get('end_date') or '')
        if not end.isdigit():
            stale.append(f"{call['function_name']} 未显式传 end_date")
            continue
        # 允许 10 个自然日的宽容（长假 + 模型把「最近」理解成上一周）
        gap_days = _days_between(end, today_compact)
        if gap_days is None or gap_days > 10:
            stale.append(f"{call['function_name']}(end_date={end}) 距今 {gap_days} 天")

    if stale:
        logger.warning(
            f"⚠️ Agent 调研存在 {len(stale)} 处可能的过时查询，结论可能基于旧行情："
            + '；'.join(stale)
        )


def _days_between(date_a: str, date_b: str):
    """两个 YYYYMMDD 字符串相差的自然日数，解析失败返回 None。"""
    from datetime import datetime
    try:
        a = datetime.strptime(date_a, '%Y%m%d')
        b = datetime.strptime(date_b, '%Y%m%d')
    except ValueError:
        return None
    return abs((b - a).days)


def job_position_plan_daily(portfolio_id=None, send_feishu=False, use_agent=True):
    """
    每日调仓计划。

    :param use_agent: 是否启用 Agent 调研阶段（默认开）。
        ⚠️ 保留开关而不是写死：调研阶段会多消耗一次「多轮工具调用」的 token，
        模型或平台不支持工具调用时要能一键回退到原来的单轮行为。
    """
    if portfolio_id is None:
        return False

    # 获取持仓信息
    investment_info = InvestmentPortfolioService.get_by_portfolio_id(portfolio_id)
    if not investment_info:
        logger.warning(f"#{portfolio_id}, 组合不存在，跳过调仓分析")
        return False

    # ⚠️ 前置校验：llm_prompt 为空时**必须在这里拦掉**，不能让它流到下面。
    # 崩溃原理：`Template(None)` 本身不报错（__init__ 只是把值存起来），
    # 直到 `safe_substitute()` 内部执行 `self.pattern.sub(convert, self.template)`
    # 才抛 `TypeError: expected string or bytes-like object, got 'NoneType'` ——
    # 也就是 `re.sub` 的第二个参数（被替换文本）是 None。
    # 报错点与根因隔着一层库函数，日志里只能看到一句与业务无关的正则错误。
    # 表定义 `llm_prompt = Column(Text, default='')` 只约束「新增且未显式传值」的行，
    # 存量数据或绕过 ORM 的写入仍可能留下 NULL，所以这里按「可能为 None」防御。
    llm_prompt_str = investment_info.get('llm_prompt')
    # ⚠️ 用 `.strip()` 判空而不是单纯判 None：纯空白（空格/换行）提示词同样无效 ——
    # 它不会抛异常，但会让模板替换产出一个空白 prompt，模型只能凭空编造，
    # 而这种「有输出、无依据」的失败比直接报错更难发现。
    if not llm_prompt_str or not llm_prompt_str.strip():
        # 这属于「未配置」而不是「运行出错」：该组合尚未启用大模型调仓，
        # 用 warning 提示管理员即可，批量任务里由调用方 continue 跳过。
        logger.warning(f"#{portfolio_id}, 未配置 llm_prompt，跳过调仓分析")
        return False

    # 大模型设置
    llm_setting = investment_info.get('llm_setting')

    # 根据策略获取大模型对象
    staff = get_model_by_setting(_setting=llm_setting)
    staff.role_base = prompt_quant_decision
    staff.set_response_json()

    # ⚠️ chat_id 带日期维度：原来的 chat_id 是固定的 prof_analysis_chat_{id}，
    # 而历史上下文会被无差别地喂给下一次分析 → 昨天的行情判断会污染今天。
    # 每天一个会话，天然做到「当天内多轮可续、跨日不串味」。
    chat_id = f"prof_analysis_chat_{portfolio_id}_{get_today()}"

    holding_assets = PortfolioAssetsService.get_all_by_portfolio_id(portfolio_id)
    holding_assets_dict = {ass['stock_code']: ass for ass in holding_assets}

    # 调仓计划
    position_plan_old = investment_info.get('position_plan')

    # 可用资金
    available_money = int(investment_info.get('current_cash'))

    # 股票池：多用户下取「本组合所属用户」自己的池子 —— 组合的 owner 就是
    # investment_info['user_id']。原来这里取的是全局股票池，改造后那会把所有人
    # 的票都当成本策略的候选（A 的策略看得见 B 的自选）。
    # ⚠️ owner 池子为空时**回退到全局并集**：新建用户还没加自选就跑调仓，
    # 硬用空池会让模型在「零候选」下产出空仓计划，而成功返回的空仓比报错更难发现。
    # 定时任务（job_position_plan_daily_all）没有用户上下文，但组合自带 owner，
    # 所以这里不需要用户参数也能正确定位。
    stock_pool = StockService.get_monitoring_stock_pool(
        per_page=strategy_setting.get('stock_pool'),
        user_id=investment_info.get('user_id'),
    )
    if not stock_pool:
        logger.warning(
            f"#{portfolio_id}, 所属用户（user_id={investment_info.get('user_id')}）"
            f"股票池为空，回退到全局股票池"
        )
        stock_pool = StockService.get_monitoring_stock_pool(
            per_page=strategy_setting.get('stock_pool')
        )

    # 近期新闻
    recent_news = MarketNewsService.get_by_time_range(limit=strategy_setting.get('news_limit'))

    # 上证指数近 30 天行情（模板里的 market_data_csv）
    index_data = databull.get_index_history(
        index_code='000001', start_date=get_date_by_n(-30), end_date=get_today()
    )

    template = Template(llm_prompt_str)
    holdings_text = format_holdings_text(holding_assets)
    stock_pool_text = format_stock_pool_text(stock_pool)

    logger.info(f"#{portfolio_id}, 进行调仓分析。大模型：{staff.model}，Agent 调研：{'开' if use_agent else '关'}")

    # 1. 读取历史上下文（当天会话内的多轮）
    # ⚠️ 原来这里紧接着有一行 `history = []`，把刚读出来的历史当场覆盖掉，
    # 导致下面的 `if len(history) == 0` **恒为真**、else 分支从未执行过 ——
    # 即「多轮对话」实际上从来没生效，而 append_messages 又在持续写库，
    # 于是 llm_conversation_context 里堆着一份谁都不读的对话。
    history = DialogueManager.get_context(chat_id) or []

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
        try:
            index_last = databull.get_realtime(symbol='000001', tick_type='index')
        except DataBullError as e:
            # 新 SDK 失败即抛异常；这里只是给大模型补一条附带信息，取不到不该中断调仓
            logger.warning(f"index tick failed: {e}")
            index_last = None
        prompt = (f"今天是：{get_today()}\n"
                  f"当前持仓：{holdings_text}\n"
                  f"可用资金：{available_money}\n"
                  f"上证指数最新数据：{index_last}\n"
                  f"继续思考调仓计划")

    # 1.5 Agent 调研阶段：让模型自己调 MCP 工具查数据
    if use_agent:
        research_text, agent_tool_calls = run_agent_research(
            staff, investment_info, holdings_text, available_money
        )
        if research_text:
            # 把调研结论拼进 prompt，交给阶段二做 JSON 决策。
            # ⚠️ 放在 prompt **最前面**且显式标注：模型对靠后的长 JSON 指令遵循度更高，
            # 若把调研结论追加在末尾，会与「只输出 JSON」的指令争抢注意力，导致输出带解释文字。
            prompt = (
                "## 前期调研结论（你自己刚刚查到的，请以此为准）\n"
                f"{research_text}\n\n"
                "---\n\n"
                "## 原始依赖数据与调仓要求\n"
                f"{prompt}\n\n"
                "请结合上面的调研结论，输出调仓计划 JSON。"
            )
        else:
            logger.warning(f"#{portfolio_id}, Agent 调研无结论，按原单轮模式继续")

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

    # 记录上下文
    DialogueManager.append_messages(chat_id, new_messages, max_tokens=llm_max_tokens)

    ai_ans = reply_content.replace("```json", "")
    ai_ans = ai_ans.replace("```", "")
    answer_json = parse_llm_json(ai_ans)

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


def parse_llm_json(text):
    """
    从大模型回复里抠出 JSON 对象。

    ⚠️ 为什么不能直接 json.loads：接入 Agent 调研阶段后，prompt 里混进了大段自然语言
    调研结论，模型偶尔会「先总结两句再给 JSON」（即使 response_format=json_object，
    部分平台也只是把它当软约束）。直接 json.loads 会抛 JSONDecodeError，
    而这发生在**已经花掉多次 LLM 调用之后**，一次失败就白烧一整轮成本。

    策略：先试整体解析 → 再退化为「截取第一个 { 到最后一个 }」。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            logger.error(f"截取 JSON 片段后仍解析失败：{e}")
            raise

    logger.error(f"回复中未找到 JSON 对象，原文前 200 字：{text[:200]}")
    raise ValueError('大模型回复中未找到 JSON 对象')


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


def job_position_plan_daily_all(trade_day_override=False, use_agent=True):
    """
    交易日运行策略

    :param use_agent: 透传给 job_position_plan_daily，控制是否启用 Agent 调研阶段
    """

    # 判断交易日
    if FactorValueService.is_trading_day() is False and trade_day_override is False:
        return

    portfolios = InvestmentPortfolioService.get_all()

    for prof in portfolios:
        # 跳过没有设置大模型的策略
        if prof.get('llm_setting') is None:
            continue
        # ⚠️ 与上一行同理：缺提示词属于「该组合未启用调仓」，不是「运行出错」。
        # 在这里提前跳过，既能省掉后面一整轮取数 + 大模型调用，
        # 也让日志不会把「未配置」误报成「调仓计划运行失败」。
        # 判空要连纯空白一起拦（理由见 job_position_plan_daily 内同名校验处的注释）。
        if not (prof.get('llm_prompt') or '').strip():
            logger.info(f"未配置 llm_prompt，跳过。#{prof.get('portfolio_id')}")
            continue
        if prof.get('position_plan') is not None and len(prof.get('position_plan')) > 0:
            logger.info(f"调仓计划已存在，跳过。#{prof.get('portfolio_id')}")
            continue
        try:
            job_position_plan_daily(portfolio_id=prof.get('portfolio_id'), use_agent=use_agent)
        except Exception as e:
            logger.warning(f"调仓计划运行失败：{e}")
            continue


if __name__ == '__main__':

    job_position_plan_daily_all(trade_day_override=True)

    # job_position_plan_daily(portfolio_id=13, send_feishu=False)
