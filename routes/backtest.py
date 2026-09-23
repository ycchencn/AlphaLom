"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

组合回测（等权 · 买入持有）对外接口。

⚠️ 本模块的路由必须写同步 `def`：Service 层全程是阻塞调用（requests 取上游行情 + pandas 计算），
写成 `async def` 会占死唯一的事件循环，一个 20 只标的的回测能把全站接口一起拖住。
同步 `def` 由 Starlette 自动丢进 anyio 线程池。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi_cache.decorator import cache

from app.fastapi_app import api_prefix
from service.portfolio_backtest_service import (
    BENCHMARK_OPTIONS,
    DEFAULT_BENCHMARK,
    MAX_SYMBOLS,
    BacktestError,
    PortfolioBacktestService,
)
from utils.logger import logger

backtest_router = APIRouter(prefix=api_prefix, tags=['组合回测'])


@backtest_router.get('/portfolio_backtest_benchmarks')
def get_backtest_benchmarks():
    """可选的基准指数清单（前端下拉的唯一来源，不写死在前端）。"""
    return [dict(item) for item in BENCHMARK_OPTIONS]


@backtest_router.get('/portfolio_backtest')
# 历史行情是日频数据，只有最新一根会随盘中变动；30 分钟够用，也让「改一个参数重跑」秒回。
# ⚠️ @cache 必须紧贴被装饰的函数（下面没有别的装饰器），否则缓存键会拿错参数。
@cache(expire=1800)
def run_portfolio_backtest(
    symbols: str = Query(
        ...,
        description='标的代码，逗号分隔（股票与 ETF 可混选），最多 %d 个。例：600519,000001,510300' % MAX_SYMBOLS,
    ),
    start_date: Optional[str] = Query(
        None, description='起始日期 YYYYMMDD 或 YYYY-MM-DD，留空取近 1 年'
    ),
    end_date: Optional[str] = Query(None, description='结束日期，留空取今天'),
    init_cash: float = Query(1000000, gt=0, description='初始资金，仅用于金额换算，不影响收益率'),
    benchmark: Optional[str] = Query(
        DEFAULT_BENCHMARK,
        description='基准指数裸码（见 /portfolio_backtest_benchmarks），传空字符串则不对比基准',
    ),
):
    """组合回测：等权买入持有，输出净值/回撤曲线与绩效指标。

    - 权重固定等权（每只 1/N），区间内不再调仓，暂不支持自定义权重与再平衡
    - 无数据的标的会被跳过并在 `skipped` 中说明，等权在剩余标的上重新分配
    - 行情为**不复权价**，分红除权会造成收益低估（`warnings` 里也会带回这一提示）
    """
    try:
        return PortfolioBacktestService.run(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            init_cash=init_cash,
            benchmark=benchmark,
        )
    except BacktestError as e:
        # 入参/数据不满足前提：400 带上可直接展示的原因，不用前端猜
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception('组合回测执行失败')
        raise HTTPException(status_code=500, detail=f'组合回测计算失败：{e}')
