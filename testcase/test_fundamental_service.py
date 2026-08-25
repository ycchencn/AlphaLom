"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest
from service.fundamental_service import compute_fundamental_scores

class TestFundamentalService(unittest.TestCase):

    def test_atr_factor(self):
        stock_code = '301308'
        res = compute_fundamental_scores(stock_code=stock_code)
        print()
        print(res)

if __name__ == '__main__':
    unittest.main()
