"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException
from app.fastapi_app import api_prefix, json_resp
from service import MarketNewsService
from service.growth_value_service import GrowthValueError, GrowthValueService
from service.sector_daily_service import SectorDailyService, normalize_sector_type
from utils.logger import logger
from utils.data_loader import databull
from fastapi_cache.decorator import cache

market_router = APIRouter(prefix=api_prefix, tags=['市场数据'])

# ⚠️ 同步 `def` 路由会被 Starlette 自动丢进 anyio 线程池（默认 40 线程）；
# 写成 `async def` 则跑在唯一的事件循环线程上，Service 层的同步 pymysql / requests
# 调用会把整个 loop 占死，表现为「一个接口慢，全部接口卡」。详见 README 并发章节。


@market_router.get('/market/sectors')
@cache(expire=3600)
def get_market_sectors(
    sector_type: str = Query('sw1', description="板块类型：sw1-申万一级, sw2-申万二级, sw3-申万三级")
):
    """获取沪深板块涨跌幅数据（申万行业涨跌排行）

    **读库优先、回退上游**：`sector_daily_stats` 由日更任务
    `job_update_sector_daily` 每天落库；优先返回库里最新交易日的数据。
    库里查不到（新库、任务还没跑、或传了非法级别）时**回退直连上游**，
    保证页面不会因为任务缺失而空白。

    ⚠️ 上游 `/cn/market/sector_data/{sw}` 只返回**最新一个交易日**，没有历史接口 ——
    想要历史（如板块轮动图）必须读库，走 `/market/sectors_history`。
    """
    st = normalize_sector_type(sector_type)
    if st:
        rows = SectorDailyService.get_latest(st)
        if rows:
            return json_resp(rows)
        logger.debug(f'{st} 库里无数据，回退上游')

    # 回退：非法 sector_type 也会走到这里，交给上游返回 4xx 或空数据
    market_sector = databull.get_sector_data(sector_type=sector_type)
    return json_resp(market_sector)


@market_router.get('/market/sectors_history')
@cache(expire=3600)
def get_market_sectors_history(
    sector_type: str = Query('sw1', description="板块类型：sw1-申万一级, sw2-申万二级, sw3-申万三级"),
    limit_days: int = Query(250, ge=1, le=2000, description='取最近 N 个交易日'),
    sector_names: str = Query(None, description='可选，逗号分隔的板块名，只取这些板块'),
    mode: str = Query('raw', description="raw-明细行; rotation-按日排名矩阵（轮动图用）"),
):
    """申万行业**历史**日线（板块轮动图数据源）

    只能读本地库 —— 上游没有历史接口。数据靠日更任务逐日累积，因此
    实际能回溯多久取决于任务已跑了多少天；空表时返回 `[]`（不是 500）。

    :param mode: `raw` 返回逐行明细（含涨跌家数、领涨股等），
                 `rotation` 返回按交易日的排名矩阵，直接喂轮动图。
    """
    st = normalize_sector_type(sector_type)
    if not st:
        raise HTTPException(status_code=400, detail=f'非法 sector_type: {sector_type}')

    names = [n.strip() for n in sector_names.split(',') if n.strip()] if sector_names else None

    if mode == 'rotation':
        return json_resp(SectorDailyService.get_rotation_ranks(st, limit_days=limit_days))
    return json_resp(SectorDailyService.get_history(st, limit_days=limit_days, sector_names=names))


@market_router.get('/market/fear_greed')
@cache(expire=3600)
def get_market_fear_greed(
    index_code: str = Query(
        '000001',
        description=(
            "指数代码。上游覆盖范围（实测 2026-09-24 近一年回溯）：000001-上证指数(263)、"
            "000300-沪深300(262)、399006-创业板指(265)、000905-中证500(262)、"
            "000015-上证红利(262)、000688-科创50(268)。"
            "⚠️ 中证红利 000922 上游**无此数据**（返回空列表）—— 红利口径请用 000015 上证红利。"
        )
    ),
    days: int = Query(365, ge=1, le=1000, description="向前取多少个自然日"),
):
    """获取指数级「恐惧贪婪指数」日线（沪深大盘监控页）

    数据源为上游 `/cn/market/fear_greed`，**直连不落库**，原因见 README 说明：

    本地 `stocks_fear_greed` 表虽然字段与上游完全一致（trade_date / index_code /
    close / fear_greed / vol_score / mom_score），但里面存的是**个股**的恐惧贪婪
    （由 job_update_stock_greedy_data 本地计算写入），`index_code` 列实际放的是
    股票代码 —— 例如 `000001` 是平安银行（close≈11.73 元）而不是上证指数
    （close≈3949 点）。若把上游指数数据写进同一张表，主键 (trade_date, index_code)
    会与个股数据直接冲突并**覆盖掉平安银行的历史**。故指数维度单独走上游。

    ⚠️ 别把「本地能取到某指数的行情」当成「这里也支持该指数」：两者是不同链路。
    例如 `databull.get_stock_history('000922')` 能拿到 410 行行情、且本地
    `build_fear_greed_index` 也能算出情绪分，但本接口依赖的是上游的
    `get_market_fear_greed`，其对 000922 返回空。若日后要让 000922 生效，
    要么等上游补齐，要么在这里加一条「本地计算」的兜底分支（需另建表避免与个股冲突）。

    ⚠️⚠️ 本路由 `@cache(expire=3600)`：上游**补齐数据后最多 1 小时才可见**。
    曾据此误判「000688 科创50 只有 1 天数据」—— 实为上游刚接入时缓存住了那条响应，
    稍后上游回填了历史，缓存到期即返回完整序列（近一年 268 条）。
    排查「某指数没数据」时请**换一个 days 参数**（cache key 含 query 参数）绕过缓存再测，
    否则会把缓存状态当成上游能力。

    字段说明：
    - fear_greed  综合指数 0~100（越高越贪婪）
    - vol_score   波动率分项
    - mom_score   动量分项
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')

    df = databull.get_market_fear_greed(
        index_code=index_code, start_date=start_date, end_date=end_date
    )
    if df is None or df.empty:
        logger.warning(f"指数 {index_code} 恐惧贪婪数据为空")
        return []

    # get_market_fear_greed 内部走 _to_dataframe(默认 date_col="date")，而上游返回的
    # 日期列名是 `trade_date` —— 列名对不上，所以**不会**被设成索引，
    # trade_date 仍是一个普通列（这也是下面能直接取 row['trade_date'] 的原因）。
    # reset_index() 只在恰好有名为 index 的列时才可能撞名，这里保留它是为了
    # 万一将来上游/封装对齐了列名也不会崩。排序保证前端折线是从旧到新。
    df = df.reset_index().sort_values('trade_date')
    records = []
    for row in df.to_dict('records'):
        trade_date = row.get('trade_date')
        records.append({
            'trade_date': trade_date.strftime('%Y-%m-%d') if hasattr(trade_date, 'strftime') else str(trade_date),
            'index_code': row.get('index_code') or index_code,
            'close': row.get('close'),
            'fear_greed': row.get('fear_greed'),
            'vol_score': row.get('vol_score'),
            'mom_score': row.get('mom_score'),
        })
    return records


@market_router.get('/market/growth_value')
@cache(expire=1800)
def get_market_growth_value(
    days: int = Query(250, ge=20, le=2000, description='返回最近 N 个交易日（1 个点/日）'),
):
    """成长 vs 价值风格强弱：创业板指(399006) ÷ 上证红利(000015)

    比值上行 = 成长跑赢价值，下行 = 价值跑赢成长。返回的 `points` 里同时带
    两条成分指数的**归一化净值**（起点 1.0），前端叠在副轴上就能区分
    「比值上行是成长涨出来的、还是红利跌出来的」—— 只看比值曲线看不出这一点。

    ⚠️ 价值腿是**上证红利 000015**，不是中证红利 000922：上游指数目录里
    000922.CSI 名称确实是「中证红利」，但 `/cn/index/history` 对它（以及
    399922.SZ）返回空，只有目录条目没有 K 线，直连上游同样为空。
    详见 service/growth_value_service.py 顶部说明。

    缓存 30 分钟：这是日线数据，只有最新一根会随盘中变动，刷太勤没意义。
    """
    try:
        return GrowthValueService.get_series(days=days)
    except GrowthValueError as e:
        # 入参问题 → 422；取数失败 → 503。都不打栈给前端。
        msg = str(e)
        status = 422 if 'days' in msg else 503
        raise HTTPException(status_code=status, detail=msg)


@market_router.get('/market/news')
def get_news(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200)
):
    """获取市场新闻"""
    news = MarketNewsService.get_by_time_range(limit=page_size)
    return news


@market_router.get('/market/search_news')
def search_news(
    keyword: str = Query('', description="在新闻摘要（digest）中模糊搜索"),
    stock_code: str = Query(None, description="按关联股票代码精确匹配"),
    start_time: str = Query(None, description="起始时间，ISO8601"),
    end_time: str = Query(None, description="结束时间，ISO8601"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    relation_level_only: bool = Query(
        True,
        description="是否只返回「已关联」新闻（relation_level > 0）。"
                    "个股新闻列表与事件驱动「全部新闻」需传 false，"
                    "否则 relation_level 为 0/NULL 的新闻会被静默丢弃。"
    )
):
    """搜索市场新闻（按时间倒序分页）"""
    try:
        start_dt = None
        end_dt = None
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

        result = MarketNewsService.search(
            keyword=keyword,
            stock_code=stock_code,
            start_time=start_dt,
            end_time=end_dt,
            page=page,
            page_size=page_size,
            relation_level_only=relation_level_only
        )
        return result
    except Exception as e:
        logger.error(f"Unexpected error in search_news: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
