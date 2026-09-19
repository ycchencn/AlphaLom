"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest

from utils.data_loader import databull

class TestDatajiji(unittest.TestCase):

    def test_get_stocks(self):
        res = databull.get_stock_list()
        self.assertIsNotNone(res)

    def test_get_company(self):
        res = databull.get_company('688008')
        self.assertIsNotNone(res['business_scope'])
        self.assertIsNotNone(res)

    def test_get_history(self):
        index_code = '603163'
        res = databull.get_history(index_code, start_date='20240101', end_date='20240115')
        # print(res)
        self.assertIsNotNone(res)

    def test_get_index_history(self):
        index_code = '000300'
        res = databull.get_index_history(index_code, start_date='20210101', end_date='20210115')
        print(res)
        self.assertIsNotNone(res)

    def test_get_tick(self):
        code = '399001'
        res = databull.get_last_tick(code, tick_type='index')
        self.assertIsNotNone(res)

    def test_get_index(self):
        code = '000001'
        res = databull.get_last_tick(code, tick_type='index')
        self.assertIsNotNone(res)

    def test_get_tick_etf(self):
        code = '510500'
        res = databull.get_last_tick(code, tick_type='etf')
        self.assertIsNotNone(res)

if __name__ == '__main__':
    unittest.main()
