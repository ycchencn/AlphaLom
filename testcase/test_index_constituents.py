"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import unittest
import akshare as ak
from utils.logger import logger, df_cache
from service import IndexConstituentsService, StockService

@df_cache()
def get_stock_hk_famous_spot_em():
    return ak.stock_hk_famous_spot_em()

class TestIndexConstituents(unittest.TestCase):

    def test_fet(self):

        index_code = "000690"

        zz500_df = IndexConstituentsService.get_index_constituents_with_cache(index_code=index_code)

        for row in zz500_df.itertuples():

            res = StockService.upsert_stock({
                'symbol': row.stock_code,
                'ts_code': '-',
                'name': row.stock_name,
                'market': 'cn',
                'securities_type': 'stock',
                'area': '-',
            })
            # print(res)

            print(f"股票代码={row.stock_code}, 名称={row.stock_name}, 加入时间={row.add_date}")
            IndexConstituentsService.create(_index_code=index_code, stock_code=row.stock_code, stock_name=row.stock_name, add_date=row.add_date)



if __name__ == '__main__':
    unittest.main()
