"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

上市公司公告（databull /cn/stock/announcements）接入的单元测试。

覆盖三块：
1. 分类标签推断（纯函数，不碰网络 —— 规则表改了这里最先把问题暴露出来）；
2. 港股/美股分支（上游只覆盖 A 股，必须返回 supported=false 而不是发必然 404 的请求）；
3. 上游返回结构的解包（裸数组 + 响应头分页元信息）。

⚠️ 分类标签是**关键词规则**而不是上游 category 码映射（上游码表不可得），
   所以「某个标题该归哪类」在这里显式固定住，避免后人改规则时无声改变行为。
"""

import unittest
from unittest.mock import patch

from routes.stock import (
    ANNOUNCEMENT_COLUMN_NAMES,
    _classify_announcement,
    get_stock_announcements,
)


class TestAnnouncementClassify(unittest.TestCase):
    """分类标签推断规则。"""

    def test_regular_report(self):
        self.assertEqual(_classify_announcement('2026年三季度报告'), '定期报告')
        self.assertEqual(_classify_announcement('2026年半年度报告全文'), '定期报告')
        self.assertEqual(_classify_announcement('关于2026年度业绩预告的公告'), '定期报告')

    def test_governance_across_intervening_words(self):
        """治理类关键词要能跨越「第六届」「第十一次」这类插入词。

        ⚠️ 早期规则用的是「董事会决议」这种固定短语，遇到
        「第六届董事会第十一次会议决议公告」就漏判了 —— 现在用机构词。
        """
        self.assertEqual(_classify_announcement('第六届董事会第十一次会议决议公告'), '公司治理')
        self.assertEqual(_classify_announcement('第七届监事会第五次会议决议公告'), '公司治理')
        self.assertEqual(_classify_announcement('关于召开2026年第二次临时股东会的提示性公告'), '公司治理')

    def test_buyback_beats_generic_shares(self):
        """「回购」必须先于「股份」类关键词命中。"""
        self.assertEqual(_classify_announcement('关于回购公司A股股份的进展公告'), '回购增持')

    def test_major_contract_is_operations(self):
        """「重大合同」归经营情况，不是重大事项 —— 签合同是日常经营动作。"""
        self.assertEqual(_classify_announcement('关于签订重大合同的公告'), '经营情况')

    def test_risk_notice(self):
        self.assertEqual(_classify_announcement('关于收到深圳证券交易所问询函的公告'), '风险提示')

    def test_fallback(self):
        """命中不了要给兜底标签，不能返回空串（前端要统一渲染标签位）。"""
        self.assertEqual(_classify_announcement('H股公告（翌日披露报表）'), '其他公告')
        self.assertEqual(_classify_announcement(''), '其他公告')
        self.assertEqual(_classify_announcement(None), '其他公告')


class TestAnnouncementRoute(unittest.TestCase):
    """路由层行为。"""

    def test_invalid_symbol_rejected(self):
        with self.assertRaises(Exception):
            get_stock_announcements.__wrapped__('1234567')

    @patch('routes.stock.StockService.get_stock_by_symbol')
    @patch('routes.stock.databull.get_stock_announcements_paged')
    def test_non_cn_market_not_supported(self, mock_api, mock_stock):
        """港股/美股：上游该端点只覆盖 A 股，必须返回 supported=false。

        ⚠️ 关键：不能去发那个必然 404 的请求 —— 断言 mock_api **未被调用**。
        """
        mock_stock.return_value = {'market': 'hk', 'name': '腾讯控股'}

        result = get_stock_announcements.__wrapped__('00700')

        self.assertFalse(result['supported'])
        self.assertEqual(result['empty_reason'], 'market_not_supported')
        self.assertEqual(result['items'], [])
        mock_api.assert_not_called()

    @patch('routes.stock.StockService.get_stock_by_symbol')
    @patch('routes.stock.databull.get_stock_announcements_paged')
    def test_cn_market_normalizes_items(self, mock_api, mock_stock):
        """A 股正常路径：字段归一 + 分类标签 + 分页元信息透传。"""
        mock_stock.return_value = {'market': 'cn', 'name': '宁德时代'}
        mock_api.return_value = ([
            {
                'id': 1,
                'announcement_id': '1225611272',
                'title': '关于回购公司A股股份的进展公告',
                'announcement_date': '2026-10-19',
                'category': '01010503||010112||011513',
                'pdf_url': 'http://static.cninfo.com.cn/finalpage/2026-10-19/1225611272.PDF',
                'pdf_size_kb': 138,
                'page_column': 'SZCY',
            },
        ], {
            'total': 10, 'page': 1, 'page_size': 20,
            'has_more': True, 'empty_reason': None,
        })

        result = get_stock_announcements.__wrapped__('300750')

        self.assertTrue(result['supported'])
        self.assertEqual(result['total'], 10)
        self.assertTrue(result['has_more'])
        item = result['items'][0]
        self.assertEqual(item['date'], '2026-10-19')
        self.assertEqual(item['category'], '回购增持')
        self.assertEqual(item['column_name'], '创业板')
        # 上游原始码保留但不是主标签
        self.assertEqual(item['raw_category'], '01010503||010112||011513')
        self.assertEqual(item['pdf_size_kb'], 138)

    @patch('routes.stock.StockService.get_stock_by_symbol')
    @patch('routes.stock.databull.get_stock_announcements_paged')
    def test_upstream_error_does_not_500(self, mock_api, mock_stock):
        """上游异常不能炸 500 —— 公告只是个股页的一个补充区块。"""
        mock_stock.return_value = {'market': 'cn', 'name': '测试'}
        mock_api.side_effect = Exception('upstream boom')

        result = get_stock_announcements.__wrapped__('600000')

        self.assertTrue(result['supported'])
        self.assertEqual(result['empty_reason'], 'upstream_error')
        self.assertEqual(result['items'], [])

    def test_column_names_mapping(self):
        """巨潮板块码 → 可读名。"""
        self.assertEqual(ANNOUNCEMENT_COLUMN_NAMES['SZZB'], '深主板')
        self.assertEqual(ANNOUNCEMENT_COLUMN_NAMES['SZCY'], '创业板')
        self.assertEqual(ANNOUNCEMENT_COLUMN_NAMES['SHZB'], '沪主板')
        self.assertEqual(ANNOUNCEMENT_COLUMN_NAMES['SHKCB'], '科创板')


if __name__ == '__main__':
    unittest.main()
