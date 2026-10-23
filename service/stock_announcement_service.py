"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

上市公司公告（巨潮资讯网原文，经 DataBull 接入）的落库与查询服务。

## 为什么是本地副本

上游 `GET /cn/stock/announcements` 是**按单只股票**分页的接口，股票池几十只票就是
几十次请求；列表页每刷新一次都要重跑一轮，还要吃上游日配额（实测
`x-ratelimit-limit: 10000`）。公告本身是「盘后集中披露、历史条目不再变化」的低频
数据，天然适合落一份本地副本：定时任务增量拉取 → 列表页只查本地 SQL。

## 三个上游事实（别当成 bug 去"修"）

1. **覆盖不完整**：部分 A 股恒为空（实测 600519 / 600036 / 601899 放宽到 2020 年
   仍返回空数组 + `X-Empty-Reason: no_match`）。所以「空列表」是**合法结果**，
   服务层用 `upsert_sync_state(status='empty')` 与失败区分开。
2. **`start_date` / `end_date` 参数实际不生效**（实测传入 2026-10-01 后 total 不变），
   增量只能靠「翻页直到遇到已入库的最新公告日期」来截断，见 job 里的翻页逻辑。
3. **`category` 是巨潮内部多级码**（`'01010503||010112||012303'`），各段语义不唯一
   （01010503 同时覆盖「对外担保」与「H 股公告」），上游没有码表端点。
   因此**禁止硬编码码→中文映射**，展示分类一律走下面的标题关键词规则；原始码只
   原样存入 `raw_category` 备查。

## 分类规则为什么放在这里

同一套规则同时被三个调用方使用：个股详情页（`routes/stock.py` 的实时接口）、
定时落库任务、列表页筛选。规则表放在 routes 里会让 job 反向依赖 FastAPI 模块，
放在 model 里又混了业务语义，所以落在 service 层，`routes/stock.py` 改为从本模块
导入（保持单一来源，改规则只改一处）。
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import re

from sqlalchemy import func, and_, or_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import SQLAlchemyError

from models import StockAnnouncement, StockAnnouncementSync
from models.database import db_session
from utils.common import ETF_PREFIXES
from utils.logger import logger

# 公告分类标签：按标题关键词规则推断（与同花顺/东财的公告分类思路一致）。
# ⚠️ 顺序有意义：先匹配的特征更具体，必须放在前面（例如「回购」要先于「股份」，
#    否则「关于回购股份的进展公告」会被「股份」规则抢走）。
ANNOUNCEMENT_CATEGORY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ('定期报告', ('年度报告', '半年度报告', '季度报告', '三季度报告', '年报', '季报', '业绩预告', '业绩快报')),
    ('重大事项', ('重大资产', '资产重组', '要约收购', '吸收合并', '分拆上市')),
    ('融资事项', ('非公开发行', '定向增发', '可转债', '配股', '募集说明书', '发行股票', '债券发行')),
    ('股权激励', ('股权激励', '股票期权', '限制性股票')),
    ('回购增持', ('回购', '增持', '减持', '股份回购')),
    ('担保事项', ('担保', '抵押', '质押')),
    ('股东变动', ('股东变动', '股份变动', '权益变动', '限售股', '解除限售', '转增', '减持计划')),
    # ⚠️ 治理类关键词要能跨越「第六届」「第十一次」这类插入词，所以用「董事会」
    #    「监事会」「股东大会」等**机构词**而不是「董事会决议」这种固定短语 ——
    #    否则「第六届董事会第十一次会议决议公告」会漏判。
    ('公司治理', ('董事会', '监事会', '股东大会', '股东会', '公司章程', '选举', '聘任', '辞职', '辞任',
                  '任职资格', '换届', '高级管理人员')),
    ('关联交易', ('关联交易', '关联方')),
    # 「重大合同」放在经营情况而非重大事项：签合同是日常经营动作，
    # 资产重组/要约收购才是真正的「重大事项」。所以「重大合同」必须排在重大事项之后。
    ('经营情况', ('重大合同', '中标', '签订', '合同', '产销快报', '经营情况', '获批', '取得',
                  '对外投资', '参与投资', '基金备案')),
    ('风险提示', ('风险提示', '问询函', '关注函', '监管措施', '立案调查', '处罚', '违规', '诉讼', '仲裁')),
)

# 展示顺序（前端筛选下拉、统计卡片都按这个顺序，避免字典序把「其他公告」排到中间）
ANNOUNCEMENT_CATEGORIES: Tuple[str, ...] = tuple(
    [label for label, _ in ANNOUNCEMENT_CATEGORY_RULES] + ['其他公告']
)

# 巨潮的板块栏目码 → 可读名。上游只给 `page_column` 这样的内部码。
# 实测取值：SZZB(深主板) / SZCY(创业板) / SHZB(沪主板) / SHKCB(科创板)。
ANNOUNCEMENT_COLUMN_NAMES: Dict[str, str] = {
    'SZZB': '深主板',
    'SZCY': '创业板',
    'SHZB': '沪主板',
    'SHKCB': '科创板',
    'BJ': '北交所',
}

# 单条 upsert 语句的 VALUES 行数上限。
# 100 行 × (title 500 + raw_category 255) 约 80KB，远低于 MySQL 默认 max_allowed_packet，
# 又比逐行 SELECT+INSERT 少两个数量级的往返。
_UPSERT_CHUNK = 100

# 批量 IN 查询时单次传入的 symbol 个数上限（避免拼出超长 SQL / 超过占位符上限）
_IN_CHUNK = 500


# A 股代码：6 位数字（沪 60/68、深 00/30、北交所 4/8 开头）。
# ⚠️ 上游 `GET /cn/stock/announcements` 只覆盖 A 股：港股/美股发过去是白吃一次配额
#    返回空数组。所以「是不是 A 股」在同步层与展示层都要判，且用同一个函数
#    —— 否则会出现「任务跳过它、页面又怪它没数据」的自相矛盾提示。
_A_SHARE_RE = re.compile(r'^\d{6}$')


def is_a_share_symbol(symbol: str) -> bool:
    """是否为 A 股代码（排除港股/美股，也排除 ETF / REITs 号段）。"""
    code = str(symbol or '').strip()
    if not _A_SHARE_RE.match(code):
        return False
    return not code.startswith(ETF_PREFIXES)


def classify_announcement(title: str) -> str:
    """按标题关键词推断公告分类标签。

    纯函数、只读标题、规则表在上方 —— 便于单测与后续调整。
    命中不了时返回 '其他公告'（不返回空串：前端要统一渲染一个标签位）。
    """
    if not title:
        return '其他公告'
    for label, keywords in ANNOUNCEMENT_CATEGORY_RULES:
        for kw in keywords:
            if kw in title:
                return label
    return '其他公告'


def _to_date(value) -> Optional[date]:
    """上游日期统一是 'YYYY-MM-DD' 字符串；也容忍 datetime / 带时分秒的字符串。"""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text[:len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    # 兜底：只截前 10 位再试一次（应对 '2026-10-13T00:00:00' 这类带 T 的格式）
    try:
        return datetime.strptime(text[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _to_int(value) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


def normalize_row(row: Dict[str, Any], symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """上游一行 → 入库字典。缺关键字段（symbol / announcement_id / 标题）返回 None。

    ⚠️ 不用 `row.get('id')`（那是上游自增主键，跨标的复用、会变）做幂等键，
       必须用 `announcement_id`（巨潮公告 ID，与 PDF 文件名同源、稳定）。
    """
    if not isinstance(row, dict):
        return None

    symbol = str(symbol or row.get('stock_code') or '').strip()
    announcement_id = str(row.get('announcement_id') or '').strip()
    title = str(row.get('title') or '').strip()
    announce_date = _to_date(row.get('announcement_date'))

    if not symbol or not announcement_id or not title or not announce_date:
        return None

    column_code = (row.get('page_column') or '').strip() or None
    return {
        'symbol': symbol,
        'stock_name': (row.get('stock_name') or '').strip()[:50] or None,
        'announcement_id': announcement_id[:64],
        'title': title[:500],
        'category': classify_announcement(title),
        'raw_category': (row.get('category') or '')[:255] or None,
        'announce_date': announce_date,
        'announce_time': _to_datetime(row.get('announcement_time')),
        'column_code': column_code[:20] if column_code else None,
        'column_name': ANNOUNCEMENT_COLUMN_NAMES.get(column_code),
        'pdf_url': (row.get('pdf_url') or '')[:500] or None,
        'pdf_size_kb': _to_int(row.get('pdf_size_kb')),
        'source': 'databull',
    }


class StockAnnouncementService:
    """公告表的读写入口（写 = 定时任务，读 = 列表页接口）。"""

    # ---------------------------------------------------------------- 写

    @staticmethod
    def upsert_many(rows: Sequence[Dict[str, Any]]) -> int:
        """批量幂等写入，返回提交的行数。

        ⚠️ 走 MySQL 原生 `INSERT ... ON DUPLICATE KEY UPDATE`（依赖唯一键
        symbol+announcement_id），不是「先查后写」：一轮同步可能几百行，逐行查会变成
        几百次往返；而队列语义是「至少一次」，重复执行必须安全 —— ON DUPLICATE
        同时满足这两个要求。
        """
        if not rows:
            return 0

        total = 0
        now = datetime.now()
        try:
            for start in range(0, len(rows), _UPSERT_CHUNK):
                chunk = list(rows[start:start + _UPSERT_CHUNK])
                stmt = mysql_insert(StockAnnouncement).values(chunk)
                stmt = stmt.on_duplicate_key_update(
                    stock_name=stmt.inserted.stock_name,
                    title=stmt.inserted.title,
                    category=stmt.inserted.category,
                    raw_category=stmt.inserted.raw_category,
                    announce_date=stmt.inserted.announce_date,
                    announce_time=stmt.inserted.announce_time,
                    column_code=stmt.inserted.column_code,
                    column_name=stmt.inserted.column_name,
                    pdf_url=stmt.inserted.pdf_url,
                    pdf_size_kb=stmt.inserted.pdf_size_kb,
                    update_time=now,
                )
                db_session.execute(stmt)
                total += len(chunk)
            db_session.commit()
            return total
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'[announcement] upsert_many 失败（{len(rows)} 行）: {e}')
            return 0
        except Exception as e:  # noqa: BLE001
            db_session.rollback()
            logger.error(f'[announcement] upsert_many 异常: {e}')
            return 0

    @staticmethod
    def upsert_sync_state(symbol: str, status: str, *, last_announce_date: Optional[date] = None,
                          error: Optional[str] = None, pages: int = 0, rows: int = 0) -> None:
        """记录单只票的同步状态（每只票一行，覆盖写）。

        `last_announce_date` 只在本次真的取到数据时更新；取不到时保留旧值 ——
        否则一次上游抖动会把增量锚点清空，下一轮就得从第一页重新翻。
        """
        if not symbol:
            return
        try:
            row = db_session.query(StockAnnouncementSync).filter(
                StockAnnouncementSync.symbol == symbol).first()
            if row is None:
                row = StockAnnouncementSync(symbol=symbol)
                db_session.add(row)
            row.last_sync_time = datetime.now()
            row.last_sync_status = (status or '')[:20]
            row.last_error = (error or '')[:255] or None
            row.fetched_pages = int(pages or 0)
            row.fetched_rows = int(rows or 0)
            if last_announce_date:
                if row.last_announce_date is None or last_announce_date > row.last_announce_date:
                    row.last_announce_date = last_announce_date
            db_session.commit()
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.warning(f'[announcement] 写同步状态失败 {symbol}: {e}')

    @staticmethod
    def purge_before(cutoff: date) -> int:
        """删除截止日之前的公告，返回删除行数。

        公告长期堆积无上限（几十只票 × 每年数百条），超过展示需要的年份没有查询价值。
        默认保留期见 job 参数（`retention_days`）。
        """
        if not cutoff:
            return 0
        try:
            deleted = db_session.query(StockAnnouncement).filter(
                StockAnnouncement.announce_date < cutoff
            ).delete(synchronize_session=False)
            db_session.commit()
            if deleted:
                logger.info(f'[announcement] 清理 {cutoff} 之前的公告 {deleted} 条')
            return int(deleted or 0)
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f'[announcement] purge_before 失败: {e}')
            return 0

    # ---------------------------------------------------------------- 读

    @staticmethod
    def get_last_announce_dates(symbols: Iterable[str]) -> Dict[str, date]:
        """批量取每只票已入库的最新公告日期（增量翻页的停止条件）。"""
        wanted = [s for s in {str(x).strip() for x in (symbols or []) if x}]
        if not wanted:
            return {}
        result: Dict[str, date] = {}
        try:
            for start in range(0, len(wanted), _IN_CHUNK):
                chunk = wanted[start:start + _IN_CHUNK]
                rows = db_session.query(
                    StockAnnouncement.symbol,
                    func.max(StockAnnouncement.announce_date),
                ).filter(
                    StockAnnouncement.symbol.in_(chunk)
                ).group_by(StockAnnouncement.symbol).all()
                for symbol, max_date in rows:
                    if symbol and max_date:
                        result[symbol] = max_date
        except SQLAlchemyError as e:
            logger.error(f'[announcement] get_last_announce_dates 失败: {e}')
        return result

    @staticmethod
    def query(symbols: Sequence[str], *, category: Optional[str] = None,
              keyword: Optional[str] = None, symbol: Optional[str] = None,
              date_from: Optional[date] = None, date_to: Optional[date] = None,
              page: int = 1, page_size: int = 20) -> Tuple[List[Dict[str, Any]], int]:
        """按「股票池代码列表 + 筛选条件」分页查询，返回 (items, total)。

        ⚠️ 用先取代码列表再 `IN (...)` 的方式过滤，**不 JOIN `user_stock_pool` 或
        `stocks`**：库内各表 symbol 的排序规则不统一
        （utf8mb4_unicode_ci / utf8mb4_0900_ai_ci 混用），直接 JOIN 会撞
        1267 Illegal mix of collations（股票池页已踩过同一个坑）。
        """
        pool = [str(s).strip() for s in (symbols or []) if s]
        if symbol:
            # 单只票筛选必须同时在池内（越权看池外标的 → 直接空结果）
            pool = [symbol] if symbol in pool else []
        if not pool:
            return [], 0

        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 20), 200))

        conditions = [StockAnnouncement.symbol.in_(pool)]
        if category:
            conditions.append(StockAnnouncement.category == category)
        if keyword:
            like = f'%{keyword.strip()}%'
            conditions.append(or_(StockAnnouncement.title.like(like),
                                  StockAnnouncement.stock_name.like(like)))
        if date_from:
            conditions.append(StockAnnouncement.announce_date >= date_from)
        if date_to:
            conditions.append(StockAnnouncement.announce_date <= date_to)

        try:
            query = db_session.query(StockAnnouncement).filter(and_(*conditions))
            total = query.count()
            rows = query.order_by(
                StockAnnouncement.announce_date.desc(),
                StockAnnouncement.announce_time.desc(),
                StockAnnouncement.id.desc(),
            ).offset((page - 1) * page_size).limit(page_size).all()
            return [r.to_dict() for r in rows], int(total or 0)
        except SQLAlchemyError as e:
            logger.error(f'[announcement] query 失败: {e}')
            return [], 0

    @staticmethod
    def category_counts(symbols: Sequence[str], *, keyword: Optional[str] = None,
                        symbol: Optional[str] = None,
                        date_from: Optional[date] = None,
                        date_to: Optional[date] = None) -> Dict[str, int]:
        """按分类统计条数（顺序对齐 ANNOUNCEMENT_CATEGORIES，未出现的分类补 0）。

        ⚠️ 刻意**不接受 category 参数**：这是「分类标签上的数字」，必须忽略分类筛选本身，
        否则用户点进「定期报告」后其它标签全部变成 0，就没法再点回别的分类。
        关键词/单只票/日期这些「范围性筛选」则要一致，否则标签数字与列表条数对不上。
        """
        counts = {label: 0 for label in ANNOUNCEMENT_CATEGORIES}
        pool = [str(s).strip() for s in (symbols or []) if s]
        if symbol:
            pool = [symbol] if symbol in pool else []
        if not pool:
            return counts

        conditions = [StockAnnouncement.symbol.in_(pool)]
        if keyword:
            like = f'%{keyword.strip()}%'
            conditions.append(or_(StockAnnouncement.title.like(like),
                                  StockAnnouncement.stock_name.like(like)))
        if date_from:
            conditions.append(StockAnnouncement.announce_date >= date_from)
        if date_to:
            conditions.append(StockAnnouncement.announce_date <= date_to)
        try:
            rows = db_session.query(
                StockAnnouncement.category, func.count(StockAnnouncement.id)
            ).filter(and_(*conditions)).group_by(StockAnnouncement.category).all()
            for label, cnt in rows:
                key = label or '其他公告'
                count = int(cnt or 0)
                if key in counts:
                    counts[key] = count
                else:
                    # 规则表调整过（老数据里存在已下线的分类）→ 归入「其他公告」，
                    # 不让统计总数与列表条数对不上。
                    counts['其他公告'] += count
        except SQLAlchemyError as e:
            logger.error(f'[announcement] category_counts 失败: {e}')
        return counts

    @staticmethod
    def latest_date(symbols: Sequence[str]) -> Optional[date]:
        """池内最新的公告日期（前端「数据截至」提示用）。"""
        pool = [str(s).strip() for s in (symbols or []) if s]
        if not pool:
            return None
        try:
            value = db_session.query(func.max(StockAnnouncement.announce_date)).filter(
                StockAnnouncement.symbol.in_(pool)
            ).scalar()
            return value
        except SQLAlchemyError as e:
            logger.error(f'[announcement] latest_date 失败: {e}')
            return None

    @staticmethod
    def get_sync_states(symbols: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """批量取同步状态（列表页展示「已同步 N 只 / 最近同步时间 / 失败原因」）。"""
        wanted = [str(s).strip() for s in (symbols or []) if s]
        if not wanted:
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for start in range(0, len(wanted), _IN_CHUNK):
                chunk = wanted[start:start + _IN_CHUNK]
                rows = db_session.query(StockAnnouncementSync).filter(
                    StockAnnouncementSync.symbol.in_(chunk)).all()
                for row in rows:
                    result[row.symbol] = row.to_dict()
        except SQLAlchemyError as e:
            logger.error(f'[announcement] get_sync_states 失败: {e}')
        return result

    @staticmethod
    def coverage(symbols: Sequence[str]) -> Dict[str, int]:
        """池内覆盖统计，供前端区分「上游未收录」与「非 A 股不在范围内」。

        返回：
          pool_total    池内标的总数
          non_a_share   非 A 股（港股/美股/ETF）—— 上游只覆盖 A 股，天然没有数据
          a_share_total A 股数量
          with_data     其中已有公告的 A 股数量
          without_data  A 股里暂时没有公告的（上游覆盖不完整，属正常）
        """
        pool = [str(s).strip() for s in (symbols or []) if s]
        if not pool:
            return {'pool_total': 0, 'non_a_share': 0, 'a_share_total': 0,
                    'with_data': 0, 'without_data': 0}

        a_share = [s for s in pool if is_a_share_symbol(s)]
        non_a_share = len(pool) - len(a_share)
        if not a_share:
            return {'pool_total': len(pool), 'non_a_share': non_a_share, 'a_share_total': 0,
                    'with_data': 0, 'without_data': 0}

        try:
            with_data = db_session.query(
                func.count(func.distinct(StockAnnouncement.symbol))
            ).filter(StockAnnouncement.symbol.in_(a_share)).scalar() or 0
            with_data = int(with_data)
        except SQLAlchemyError as e:
            logger.error(f'[announcement] coverage 失败: {e}')
            with_data = 0
        return {
            'pool_total': len(pool),
            'non_a_share': non_a_share,
            'a_share_total': len(a_share),
            'with_data': with_data,
            'without_data': max(0, len(a_share) - with_data),
        }


def default_retention_cutoff(days: int) -> Optional[date]:
    """保留期 → 删除截止日（days<=0 表示不清理，返回 None）。"""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return datetime.now().date() - timedelta(days=days)
