"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_update_factors import job_update_stock_factor
from service.etf_service import EtfService
from utils.logger import logger

if __name__ == '__main__':

    """
    对 ETF 监控清单做一次全量分析：恐贪指数 + 技术面因子。

    清单直接读 etf_watchlist 表 —— 与「ETF 洞察」页面同一份数据。这里原先写死了 8 只
    ETF，早就和页面上的清单脱节了；新加入监控的 ETF 也不会被算到。
    注意 asset_type='etf' 必须显式传：ETF 与个股的行情接口不同，靠代码号段猜会漏。
    """

    etfs = EtfService.list_watchlist()
    logger.info(f"ETF 全量分析开始，共 {len(etfs)} 只")

    for etf in etfs:
        # 恐贪指数：整段重算
        job_update_stock_greedy_data(index_code=etf.symbol, override_all=True)

        # 技术面因子：清空后整段重写（-1200 天约覆盖 800 个交易日，足够 52 周区间因子的窗口）
        job_update_stock_factor(stock_code=etf.symbol, asset_type='etf',
                                save_last=False, time_period=-1200)

    logger.info("ETF 全量分析结束")
