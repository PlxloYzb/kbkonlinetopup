# -*- coding: utf-8 -*-
"""
IC卡刷卡管理系统测试运行脚本
运行所有测试单元
"""
import unittest
import sys
import os
from pathlib import Path

# 添加项目根目录到系统路径
sys.path.append(str(Path(__file__).parent))

# 导入测试模块
from test_units.test_database import TestDatabase
from test_units.test_protocol import TestProtocol
from test_units.test_integration import TestIntegration
from test_units.test_concurrency import TestConcurrency


def run_all_tests():
    """运行所有测试"""
    # 创建测试套件
    test_suite = unittest.TestSuite()
    
    # 添加测试类
    test_suite.addTest(unittest.makeSuite(TestDatabase))
    test_suite.addTest(unittest.makeSuite(TestProtocol))
    test_suite.addTest(unittest.makeSuite(TestIntegration))
    test_suite.addTest(unittest.makeSuite(TestConcurrency))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # 返回测试结果
    return result.wasSuccessful()


def run_specific_test(test_name):
    """运行指定的测试"""
    if test_name == 'database':
        test_suite = unittest.makeSuite(TestDatabase)
    elif test_name == 'protocol':
        test_suite = unittest.makeSuite(TestProtocol)
    elif test_name == 'integration':
        test_suite = unittest.makeSuite(TestIntegration)
    elif test_name == 'concurrency':
        test_suite = unittest.makeSuite(TestConcurrency)
    else:
        print(f"未知的测试名称: {test_name}")
        print("可用的测试: database, protocol, integration, concurrency")
        return False
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # 返回测试结果
    return result.wasSuccessful()


if __name__ == '__main__':
    # 解析命令行参数
    if len(sys.argv) > 1:
        # 运行指定的测试
        test_name = sys.argv[1].lower()
        success = run_specific_test(test_name)
    else:
        # 运行所有测试
        success = run_all_tests()
    
    # 设置退出码
    sys.exit(0 if success else 1)
