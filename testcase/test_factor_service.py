"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest
from utils.beta_calculate import calculate_beta
from utils.common import get_today, get_date_by_n
from service.factor_cal_service import FactorCalService

class TestFactorService(unittest.TestCase):

    def test_atr_factor(self):
        stock_code = '688362'
        start_date = get_date_by_n(-365)
        end_date = get_today(_format='%Y%m%d')
        cls = FactorCalService()
        df = cls._prepare_data(stock_code, start_date, end_date)
        atr = FactorCalService.update_atr_factor(df)
        self.assertIsNotNone(atr)

    def test_update_closing_strength(self):
        stock_code = '688362'
        start_date = get_date_by_n(-365)
        end_date = get_today(_format='%Y%m%d')
        cls = FactorCalService()
        df = cls._prepare_data(stock_code, start_date, end_date)
        df = FactorCalService.update_closing_strength(df)
        # print(df['closing_strength'])
        self.assertIsNotNone(df)

    def test_calculate_beta(self):
        stock_code = '300124'
        market_index = "000001"
        start_date = "20251101"
        end_date = get_today()
        beta = calculate_beta(stock_code, market_index, start_date=start_date, end_date=end_date)
        self.assertIsNotNone(beta)


if __name__ == '__main__':
    unittest.main()
