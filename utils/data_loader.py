"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 数据接口唯一接入点：全项目共用的 DataBull 客户端在这里构造，业务代码一律
 `from utils.data_loader import databull` 使用。

 客户端实现来自官方 SDK `databull`（pip install databull），**不再是仓库内的
 service/databull_api.py**。端点路径与参数规整（裸码 / 日期格式）改由 SDK 单一维护，
 避免本地副本被整体覆盖后静默回退（历史上已发生三次）。

 ⚠️ 与旧本地客户端的行为差异（迁移时逐点确认过，新增调用请照此办理）：

 1. **失败抛 DataBullError**，不再 print 后返回 None。原先靠 `result or {}` 兜底、
    或靠 `is None` 判断「没数据」的调用点，必须改成 try/except。
 2. **返回形态以上游真实信封为准**，SDK 只对 get_etf_info 做了自动解包：
      - 裸对象：/cn/stock/tick、/cn/stock/info
      - {code, data} 信封：/cn/stock/profile、/cn/etfs/etf_pcf、
        /cn/etfs/etf_composition、/cn/stocks、/cn/stock/financial_data
      - 裸数组：/cn/index/history、/cn/stock/history、/cn/etf/history、
        /cn/market/sector_data/{sw1|sw2|sw3}
    信封型由调用方自行取 `data`。
 3. **get_stock_financial_data 的 report_type 在 SDK 里有默认值 'Balance'**（旧本地版
    故意设计成必传）。本项目调用点一律显式传 'PershareIndex'；漏传不会报错，会静默
    取错报表，新增调用点务必显式传。
 4. get_etf_list 的路径在 SDK 里不带尾斜杠，会多吃一次 307 跳转（功能不受影响）。

 历史备注（已失效）：本模块原先 import service.databull_api，而 service/__init__ 又会
 反向导入各 Service 模块，构成 utils.data_loader → service.__init__ → service.xxx →
 utils.data_loader(半初始化) 的循环导入，所以 service 包内一律只能「函数内延迟 import」。
 改用外部包 databull 后本模块**不再依赖 service 包**，该约束随之消失。
"""

from databull import DataBull
from config import databull_host, databull_key


class _DataBull(DataBull):
    """SDK 缺陷的最小绕行层。

    本类**只放「已在 SDK 复现的 bug」的绕行，不放语义兼容层**。SDK 修好后删掉对应方法；
    类清空了就把整个类删掉、下面的实例化改回 `DataBull`。
    """

    def get_etf_list(self, market: str = 'cn', q=None, exchange=None, search=None):
        """绕行：SDK 原实现路径不带尾斜杠，在当前线上**必然 401**。

        实测：`GET https://api.databull.cn/cn/etfs`（SDK 写法）会 307 跳到
        **http://**api.databull.cn/cn/etfs/，再 301 回到 https —— 跨协议重定向时
        requests 会丢弃 Authorization 头，最终稳定得到
        401「缺少 API 凭证」。带尾斜杠直连（`/cn/etfs/`）是 200。
        旧本地客户端早就在注释里写下过这个结论（「文档要求路径以 / 结尾」），SDK 漏了。

        修法（SDK 侧一行）：`client.py::get_etf_list` 里
            return self._request(f"{market}/etfs", params=params or None)
        改成
            return self._request(f"{market}/etfs/", params=params or None)
        """
        params = {}
        keyword = q or search
        if keyword:
            params['q'] = keyword
        if exchange:
            params['exchange'] = exchange
        return self._request(f'{market}/etfs/', params=params or None)


# ⚠️ 缺 DATABULL_KEY 时 SDK 会在**构造阶段**就抛 DataBullError（旧本地版会带着空 Bearer
# 继续跑、等到第一次请求才失败）。也就是说未配置密钥的环境是在 import 阶段就失败，
# 而不是某个接口 401 —— 属「快速失败」，但部署时别再以为「没配 key 也能起来」。
databull = _DataBull(api_key=databull_key, base_url=databull_host)
