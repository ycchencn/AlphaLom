"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest
from utils.beta_calculate import calculate_beta
from utils.common import get_today


class TestFactorService(unittest.TestCase):

    def test_calculate_beta(self):
        stock_code = '300124'
        market_index = "000001"
        start_date = "20251101"
        end_date = get_today()
        beta = calculate_beta(stock_code, market_index, start_date=start_date, end_date=end_date)
        self.assertIsNotNone(beta)


if __name__ == '__main__':
    unittest.main()
