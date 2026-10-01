"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

腾讯云 / 百度云大模型平台接入测试（不碰网络 / DB / Redis）。

验证两项新平台被正确接入：
  - PLATFORM_META 与 _PLATFORM_REGISTRY 含 tencent / baidu；
  - 设置页视图 list_platforms_view 输出两者（前端据此渲染启用开关）；
  - 未配置凭据时 get_api_key(required=True) 明确抛错（不静默回退）。
"""

import sys, os, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llms import llm_platform as llm_platform_mod
from llms.llm_platform import PLATFORM_META, list_platforms_view, get_api_key
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

    def test_view_lists_tencent_and_baidu(self):
        platforms = {v['platform']: v for v in list_platforms_view()}
        self.assertIn('tencent', platforms)
        self.assertIn('baidu', platforms)
        self.assertEqual(platforms['tencent']['label'], '腾讯云混元')
        self.assertEqual(platforms['baidu']['label'], '百度云千帆')
        # 设置页据此给前端展示默认端点（用户未自定义时的兜底）
        self.assertEqual(
            platforms['tencent']['default_base_url'],
            'https://api.hunyuan.cloud.tencent.com/v1',
        )
        self.assertEqual(
            platforms['baidu']['default_base_url'],
            'https://qianfan.baidubce.com/v2',
        )

    def test_get_api_key_required_raises_when_unconfigured(self):
        # 无 overrides、无 env key → 应明确抛错（不静默回退到别的平台）
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}), \
             patch.object(llm_platform_mod, '_env_default_api_key', return_value=None):
            with self.assertRaises(ValueError):
                get_api_key('tencent', required=True)
            with self.assertRaises(ValueError):
                get_api_key('baidu', required=True)

    def test_get_api_key_not_required_returns_none_when_unconfigured(self):
        with patch.object(llm_platform_mod, '_load_overrides', return_value={}), \
             patch.object(llm_platform_mod, '_env_default_api_key', return_value=None):
            self.assertIsNone(get_api_key('tencent', required=False))
            self.assertIsNone(get_api_key('baidu', required=False))


if __name__ == '__main__':
    unittest.main()
