"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 ⚠️ 循环导入约束：本模块 import 了 service 包（会执行 service/__init__，进而导入各 Service
 模块），因此 **service 包内的模块不得在模块顶层 import 本模块的 databull**，否则构成
     utils.data_loader → service.__init__ → service.xxx → utils.data_loader(半初始化)
 的循环，报 ImportError: cannot import name 'databull' from partially initialized module。
 它只在「入口先 import utils.data_loader」时才暴露（testcase/test_databull.py、
 job/dump_stocks_dcf.py 就是这样炸的），平时先 import service 的调用方看不出来。
 service/stock.py / fundamental_service.py / etf_service.py 已改为在函数体内延迟导入，
 新增调用请沿用「函数内 import」，不要提到模块顶层。
"""

from service.databull_api import DataBull
from config import databull_host, databull_key

databull = DataBull(api_key=databull_key, base_url=databull_host)
