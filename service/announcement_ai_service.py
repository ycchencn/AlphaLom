"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

公司公告「AI 解读」服务：公告正文抽取 + 公司背景组装 + 提示词构建。

## 为什么需要抽正文

上游只给「标题 + PDF 链接」，没有正文。而公告标题的信息量差异极大：
「关于回购公司股份的进展公告」这类标题本身不含金额、比例、期限，只凭标题让模型解读，
它只能讲一堆「回购通常意味着…」的行业套话 —— 看着专业，实际零信息，甚至会把
通用常识说成这家公司的事实。所以解读必须有正文兜底。

正文抽取**懒加载**（首次点「AI 解读」才做）：公告表里已有数百条，全量预抽是白烧流量；
而且绝大多数公告没人会去解读。抽过的落库缓存，第二次打开抽屉不再联网。

## 三个必须诚实处理的边界

1. **抽不出正文的公告真实存在**：部分巨潮 PDF 用自定义 CID 字体（尤其中资港股公告），
   抽出来是 `∉ ၵರ஼੝Ḹі` 这样的乱码；还有扫描件没有文字层。
   → 用 `_assess_quality` 判定，乱码/空文本一律记为 `unsupported` / `empty`，
   **绝不把乱码喂给模型**（否则模型会对着乱码一本正经地编）。
   提示词里也强制要求：正文缺失时必须由模型自己声明「仅基于标题推断」。
2. **正文不能无限长**：年报可达数百页。存储截断到 4 万字符、喂模型截断到 9 千字符，
   两者分开 —— 存的比喂的多，是为了以后做全文检索时还有料。
3. **解读不能当投资建议**：提示词写死免责要求，且禁止给目标价/买卖点。
"""

import io
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from pypdf import PdfReader
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models import Stock, StockAnnouncement
from models.database import db_session, engine
from utils.logger import logger

# ---- 正文抽取参数 ----
PDF_TIMEOUT = 20                    # 秒；巨潮 CDN 实测 0.1s，20s 是兜底而非预期
PDF_MAX_BYTES = 25 * 1024 * 1024    # 单份 25MB 上限：公告正常几百 KB，超了多半是异常响应
PDF_MAX_PAGES = 40                  # 只抽前 40 页：关键条款都在「重要内容提示」与前几节
CONTENT_STORE_MAX_CHARS = 40000     # 入库上限（LONGTEXT 放得下，但没必要存全本）
PROMPT_CONTENT_MAX_CHARS = 9000     # 喂模型上限（中文约 5~6k tokens，留足输出空间）

# 失败状态的重试窗口：正文下载失败多为瞬时网络问题，1 小时内不反复重试
FAILED_RETRY_AFTER = timedelta(hours=1)

# 正文之外，再带上同一只票最近的几条公告标题：判断「是不是进展类/连续披露」靠它。
RELATED_ANNOUNCEMENT_LIMIT = 6

_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'
)

# 中日韩统一表意文字（含扩展 A）：一段正常中文公告里占比很高
_CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
_ASCII_LETTER_RE = re.compile(r'[A-Za-z]')


# --------------------------------------------------------------------------- 正文抽取


def _assess_quality(text: str) -> Tuple[str, str]:
    """判定抽出来的文本是否可用，返回 (status, 说明)。

    status:
      - ok          正常中英文正文
      - unsupported 有文字层但解不出有意义内容（自定义 CID 字体 → 乱码）
      - empty       没有文字层（扫描件 / 图片型 PDF）

    ⚠️ 判据用「中文字符占比」与「ASCII 字母占比」两条，而不是「长度够不够」：
       乱码样本长度并不短（8 页抽出 4400 字符），只看长度会当成成功。
    """
    if not text:
        return 'empty', 'PDF 无文字层'
    n = len(text)
    if n < 40:
        return 'empty', 'PDF 无文字层'
    cjk = len(_CJK_RE.findall(text))
    letters = len(_ASCII_LETTER_RE.findall(text))
    if cjk / n >= 0.12 or letters / n >= 0.30:
        return 'ok', ''
    # 乱码：非中文、非拉丁，且大量非常用符号（实测样本：∉ ၵರ஼੝Ḹі ٺܢứྛದ）
    return 'unsupported', 'PDF 使用自定义字体编码，文本无法解码'


def _normalize_text(text: str) -> str:
    """压掉 PDF 抽取带来的碎片空白：连续空格/换行归一，保留段落分隔。"""
    text = text.replace('\x00', ' ')
    # PDF 常见「每个字之间一个空格」，中文里这类空格无意义 → 中文之间的空格去掉
    text = re.sub(r'(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_pdf_text(pdf_url: str) -> Dict[str, Any]:
    """下载并抽取 PDF 正文。返回 {'status', 'text', 'chars', 'pages', 'error'}。

    不抛异常：所有失败都折算成 status，由调用方决定提示口径。
    """
    out = {'status': 'failed', 'text': '', 'chars': 0, 'pages': 0, 'error': ''}
    if not pdf_url:
        out['error'] = '无 PDF 链接'
        return out
    try:
        resp = requests.get(pdf_url, timeout=PDF_TIMEOUT, headers={'User-Agent': _USER_AGENT})
        if resp.status_code != 200:
            out['error'] = f'HTTP {resp.status_code}'
            return out
        raw = resp.content or b''
        if not raw:
            out['error'] = '响应为空'
            return out
        if len(raw) > PDF_MAX_BYTES:
            out['error'] = f'PDF 过大（{len(raw) // 1024}KB）'
            return out
        if not raw[:4] == b'%PDF':
            # 拿到 HTML 错误页/防盗链提示时，pypdf 会抛一堆看不懂的异常，先挡掉
            out['error'] = '响应不是 PDF'
            return out

        reader = PdfReader(io.BytesIO(raw))
        pages = len(reader.pages)
        out['pages'] = pages
        chunks: List[str] = []
        for page in reader.pages[:PDF_MAX_PAGES]:
            try:
                chunks.append(page.extract_text() or '')
            except Exception:  # noqa: BLE001 - 单页异常不影响其它页
                continue
        text = _normalize_text('\n'.join(chunks))
        status, reason = _assess_quality(text)
        out.update(status=status, text=text, chars=len(text), error=reason)
        return out
    except requests.RequestException as e:
        out['error'] = f'下载失败：{e.__class__.__name__}'
        return out
    except Exception as e:  # noqa: BLE001 - pypdf 对坏文件抛的异常类型不统一
        out['error'] = f'解析失败：{e.__class__.__name__}'
        return out


def _persist_content(announcement_id: int, result: Dict[str, Any], text: str) -> None:
    """把抽取结果写回公告行。

    ⚠️ **必须用独立 Session**，不能用全局 `db_session`：本函数会在**流式响应生成器**
    里被调用，而请求级 Session 由 `app/fastapi_app.py` 的中间件在 ``call_next`` 返回
    时（= 流还没开始发）就 ``remove()`` 了。此时全局 session 已是新会话、原来的 row
    处于 detached 状态，``commit()`` 不报错但**什么都不写** —— 表现是「正文每次都重新
    下载」「解读永不命中缓存」，且日志里一条错误都没有。独立 Session 与请求作用域无关，
    写的是真实数据。
    """
    try:
        with Session(bind=engine) as s:
            s.query(StockAnnouncement).filter(StockAnnouncement.id == announcement_id).update(
                {
                    StockAnnouncement.content_status: result['status'],
                    StockAnnouncement.content_text: text or None,
                    StockAnnouncement.content_chars: int(result.get('chars') or 0),
                    StockAnnouncement.content_fetch_time: datetime.now(),
                },
                synchronize_session=False,
            )
            s.commit()
    except SQLAlchemyError as e:  # noqa: BLE001
        logger.warning(f'[announcement-ai] 正文缓存落库失败 id={announcement_id}: {e}')


def ensure_content(row: StockAnnouncement, force: bool = False) -> Dict[str, Any]:
    """确保该公告已有正文缓存；必要时现抽并落库。

    返回 {'status', 'text', 'chars', 'cached', 'reason'}。
    - status=ok 且 text 非空 → 可直接喂模型
    - 其它状态 → 调用方据此在提示词里声明「无正文」
    """
    if row is None:
        return {'status': 'failed', 'text': '', 'chars': 0, 'cached': False, 'reason': '公告不存在'}

    cached_text = (row.content_text or '').strip()
    status = (row.content_status or '').strip()

    if not force and status and status != 'failed' and (cached_text or status in ('unsupported', 'empty')):
        return {'status': status, 'text': cached_text, 'chars': int(row.content_chars or len(cached_text)),
                'cached': True, 'reason': ''}

    if not force and status == 'failed' and row.content_fetch_time:
        # 失败后 1 小时内不重试，避免用户连点「重新生成」把时间都耗在超时上
        if datetime.now() - row.content_fetch_time < FAILED_RETRY_AFTER:
            return {'status': 'failed', 'text': '', 'chars': 0, 'cached': True,
                    'reason': '正文下载失败（稍后重试）'}

    result = extract_pdf_text(row.pdf_url or '')
    # ⚠️ 只有 ok 才存正文：乱码/扫描件的文本留着既没用又占空间，
    #    status 本身已经能阻止重复下载（想复现问题可以直接点 PDF 链接）。
    stored = _normalize_text(result['text'])[:CONTENT_STORE_MAX_CHARS] if result['status'] == 'ok' else ''
    _persist_content(row.id, result, stored)

    # 内存对象同步一份，供本次请求后续使用（它已 detached，写库不走它）
    row.content_status = result['status']
    row.content_text = stored or None
    row.content_chars = int(result['chars'] or 0)
    row.content_fetch_time = datetime.now()

    logger.info(
        f'[announcement-ai] 正文抽取 id={row.id} symbol={row.symbol} '
        f'status={result["status"]} pages={result["pages"]} chars={result["chars"]} '
        f'{result["error"]}'
    )
    return {
        'status': result['status'],
        'text': stored,
        'chars': int(result['chars'] or 0),
        'cached': False,
        'reason': result['error'],
    }


# --------------------------------------------------------------------------- 公司背景


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ''
    return f'{f:.{digits}f}'


def build_company_context(symbol: str, exclude_id: Optional[int] = None) -> str:
    """组装公司背景（全部来自本地表，零网络开销）。

    只放「模型判断影响时真正会用到的锚点」：行业定位、估值水平、最近行情、
    以及最近几条其它公告（判断是否为进展/连续披露）。刻意不塞完整财务三表 ——
    那是「AI 财务点评」的活，这里塞进来只会稀释公告本身的信息。
    """
    lines: List[str] = []
    try:
        stock = db_session.query(Stock).filter(Stock.symbol == symbol).first()
    except SQLAlchemyError as e:  # noqa: BLE001
        logger.warning(f'[announcement-ai] 读取公司背景失败 {symbol}: {e}')
        stock = None

    if stock:
        bits = [f'{stock.name or "—"}（{symbol}）']
        if stock.industry:
            bits.append(f'所属行业：{stock.industry}')
        if stock.province or stock.city:
            bits.append('所在地：' + ''.join(x for x in (stock.province, stock.city) if x))
        lines.append('｜'.join(bits))
        concepts = (stock.concepts or '').strip()
        if concepts:
            short = ','.join([c for c in concepts.split(',') if c][:6])
            lines.append(f'概念标签：{short}')
        valuation = []
        if stock.pe_ratio:
            valuation.append(f'PE {_fmt_num(stock.pe_ratio)}')
        if stock.pb_ratio:
            valuation.append(f'PB {_fmt_num(stock.pb_ratio)}')
        if valuation:
            lines.append('估值快照：' + '，'.join(valuation))

        ohlc = stock.ohlc_last or {}
        if isinstance(ohlc, dict) and ohlc.get('lastPrice'):
            price = _fmt_num(ohlc.get('lastPrice'))
            chg = ohlc.get('chg_pct')
            chg_text = ''
            try:
                chg_text = f'（当日 {float(chg):+.2f}%）'
            except (TypeError, ValueError):
                chg_text = ''
            lines.append(f'最近收盘：{price} 元{chg_text}')
    else:
        lines.append(f'（本地库无 {symbol} 的公司基础信息）')

    # 同票近期其它公告：让模型知道「这是不是一串连续披露里的最新一条」
    try:
        rows = (
            db_session.query(StockAnnouncement)
            .filter(StockAnnouncement.symbol == symbol)
            .order_by(StockAnnouncement.announce_date.desc(), StockAnnouncement.id.desc())
            .limit(RELATED_ANNOUNCEMENT_LIMIT + 1)
            .all()
        )
        # 多取 1 条是为了不把「当前这条」挤掉后不足数（下面按 id 剔除当前条）
        others = [r for r in rows if r.id != exclude_id][:RELATED_ANNOUNCEMENT_LIMIT]
        if others:
            lines.append('')
            lines.append('该公司近期其它公告（按日期倒序，仅供判断上下文，不要当成这次公告的内容）：')
            for r in others:
                d = r.announce_date.isoformat() if r.announce_date else ''
                lines.append(f'- {d} {r.title}')
    except SQLAlchemyError as e:  # noqa: BLE001
        logger.warning(f'[announcement-ai] 读取同票公告失败 {symbol}: {e}')

    return '\n'.join(lines)


# --------------------------------------------------------------------------- 提示词


def build_material(row: StockAnnouncement, content: Dict[str, Any], company_ctx: str) -> str:
    """拼「背景资料 + 公告元数据 + 正文」这一段材料（作为首轮 user 消息的主体）。"""
    status = content.get('status')
    text = (content.get('text') or '').strip()

    meta = [
        f'公告标题：{row.title}',
        f'公告日期：{row.announce_date.isoformat() if row.announce_date else "未知"}',
        f'公告分类（系统按标题关键词推断，仅供参考）：{row.category or "其他公告"}',
    ]
    if row.column_name:
        meta.append(f'上市板块：{row.column_name}')
    meta.append(f'原文链接：{row.pdf_url or "无"}')

    if status == 'ok' and text:
        body = text[:PROMPT_CONTENT_MAX_CHARS]
        truncated = len(text) > len(body)
        body_block = (
            '=== 公告正文（系统从 PDF 抽取' + ('，已截断，仅前 %d 字' % len(body) if truncated else '') + '）===\n'
            + body
        )
    elif status == 'empty':
        body_block = (
            '=== 公告正文 ===\n'
            '（这份 PDF 是扫描件，没有可提取的文字层，系统拿不到正文。'
            '请只基于标题与公司背景做有限推断，并在开头明确说明这一点。）'
        )
    elif status == 'unsupported':
        body_block = (
            '=== 公告正文 ===\n'
            '（这份 PDF 使用了无法解码的字体编码，抽出来的文字是乱码，已丢弃。'
            '请只基于标题与公司背景做有限推断，并在开头明确说明这一点。）'
        )
    else:
        body_block = (
            '=== 公告正文 ===\n'
            f'（正文获取失败：{content.get("reason") or "未知原因"}。'
            '请只基于标题与公司背景做有限推断，并在开头明确说明这一点。）'
        )

    return (
        '=== 公司背景 ===\n' + (company_ctx or '（无）') + '\n\n'
        '=== 本次公告 ===\n' + '\n'.join(meta) + '\n\n' + body_block
    )


def build_messages(row: StockAnnouncement, content: Dict[str, Any],
                   history: Optional[List[Dict[str, str]]] = None,
                   question: Optional[str] = None) -> List[Dict[str, str]]:
    """组装完整 messages。

    结构固定为：
      system  → 解读分析师角色 + 硬性约束
      user    → 材料（公司背景 + 公告元数据 + 正文）+ 首轮解读指令
      history → 首轮解读（assistant）+ 后续问答
      user    → 本次追问（可选）

    ⚠️ 材料只作为**第一轮**的 user 消息注入，不重复放进 history：追问时若把正文
       再贴一遍，token 会翻倍，而模型从上文已经看过了。
    """
    status = content.get('status')
    has_body = status == 'ok' and bool((content.get('text') or '').strip())

    material = build_material(row, content, build_company_context(row.symbol or '', exclude_id=row.id))
    first_instruction = (
        '请解读上面这条公告。若正文已给出，一切事实以正文为准；'
        '若正文缺失，只能基于标题与公司背景做有限推断，并在开头一句明确说明。'
        if has_body else
        '请解读上面这条公告。注意：正文缺失，你只能基于标题与公司背景做有限推断，'
        '必须在开头一句明确说明「未取到公告正文」，并且不得编造任何具体数字、金额、比例、期限或条款。'
    )

    messages: List[Dict[str, str]] = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'{material}\n\n{first_instruction}'},
    ]
    for item in history or []:
        role = (item or {}).get('role')
        content_text = (item or {}).get('content') or ''
        if role in ('user', 'assistant') and content_text.strip():
            messages.append({'role': role, 'content': content_text})
    if question and question.strip():
        messages.append({'role': 'user', 'content': question.strip()})
    return messages


# --------------------------------------------------------------------------- 解读缓存


def save_summary(announcement_id: int, summary: str, model: str) -> bool:
    """保存首轮解读（一条公告一份）。

    ⚠️ 同样用**独立 Session**：这个方法在流式生成器里被调用，请求级 Session 早已
    被中间件回收（详见 `_persist_content` 的说明）。
    """
    if not announcement_id or not (summary or '').strip():
        return False
    try:
        with Session(bind=engine) as s:
            s.query(StockAnnouncement).filter(StockAnnouncement.id == announcement_id).update(
                {
                    StockAnnouncement.ai_summary: summary.strip(),
                    StockAnnouncement.ai_model: model,
                    StockAnnouncement.ai_update_time: datetime.now(),
                },
                synchronize_session=False,
            )
            s.commit()
        return True
    except SQLAlchemyError as e:  # noqa: BLE001
        logger.warning(f'[announcement-ai] 解读落库失败 id={announcement_id}: {e}')
        return False


def get_announcement(announcement_id: int) -> Optional[StockAnnouncement]:
    """按主键取公告（不存在返回 None）。越权判定由路由层用 symbol 做。"""
    try:
        return db_session.query(StockAnnouncement).filter(StockAnnouncement.id == announcement_id).first()
    except SQLAlchemyError as e:  # noqa: BLE001
        logger.error(f'[announcement-ai] 读取公告失败 id={announcement_id}: {e}')
        return None


# ⚠️ 角色与约束写死在后端：前端只传「问什么」，不传「你是谁」，
#    避免被改成「无条件看多」之类的口吻而让解读失去参考价值。
SYSTEM_PROMPT = """你是一名专注 A 股上市公司信息披露的解读分析师，长期跟踪公告背后的经营与治理含义。你的读者是持有或关注这家公司的个人投资者。

你的任务：先把公告「说了什么」讲清楚，再评估「对公司意味着什么」，最后指出「哪里还需要确认」。

硬性约束（必须遵守）：
1. 事实来源只有两处：用户提供的公告正文、以及用户提供的公司背景资料。**不得引用任何外部记忆中的数字或事件**，也不得把行业通用常识说成这家公司的事实。
2. 正文缺失（未取到 / 乱码 / 扫描件）时：必须在开头第一句明确说明「未取到公告正文」，之后只能做有限的逻辑推断，**绝对不许编造具体金额、比例、期限、交易对手、审批进度等细节**。
3. 严格区分「公告原文事实」与「你的推断」：推断用「可能 / 倾向于 / 需进一步确认」这类措辞，不要把推断写成结论。
4. 不做买卖建议，不给目标价，不预测股价涨跌。
5. 语言：中文，简洁专业、信息密度高。不要复述公告全文，不要写套话开场。

输出结构（Markdown，总长 400~600 字）：
### 一句话结论
用一句话定性这条公告的性质与影响方向（利好/利空/中性并说清原因），不给操作建议。

### 公告事实
逐条列出公告到底说了什么：主体、事项、关键数字、期限、前置条件。正文有就照抄要点，没有就明确写「标题未披露具体条款」。

### 影响分析
按影响路径说清楚：对业绩/现金流、对股权结构或治理、对经营节奏分别意味着什么。影响不确定的要标注不确定。

### 需要注意的点
是否为进展类/连续披露、是否有待审批或前置条件、与近期其它公告是否衔接、有哪些容易被误读的地方。

### 后续关注
下一次该看什么披露或什么数据来验证这件事的进展。

文末固定加一行：本解读由 AI 基于公开披露信息生成，仅供参考，不构成投资建议。"""
