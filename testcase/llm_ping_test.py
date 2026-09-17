"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 大模型连通性测试脚本
 * 遍历 config.llm_model_setting 中所有配置的模型，发送 ping 请求验证连通性
"""

import time
from typing import Dict, List, Any
from config import llm_model_setting
from llms import get_model_by_setting
from utils.logger import logger


def ping_llm_model(setting_name: str, setting: Dict[str, Any], test_question: str = "ping") -> Dict[str, Any]:
    """
    测试单个 LLM 模型的连通性
    :param setting_name: 配置名称
    :param setting: 配置字典
    :param test_question: 测试问题，默认 "ping"
    :return: 测试结果字典
    """
    result = {
        'name': setting_name,
        'platform': setting.get('platform', 'unknown'),
        'model': setting.get('model', 'unknown'),
        'success': False,
        'response': None,
        'error': None,
        'latency_ms': 0
    }
    
    try:
        # 获取 LLM 实例
        llm = get_model_by_setting(_setting_name=setting_name, _setting=setting)
        
        # 发送测试请求并计时
        start_time = time.time()
        response = llm.ask(test_question)
        end_time = time.time()
        
        result['success'] = True
        result['response'] = response[:100] if response else None  # 只保留前100字符
        result['latency_ms'] = int((end_time - start_time) * 1000)
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Ping failed for {setting_name}: {e}")
    
    return result


def ping_all_models() -> List[Dict[str, Any]]:
    """
    测试所有配置的 LLM 模型连通性
    :return: 所有测试结果的列表
    """
    results = []
    
    print(f"\n{'='*60}")
    print(f"开始测试 {len(llm_model_setting)} 个 LLM 模型...")
    print(f"{'='*60}\n")
    
    for setting_name, setting in llm_model_setting.items():
        print(f"测试 {setting_name}...", end=' ', flush=True)
        
        result = ping_llm_model(setting_name, setting)
        results.append(result)
        
        # 打印结果
        if result['success']:
            print(f"✓ 成功 ({result['latency_ms']}ms)")
            if result['response']:
                print(f"  响应: {result['response'][:50]}...")
        else:
            print(f"✗ 失败")
            print(f"  错误: {result['error']}")
        print()
    
    # 打印汇总
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    
    print(f"{'='*60}")
    print(f"测试完成: {success_count} 成功, {fail_count} 失败")
    print(f"{'='*60}\n")
    
    return results


if __name__ == '__main__':
    ping_all_models()
