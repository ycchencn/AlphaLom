"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

腾讯云 / 百度云大模型平台接入测试（不碰网络 / DB / Redis）。

验证：
  - PLATFORM_META 与 _PLATFORM_REGISTRY 含 tencent / baidu；
  - 设置页视图正确区分「已添加」与「待添加」——凭据只认数据库，
    库里没有配置行 = 该平台未添加 = 不可用；
  - 未添加 / 被禁用时 get_api_key(required=True) 明确抛错
    （不静默回退，**也不再回退到 .env**）。
"""

import sys, os, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llms import llm_platform as llm_platform_mod
from llms.llm_platform import (PLATFORM_META, get_api_key, list_addable_platforms,
                               list_platforms_view)
import llms


class TestLlmPlatforms(unittest.TestCase):
    """腾讯云 / 百度云接入校验。"""

    def test_platform_meta_has_tencent_and_baidu(self):
        self.assertIn('tencent', PLATFORM_META)
        self.assertIn('baidu', PLATFORM_META)
        self.assertEqual(
            PLATFORM_META['tencent']['default_base_url'],
            'https://api.hunyuan.cloud.tencent.com/v1',
        )
        self.assertEqual(
            PLATFORM_META['baidu']['default_base_url'],
            'https://qianfan.baidubce.com/v2',
        )

    def test_registry_has_tencent_and_baidu(self):
        self.assertIn('tencent', llms._PLATFORM_REGISTRY)
        self.assertIn('baidu', llms._PLATFORM_REGISTRY)
        # platform_name 与注册键一致（get_model_by_setting 据此实例化）
        self.assertEqual(llm_platform_mod.platform_label('tencent'), '腾讯云混元')
        self.assertEqual(llm_platform_mod.platform_label('baidu'), '百度云千帆')

    def test_view_only_lists_added_platforms(self):
        """
        库里有的 = 已添加（出现在 platform_rows）；没有的 = 待添加（出现在下拉候选）。

        ⚠️ 用一个假 overrides：既不碰真库，也能验证「未添加的平台不会出现在表格里」
        ——这正是本次语义变更的核心（以前 list_platforms_view 返回全部已注册平台）。
        """
        fake = {
            'tencent': {'enabled': True, 'api_key': 'v1:whatever'},
            'baidu': {'enabled': False},
        }
        with patch.object(llm_platform_mod, '_load_overrides', return_value=fake):
            rows = {v['platform']: v for v in list_platforms_view()}
            addable = {v['platform'] for v in list_addable_platforms()}

        # 已添加的两个在表格里
        self.assertIn('tencent', rows)
        self.assertIn('baidu', rows)
        self.assertTrue(rows['tencent']['added'])
        self.assertFalse(rows['baidu']['enabled'])
        self.assertEqual(rows['tencent']['label'], '腾讯云混元')
        self.assertEqual(rows['baidu']['label'], '百度云千帆')
        # 没添加的不在表格里，而在候选里（fake 里只有 tencent/baidu 被添加）
        self.assertNotIn('deepseek', rows)
        self.assertIn('deepseek', addable)
        # 已添加的不该再出现在下拉里（否则会重复添加）
        self.assertNotIn('tencent', addable)
        self.assertNotIn('baidu', addable)
        self.assertEqual(rows['baidu']['default_base_url'], 'https://qianfan.baidubce.com/v2')

    def test_unadded_platform_has_no_key(self):
        """未添加 = 不可用（enabled=False、api_key=None），不是「enabled 但没 key」。"""
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}):
            setting = llm_platform_mod.get_platform_setting('tencent')
        self.assertFalse(setting['added'])
        self.assertFalse(setting['enabled'])
        self.assertIsNone(setting['api_key'])

    def test_env_api_key_no_longer_fallback(self):
        """
        .env 里即使有 *_APIKEY 也不能激活平台 —— 凭据只从数据库取。

        这是本次改动的核心约束：把 DEEPSEEK_APIKEY 塞进环境变量后，
        该平台仍应判定为「未添加」。
        """
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}), \
             patch.dict(os.environ, {'TENCENT_APIKEY': 'sk-should-be-ignored'}):
            self.assertIsNone(llm_platform_mod._env_default_api_key('tencent'))
            with self.assertRaises(ValueError):
                get_api_key('tencent', required=True)

    def test_get_api_key_required_raises_when_unconfigured(self):
        # 未添加 → 明确抛错（不静默回退到别的平台，也不回退到 .env）
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}):
            with self.assertRaises(ValueError):
                get_api_key('tencent', required=True)
            with self.assertRaises(ValueError):
                get_api_key('baidu', required=True)

    def test_get_api_key_required_raises_when_disabled(self):
        """已添加但被禁用 → 明确抛错。"""
        fake = {'tencent': {'enabled': False, 'api_key': 'v1:whatever'}}
        with patch.object(llm_platform_mod, '_load_overrides', return_value=fake), \
             patch.object(llm_platform_mod, '_resolve', wraps=llm_platform_mod._resolve):
            with self.assertRaises(ValueError):
                get_api_key('tencent', required=True)

    def test_get_api_key_not_required_returns_none_when_unconfigured(self):
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}):
            self.assertIsNone(get_api_key('tencent', required=False))
            self.assertIsNone(get_api_key('baidu', required=False))


if __name__ == '__main__':
    unittest.main()
