"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest

from databull import DataBullError
from utils.data_loader import databull

class TestDatajiji(unittest.TestCase):

    def test_get_stocks(self):
        res = databull.get_stock_list()
        self.assertIsNotNone(res)

    def test_get_company(self):
        # SDK 返回 {code, data} 信封，公司资料在内层 data
        resp = databull.get_company_profile('688008')
        res = resp.get('data') if isinstance(resp, dict) else resp
        self.assertIsNotNone(res['business_scope'])

    def test_get_company_alias_returns_envelope(self):
        """固定住 SDK 的别名契约：get_company 转发 get_company_profile，返回完整体。"""
        resp = databull.get_company('688008')
        self.assertIn('data', resp)
        self.assertIsNotNone(resp['data'].get('business_scope'))

    def test_get_history(self):
        index_code = '603163'
        res = databull.get_stock_history(index_code, start_date='20240101', end_date='20240115')
        self.assertIsNotNone(res)

    def test_get_index_history(self):
        index_code = '000300'
        res = databull.get_index_history(index_code, start_date='20210101', end_date='20210115')
        self.assertIsNotNone(res)

    def test_get_tick(self):
        code = '399001'
        res = databull.get_realtime(code, tick_type='index')
        self.assertIsNotNone(res)

    def test_get_index(self):
        code = '000001'
        res = databull.get_realtime(code, tick_type='index')
        self.assertIsNotNone(res)

    def test_get_tick_etf(self):
        code = '510500'
        res = databull.get_realtime(code, tick_type='etf')
        self.assertIsNotNone(res)

    def test_etfs(self):
        # 注意：这条同时守护 utils/data_loader._DataBull.get_etf_list 的绕行
        # （SDK 原路径 /cn/etfs 不带尾斜杠 → 307 到 http 再 301 回 https →
        # requests 丢弃 Authorization → 401）。若有人删掉绕行，这里会红。
        res = databull.get_etf_list(market='cn')
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0, 'ETF 清单为空，检查 get_etf_list 的尾斜杠绕行是否被删除')
        self.assertTrue(res[0].get('symbol') and res[0].get('name'))

    def test_error_raises_not_none(self):
        """迁移后固定住的契约：失败抛 DataBullError，不再返回 None。

        全项目仍有大量 `result or {}` 式兜底，都是按旧本地客户端的
        「print 后返回 None」语义写的；这条测试保证「有人把 SDK 换回静默
        返回 None 的实现」时会立刻红。

        入参用 get_etf_info('999999')：上游稳定回 HTTP 400（ETF 代码格式非法）。
        注意**不要**换成「代码合法但本地无数据」的入参 —— 那种情况 SDK 回
        200 + 空 data，返回 None 而**不抛异常**（原因见 client.last_empty_reason），
        那样写这条测试必然红。
        """
        with self.assertRaises(DataBullError) as ctx:
            databull.get_etf_info('999999')
        self.assertEqual(ctx.exception.status, 400)

    def test_get_stock_financial_data(self):
        index_code = '000001'
        res = databull.get_stock_financial_data(
            index_code,
            start_date='20260101',
            end_date='20260611',
            report_type='PershareIndex'
        )
        print(res)
        self.assertIsNotNone(res)

if __name__ == '__main__':
    unittest.main()
