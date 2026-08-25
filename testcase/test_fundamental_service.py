"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest
from service.fundamental_service import compute_fundamental_scores
from utils.common import get_today, get_date_by_n

class TestFundamentalService(unittest.TestCase):

    def test_atr_factor(self):
        stock_code = '301308'
        res = compute_fundamental_scores(stock_code=stock_code, start_date=get_date_by_n(-365), end_date=get_today())
        print(res)

if __name__ == '__main__':
    unittest.main()
