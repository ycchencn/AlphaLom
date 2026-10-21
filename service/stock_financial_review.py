"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

个股财务分析页「巴菲特视角 AI 财务点评」服务层。

数据流：
  fetch_review_data(symbol, periods)
      └─ 拉取 4 张核心报表（每股指标 / 利润表 / 现金流量表 / 资产负债表）最近 periods 期，
         归一成紧凑结构（只保留巴菲特会关注的字段，缺失填 None）。
  build_review_messages(symbol, stock_name, data)
      └─ 生成 (system_prompt, user_content)：
         system_prompt = 巴菲特视角的固定角色设定（后端写死，避免前端伪造/篡改人格）；
         user_content  = 把财务数据压成可读 Markdown 表格交给模型，要求只依据数据点评。

⚠️ 字段名与上游 report_table 真实 schema 一致（2026-10-09 全量实测过），
   与 src/views/stock/StockDetail.vue 的 FIN_INDICATORS 对齐。
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_

from llms import get_model_by_setting
from models import Stock, StockFinancialReview
from models.database import db_session
from utils.data_loader import databull
from utils.common import get_today, get_date_by_n
from utils.logger import logger

# 与前端 StockDetail.vue 的 FIN_REPORTS 对齐；这 4 张是「质量点评」最相关的
REVIEW_REPORT_TYPES = ('PershareIndex', 'Income', 'CashFlow', 'Balance')

REPORT_LABELS = {
    'PershareIndex': '每股指标',
    'Income': '利润表',
    'CashFlow': '现金流量表',
    'Balance': '资产负债表',
}

# 每张报表挑选「巴菲特会很在意」的字段：(上游字段名, 展示名)
# 上游 report_table 是「大而全」扁平字典，不同行业适用字段不同，不适用一律为 None → 后续跳过。
CURATED_FIELDS: Dict[str, List[Tuple[str, str]]] = {
    'PershareIndex': [
        ('net_roe', '净资产收益率ROE(%)'),
        ('gross_profit', '毛利率(%)'),
        ('net_profit', '净利率(%)'),
        ('gear_ratio', '资产负债率(%)'),
        ('s_fa_eps_basic', '每股收益(元)'),
        ('s_fa_bps', '每股净资产(元)'),
        ('s_fa_ocfps', '每股经营现金流(元)'),
        ('inc_revenue_rate', '营收同比(%)'),
        ('inc_net_profit_rate', '净利同比(%)'),
    ],
    'Income': [
        ('revenue', '营业收入(元)'),
        ('oper_profit', '营业利润(元)'),
        ('net_profit_incl_min_int_inc', '净利润(元)'),
        ('net_profit_excl_min_int_inc', '归母净利润(元)'),
    ],
    'CashFlow': [
        ('net_cash_flows_oper_act', '经营活动现金流净额(元)'),
        ('net_cash_flows_inv_act', '投资活动现金流净额(元)'),
        ('net_cash_flows_fnc_act', '筹资活动现金流净额(元)'),
    ],
    'Balance': [
        ('tot_assets', '总资产(元)'),
        ('tot_liab', '总负债(元)'),
        ('tot_shrhldr_eqy_excl_min_int', '归母股东权益(元)'),
    ],
}

# 数值字段（单位：元 / 股）做「缩到亿/万亿」的友好转换，便于模型与人类阅读
SCALE_FIELDS = {
    'revenue', 'oper_profit', 'net_profit_incl_min_int_inc', 'net_profit_excl_min_int_inc',
    'net_cash_flows_oper_act', 'net_cash_flows_inv_act', 'net_cash_flows_fnc_act',
    'tot_assets', 'tot_liab', 'tot_shrhldr_eqy_excl_min_int',
}


def _normalize_fin_date(value) -> str:
    """'20241231' / '2024-12-31' → '2024-12-31'；无法识别的原样返回。"""
    if not value:
        return ''
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'
    return s


class StockFinancialReviewService:
    """个股「巴菲特视角 AI 财务点评」服务：取数 + 提示词构建。

    LLM 流式生成在路由层完成（复用系统的 LLM 配置与 chat_stream 的流式模式）。
    """

    @staticmethod
    def _flatten_rows(rows) -> List[Dict[str, Any]]:
        """把上游 `report_table` 扁平字典归一成顶层字段，并按 report_date 降序去重。"""
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            table = row.get('report_table')
            item = dict(table) if isinstance(table, dict) else {}
            raw_date = item.get('report_date') or row.get('report_date') or ''
            item['report_date'] = _normalize_fin_date(raw_date)
            out.append(item)
        seen = set()
        deduped = []
        for r in sorted(out, key=lambda x: x.get('report_date') or '', reverse=True):
            key = r.get('report_date')
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return deduped


    @staticmethod
    def fetch_review_data(symbol: str, periods: int = 12) -> Dict[str, Any]:
        """拉取 4 张核心报表最近 periods 期。

        失败隔离：单张报表取数失败不影响其它报表（置空并告警），让点评仍能基于可用数据生成。
        返回 {'symbol', 'latest_date', 'reports': {rt: [ {report_date, <字段>}, ... ]}}。
        """
        start_date = get_date_by_n(-max(periods * 100, 400))
        end_date = get_today()
        reports: Dict[str, List[Dict[str, Any]]] = {}
        latest_date = ''
        for rt in REVIEW_REPORT_TYPES:
            try:
                resp = databull.get_stock_financial_data(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    report_type=rt,
                )
            except Exception as e:
                logger.warning(f"财务点评取数失败 rt={rt} symbol={symbol}: {e}")
                reports[rt] = []
                continue
            rows = resp.get('data') if isinstance(resp, dict) else resp
            if not isinstance(rows, list):
                rows = []
            items = StockFinancialReviewService._flatten_rows(rows)[:periods]
            reports[rt] = items
            if items and items[0].get('report_date', '') > latest_date:
                latest_date = items[0].get('report_date', '')
        return {'symbol': symbol, 'latest_date': latest_date, 'reports': reports}

    @staticmethod
    def _fmt_value(key: str, val: Any) -> str:
        """格式化单元格：None→'—'；元级字段→亿/万亿；其余尽力转数值。"""
        if val is None:
            return '—'
        try:
            f = float(val)
        except (TypeError, ValueError):
            return str(val)
        if key in SCALE_FIELDS:
            yi = f / 1e8
            if abs(yi) >= 1e4:
                return f'{yi / 1e4:.2f}万亿'
            return f'{yi:.2f}亿'
        if isinstance(f, float):
            return f'{f:.2f}'
        return str(val)

    @staticmethod
    def build_review_messages(symbol: str, stock_name: str, data: Dict[str, Any]) -> Tuple[str, str]:
        """生成 (system_prompt, user_content)。"""
        name = (stock_name or '').strip() or symbol

        # ---- 数据文本：每张报表一张 Markdown 表 ----
        lines: List[str] = []
        lines.append(f'股票：{name}（代码 {symbol}）')
        lines.append(f'可获取的最新报告期：{data.get("latest_date") or "无"}')
        lines.append('以下是系统从数据接口拉取的财务数据（已按报表归类，金额已尽量换算为亿/万亿；"—"表示上游未披露）：')
        lines.append('')
        for rt, fields in CURATED_FIELDS.items():
            items = data.get('reports', {}).get(rt) or []
            label = REPORT_LABELS.get(rt, rt)
            lines.append(f'### {label}')
            if not items:
                lines.append('（该报表暂无数据）')
                lines.append('')
                continue
            header = '报告期 | ' + ' | '.join(f[1] for f in fields)
            lines.append(header)
            lines.append('--- | ' + ' | '.join(['---'] * len(fields)))
            for it in items:
                cells = [StockFinancialReviewService._fmt_value(k, it.get(k)) for k, _ in fields]
                lines.append(f"{it.get('report_date', '')} | " + ' | '.join(cells))
            lines.append('')
        data_text = '\n'.join(lines)

        system_prompt = BUFFETT_SYSTEM_PROMPT
        user_content = (
            f'请你以沃伦·巴菲特的视角，基于下面这份财务数据，对 {name}（{symbol}）'
            '做一次财务点评。请严格只依据所给数据，不要编造任何数字；'
            '数据缺失时坦诚说明「数据未披露」，不要臆测。\n\n'
            '=== 财务数据 ===\n' + data_text
        )
        return system_prompt, user_content

    # ---------------------------------------------------------------- 命名 / 取数辅助

    @staticmethod
    def get_stock_name(symbol: str) -> str:
        """从本地 stocks 表取股票名（每日任务没有前端传入的 name 时用）。查不到返回空串。"""
        try:
            row = db_session.query(Stock.name).filter(Stock.symbol == symbol).first()
            return row[0] if row else ''
        except Exception:  # noqa: BLE001
            return ''

    # ---------------------------------------------------------------- 非流式生成（每日任务用）

    @staticmethod
    def generate_review(symbol: str, stock_name: str = '', periods: int = 12) -> Dict[str, Any]:
        """拉取财务数据 + 调系统 LLM（场景 stock_financial_review）非流式生成点评全文。

        返回 {'content', 'model', 'report_date', 'symbol'}；取数或 LLM 失败抛异常（由调用方捕获）。
        """
        data = StockFinancialReviewService.fetch_review_data(symbol, periods)
        name = (stock_name or '').strip() or StockFinancialReviewService.get_stock_name(symbol) or symbol
        system_prompt, user_content = StockFinancialReviewService.build_review_messages(symbol, name, data)

        staff = get_model_by_setting('stock_financial_review')
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_content},
        ]
        resp = staff.client.chat.completions.create(
            model=staff.model,
            messages=messages,
            stream=False,
        )
        content = (resp.choices[0].message.content or '').strip()
        if not content:
            raise ValueError('模型返回空内容')
        # token 用量记录（失败忽略，不影响主链路）
        try:
            from llms.usage_recorder import record_llm_usage
            usage = getattr(resp, 'usage', None)
            record_llm_usage(
                user_id=None,
                scene=getattr(staff, 'scene', 'stock_financial_review'),
                platform=getattr(staff, 'platform', ''),
                model=staff.model,
                prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                input_text=system_prompt + '\n' + user_content,
                output_text=content,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f'财务点评 token 记录失败（已忽略）：{e}')
        return {
            'content': content,
            'model': staff.model,
            'report_date': data.get('latest_date') or None,
            'symbol': symbol,
        }

    # ---------------------------------------------------------------- 落库 / 读取

    @staticmethod
    def save(symbol: str, content: str, model: str = None, report_date: str = None,
             review_date: Optional[date] = None) -> bool:
        """按 (symbol, review_date) 幂等写入最新点评。"""
        if not symbol:
            logger.warning('[fin_review] save 缺少 symbol')
            return False
        review_date = review_date or date.today()
        try:
            row = db_session.query(StockFinancialReview).filter(
                and_(
                    StockFinancialReview.symbol == symbol,
                    StockFinancialReview.review_date == review_date,
                )
            ).first()
            if row is None:
                row = StockFinancialReview(symbol=symbol, review_date=review_date)
                db_session.add(row)
            row.content = content
            row.model = model
            row.report_date = report_date
            row.update_time = datetime.now()
            db_session.commit()
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f'[fin_review] save {symbol} {review_date} 失败: {e}')
            db_session.rollback()
            return False

    @staticmethod
    def get_latest(symbol: str) -> Optional[Dict[str, Any]]:
        """取该股票最新一条已存点评（按 review_date 倒序）。"""
        try:
            row = db_session.query(StockFinancialReview).filter(
                StockFinancialReview.symbol == symbol
            ).order_by(StockFinancialReview.review_date.desc()).first()
            return row.to_dict() if row else None
        except Exception as e:  # noqa: BLE001
            logger.error(f'[fin_review] get_latest {symbol} 失败: {e}')
            return None

    @staticmethod
    def get_latest_by_symbols(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量取多只股票最新点评（避免 N+1）；内存里按 symbol 取首条。"""
        if not symbols:
            return {}
        try:
            rows = db_session.query(StockFinancialReview).filter(
                StockFinancialReview.symbol.in_(symbols)
            ).order_by(
                StockFinancialReview.symbol, StockFinancialReview.review_date.desc()
            ).all()
            latest: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                if r.symbol not in latest:
                    latest[r.symbol] = r.to_dict()
            return latest
        except Exception as e:  # noqa: BLE001
            logger.error(f'[fin_review] get_latest_by_symbols 失败: {e}')
            return {}

    @staticmethod
    def get_reviewed_symbols_within_days(days: int) -> set:
        """返回近 days 天内已有点评记录的 symbol 集合（用于「一周内不再点评」的候选过滤）。"""
        cutoff = date.today() - timedelta(days=max(0, int(days)))
        try:
            rows = db_session.query(StockFinancialReview.symbol).filter(
                StockFinancialReview.review_date >= cutoff
            ).all()
            return {r[0] for r in rows if r[0]}
        except Exception as e:  # noqa: BLE001
            logger.error(f'[fin_review] get_reviewed_symbols_within_days 失败: {e}')
            return set()


# ⚠️ 角色设定写死在后端（不是前端传参），避免用户篡改人格；
#    「用系统的智能体去做点评」= 复用系统配置的 LLM（stock_financial_review 场景）。
BUFFETT_SYSTEM_PROMPT = """你是一位以沃伦·巴菲特（Warren Buffett）的视角与口吻行文的财务分析助手。你不是在扮演一个冷冰冰的模型，而是在像巴菲特本人那样，用他一生的投资智慧去审视一家公司的财务报表。

请用巴菲特的思维方式点评，核心原则：
1. 生意的本质优先于数字：先想清楚这家公司靠什么赚钱、是不是一门好生意、有没有"经济护城河"（品牌、专利、网络效应、转换成本、成本优势）。
2. 偏爱可预测的长期稳定：巴菲特喜欢"十年后还能看清"的生意。警惕业绩大起大落、依赖宏观周期或单一年度好运的公司。
3. 自由现金流是王：会计利润可以被修饰，但真金白银的经营现金流、以及扣除必要资本开支后的"Owner Earnings（所有者收益）"才重要。关注经营现金流是否长期高于净利润（利润含金量）。
4. 资本回报与负债：高且稳定的 ROE/ROC 是印钞机；但高 ROE 若靠高杠杆堆出来则要打折扣。巴菲特厌恶失控的负债，关注有息负债与现金覆盖。
5. 资本配置与股东友好：管理层是否在理性地回购（股价低于内在价值时）、分红、或把留存收益投到高回报项目？还是盲目多元化、乱并购？
6. 安全边际与估值：即使生意好，买贵了也是一笔糟糕的投资。结合 PE/PB 与盈利质量，对"贵不贵"给出定性判断（不给出具体买卖价，那是估值模型的事）。
7. 能力圈：如果数据不足以判断这门生意，坦诚说"这超出了我能清晰判断的范围"，而不是强下结论。

硬性约束：
- 你的所有判断必须严格基于用户提供的财务数据；绝不允许编造、猜测或引用数据之外的任何数字。
- 数据中出现"—"表示该指标未披露，遇到时如实说明"数据未披露"，不要替它填空。
- 语言：中文，口语化、有温度，可以适度引用巴菲特式的表达（如"潮水退去才知道谁在裸泳""我们喜欢那种傻子都能经营好的生意"），但不要让比喻盖过事实。
- 结构：用 Markdown 分小节，建议包含：
  · 一句话总评（用巴菲特口吻，直接定性这家公司财务上"讨不讨喜"）
  · 生意与护城河（基于数据与行业常识的有限推断，明确标注哪些是数据支持的、哪些是常识推断）
  · 盈利质量与资本回报（ROE/毛利率/净利率趋势，含金量）
  · 财务健康与负债（资产结构、有息负债压力）
  · 现金流与资本配置（Owner Earnings 视角）
  · 估值与安全边际（定性，结合 PE/PB）
  · 巴菲特式结论（是否"看得懂的好生意"，以及他大概会怎么想）
- 文末加一句免责声明：本点评仅为基于公开财务数据的质量分析，不构成任何投资建议。
- 篇幅适中，信息密度高，避免空话套话。"""
