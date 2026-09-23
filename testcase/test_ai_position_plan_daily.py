"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

调仓计划（ai_position_plan_daily）的回归测试。

重点钉住一类「配置缺失被误报成运行时异常」的缺陷：
    llm_prompt 为 NULL/空时，`Template(llm_prompt).safe_substitute()` 会抛
    `TypeError: expected string or bytes-like object, got 'NoneType'`
    —— 报错点是 string.Template 内部的正则替换，与业务语义完全无关，
    运维看到日志只会以为程序出了 bug，而真实原因是「该组合根本没配提示词」。

全部用例都不碰网络：
    job_position_plan_daily 的前置校验发生在任何取数/LLM 调用之前，
    因此「缺配置」用例都是瞬时返回；「有配置」用例靠打桩截住后续步骤。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategy import ai_position_plan_daily as mod
from string import Template


class TestTemplateNoneCrashSignature(unittest.TestCase):
    """先钉住崩溃原理本身，避免以后有人把前置校验删掉还以为「本来就不报错」。"""

    def test_template_none_only_fails_at_substitute(self):
        # 构造阶段不报错 —— 这正是缺陷隐蔽的原因：异常点与根因隔了一层
        template = Template(None)
        with self.assertRaises(TypeError) as ctx:
            template.safe_substitute(x='1')
        self.assertIn('NoneType', str(ctx.exception))


class TestMissingLlmPromptGuard(unittest.TestCase):
    """缺 llm_prompt 时必须「明确跳过」而不是抛异常。"""

    def setUp(self):
        self._originals = {}

    def _patch(self, name, value):
        self._originals.setdefault(name, getattr(mod, name))
        setattr(mod, name, value)

    def tearDown(self):
        for name, value in self._originals.items():
            setattr(mod, name, value)

    def _stub_portfolio(self, **overrides):
        """构造一个最小可用的组合信息，默认「配置齐全」，用例只改关心的字段。"""
        info = {
            'name': '测试组合',
            'llm_prompt': '请分析 $holdings_text 并输出',
            'llm_setting': {'platform': 'aliyun', 'model': 'qwen3.7-plus'},
            'position_plan': None,
            'current_cash': 10000,
            'desc': '测试用',
        }
        info.update(overrides)
        return info

    def _install_stubs(self, portfolio_info, calls):
        """把函数体里所有外部依赖换成打桩，并记录被调用的痕迹。"""
        self._patch('InvestmentPortfolioService', type('S', (), {
            'get_by_portfolio_id': staticmethod(lambda pid: portfolio_info),
        }))
        # 下面这些一旦被调用就说明「不该往下走的代码往下走了」
        self._patch('databull', type('D', (), {
            'get_index_history': staticmethod(lambda **kw: calls.append('index_history') or []),
        }))
        self._patch('PortfolioAssetsService', type('P', (), {
            'get_all_by_portfolio_id': staticmethod(lambda pid: calls.append('holdings') or []),
        }))
        self._patch('StockService', type('K', (), {
            'get_monitoring_stock_pool': staticmethod(lambda **kw: calls.append('stock_pool') or []),
        }))
        self._patch('MarketNewsService', type('N', (), {
            'get_by_time_range': staticmethod(lambda **kw: calls.append('news') or []),
        }))
        self._patch('get_model_by_setting', lambda **kw: calls.append('llm_client') or type('M', (), {
            'model': 'stub', 'role_base': '', 'response_format': 'text',
            'set_response_json': lambda self: None,
            # 反向用例会走到真正的模型调用，这里直接抛错截断 —— 断言只关心「之前的取数有没有发生」
            'create_completion': lambda self, **kw: (_ for _ in ()).throw(RuntimeError('stub: 不真的调模型')),
        })())

    def _run_without_prompt(self, prompt_value):
        calls = []
        self._install_stubs(self._stub_portfolio(llm_prompt=prompt_value), calls)
        result = mod.job_position_plan_daily(portfolio_id=99, use_agent=False)
        return result, calls

    def test_none_prompt_returns_false_without_side_effects(self):
        result, calls = self._run_without_prompt(None)
        self.assertFalse(result)
        # 关键断言：一处外部调用都不该发生（校验必须在取数/构造客户端之前）
        self.assertEqual(calls, [])

    def test_empty_prompt_also_guarded(self):
        # 空字符串走的是同一条分支：模板替换不会崩，但组合同样没有可用提示词
        result, calls = self._run_without_prompt('')
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_whitespace_prompt_also_guarded(self):
        result, calls = self._run_without_prompt('   \n  ')
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_missing_portfolio_returns_false(self):
        calls = []
        self._install_stubs(None, calls)
        result = mod.job_position_plan_daily(portfolio_id=99, use_agent=False)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_valid_prompt_reaches_data_loading(self):
        # 反向用例：配置齐全时必须真的往下走，否则前置校验就成了「全跳过」
        calls = []
        self._install_stubs(self._stub_portfolio(), calls)
        try:
            mod.job_position_plan_daily(portfolio_id=99, use_agent=False)
        except Exception:
            # 打桩到这一步之后必然因为缺 LLM 而失败，这里只关心「有没有走到取数」
            pass
        self.assertIn('holdings', calls)
        self.assertIn('stock_pool', calls)


class TestBatchSkipSemantics(unittest.TestCase):
    """批量任务里，缺 prompt 应当被「跳过」而非记为「运行失败」。"""

    def test_batch_skips_missing_prompt(self):
        calls = []

        originals = {}
        for name in ('InvestmentPortfolioService', 'FactorValueService', 'job_position_plan_daily'):
            originals[name] = getattr(mod, name)

        portfolios = [
            {'portfolio_id': 1, 'llm_prompt': 'ok', 'llm_setting': {'platform': 'a'}, 'position_plan': None},
            {'portfolio_id': 2, 'llm_prompt': None, 'llm_setting': {'platform': 'a'}, 'position_plan': None},
            {'portfolio_id': 3, 'llm_prompt': '', 'llm_setting': {'platform': 'a'}, 'position_plan': None},
            {'portfolio_id': 4, 'llm_prompt': 'ok', 'llm_setting': None, 'position_plan': None},
            {'portfolio_id': 5, 'llm_prompt': 'ok', 'llm_setting': {'platform': 'a'},
             'position_plan': {'date': '20260922'}},
        ]

        try:
            mod.InvestmentPortfolioService = type('S', (), {
                'get_all': staticmethod(lambda: portfolios),
            })
            mod.FactorValueService = type('F', (), {
                'is_trading_day': staticmethod(lambda: True),
            })
            mod.job_position_plan_daily = lambda portfolio_id=None, **kw: calls.append(portfolio_id)
            mod.job_position_plan_daily_all()
        finally:
            for name, value in originals.items():
                setattr(mod, name, value)

        # 只有 #1 满足「有 prompt + 有 llm_setting + 无 position_plan」
        self.assertEqual(calls, [1])


if __name__ == '__main__':
    unittest.main()
