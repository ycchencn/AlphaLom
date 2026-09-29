"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 个股「入池后一键分析」的编排任务：把加自选后要展示的派生数据依次算出来。

 ⚠️ 下面两点是刻意设计，别按「业务故事顺序」重排：

 1. **最新报价（ohlc_last）排在第一个算。**
    它是列表 / 详情页最显眼的字段（价格 + 涨跌幅），成本却最低（一次实时接口 ~0.1s）；
    而后面的 DCF / 技术面要调大模型，实测**单只约 6 分钟**。
    原先它排在最末 —— 加自选后报价要等整条链路跑完才出现（任务队列 prefetch=1 串行消费，
    多只一起加、或撞上日更批量派发的积压时还要排队叠加），
    用户看到的就是「加了股票，可 ohlc_last 一直是空的」。
    注：web 侧「加自选」时还会**同步补写一次**报价（见 routes/stock.py），
    所以正常入池瞬间就有价格，这里的位置主要保证「重新分析」等异步路径也先刷报价。

 2. **每个步骤互相隔离（失败的步骤只记日志、不让异常冒泡）。**
    job_server 捕获异常后直接 ACK 丢弃整个 job（不重试），所以任何一步抛异常若让它冒泡，
    后面的步骤就全都不会执行、对应字段全空。隔离后各字段互不牵连，
    单个上游抖动（大模型超时、行情接口偶发失败）不会连累其它数据。
"""

from service.stock import StockService
from models.database import db_session
from utils.logger import logger
from job.job_stock_dcf_model_analysis import job_stock_dcf_model_analysis
from job.job_update_stock_greedy_data import job_update_stock_greedy_data
from job.job_check_signal import job_check_signal
from job.job_update_factors import job_update_stock_factor
from job.job_stock_daily_update import job_fix_ohlc_last


def _run_step(label, fn, *args, **kwargs):
    """跑一个数据步骤；失败只记日志，不中断整条链路。

    失败后必须把**当前线程的 db_session 丢弃**（remove）：某个步骤可能因上游超时 /
    连接中断把会话留在「未回滚的坏事务」里（之后所有操作都会报
    `Can't reconnect until invalid transaction is rolled back`）。
    不重置会话的话，后面每个步骤都会跟着失败 —— 那就等于没做隔离。
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.exception(f'个股分析步骤失败（{label}），已跳过：{e}')
        try:
            db_session.remove()
        except Exception:
            pass
        return None


def job_stock_analysis(stock_code, send_notification=False):
    # 不在数据库则自动添加（从 API 补全名称 + 公司概况）。
    # 这一步**不隔离**：后面所有步骤都依赖「这一行存在」。所有投递路径都保证它已在库
    # （web 路由先 ensure_stock_from_api、批量脚本先 upsert_stock），此处实际是幂等空操作。
    StockService.ensure_stock_from_api(stock_code)

    # 最新报价：最先写（见文件头说明 1）
    _run_step('最新报价', job_fix_ohlc_last, stock_code)

    # 计算走势指标
    _run_step('恐惧贪婪走势', job_update_stock_greedy_data,
              index_code=stock_code, override_all=True)

    # 计算因子
    _run_step('技术因子', job_update_stock_factor,
              stock_code=stock_code, save_last=False, time_period=-1200)

    # DCF 模型分析（重：调大模型）
    _run_step('DCF 估值分析', job_stock_dcf_model_analysis,
              stock_code, send_notification=send_notification)

    # 技术分析（重：调大模型）
    _run_step('技术面信号', job_check_signal, stock_code)


if __name__ == '__main__':

    stock_codes = [
        '002156'
    ]

    for stock_code in stock_codes:
        job_stock_analysis(stock_code)
