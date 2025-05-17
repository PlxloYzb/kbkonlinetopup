# -*- coding: utf-8 -*-
"""
通信协议测试单元
测试中文编码转换函数、GET/POST请求解析功能和JSON格式解析功能
"""
import unittest
import sys
from pathlib import Path

# 添加项目根目录到系统路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入服务器模块
import http_reader


class TestProtocol(unittest.TestCase):
    """通信协议测试类"""
    
    def test_chinese_code_conversion(self):
        """测试中文编码转换函数"""
        # 测试纯英文字符串
        english_str = "Hello World!"
        english_code = http_reader.GetChineseCode(english_str)
        self.assertEqual(english_code, english_str)
        
        # 测试中文字符串
        chinese_str = "你好，世界！"
        chinese_code = http_reader.GetChineseCode(chinese_str)
        # 由于中文编码结果依赖于具体的GBK编码值，这里只验证长度和格式
        self.assertGreater(len(chinese_code), len(chinese_str))
        self.assertIn("\\x", chinese_code)
        
        # 测试混合字符串
        mixed_str = "Hello 世界!"
        mixed_code = http_reader.GetChineseCode(mixed_str)
        self.assertGreater(len(mixed_code), len(mixed_str))
        self.assertIn("\\x", mixed_code)
        self.assertIn("Hello", mixed_code)
        
        # 测试特殊字符
        special_str = "你好！@#￥%……&*（）"
        special_code = http_reader.GetChineseCode(special_str)
        self.assertGreater(len(special_code), len(special_str))
        self.assertIn("\\x", special_code)
        
        # 测试空字符串
        empty_str = ""
        empty_code = http_reader.GetChineseCode(empty_str)
        self.assertEqual(empty_code, empty_str)
    
    def test_get_request_parsing(self):
        """测试GET请求解析功能"""
        # 构造GET请求
        get_request = (
            "GET /index.html?info=12345&jihao=1&card=A1B2C3D4&dn=1234567890123456 HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "Connection: keep-alive\r\n"
            "User-Agent: Mozilla/5.0\r\n"
            "\r\n"
        )
        
        # 解析请求
        params = http_reader.parse_request(get_request)
        
        # 验证解析结果
        self.assertIn('info', params)
        self.assertEqual(params['info'], '12345')
        self.assertIn('jihao', params)
        self.assertEqual(params['jihao'], '1')
        self.assertIn('card', params)
        self.assertEqual(params['card'], 'A1B2C3D4')
        self.assertIn('dn', params)
        self.assertEqual(params['dn'], '1234567890123456')
        
        # 测试不带参数的GET请求
        get_request_no_params = (
            "GET /index.html HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        )
        
        params = http_reader.parse_request(get_request_no_params)
        self.assertEqual(params, {})
        
        # 测试格式错误的GET请求
        get_request_invalid = (
            "GET /index.html?invalid_format HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        )
        
        params = http_reader.parse_request(get_request_invalid)
        self.assertEqual(params, {})
    
    def test_post_request_parsing(self):
        """测试POST请求解析功能"""
        # 构造POST请求 (表单格式)
        post_request = (
            "POST /process HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "Content-Length: 56\r\n"
            "\r\n"
            "info=67890&jihao=2&card=E5F6G7H8&dn=6543210987654321"
        )
        
        # 解析请求
        params = http_reader.parse_request(post_request)
        
        # 验证解析结果
        self.assertIn('info', params)
        self.assertEqual(params['info'], '67890')
        self.assertIn('jihao', params)
        self.assertEqual(params['jihao'], '2')
        self.assertIn('card', params)
        self.assertEqual(params['card'], 'E5F6G7H8')
        self.assertIn('dn', params)
        self.assertEqual(params['dn'], '6543210987654321')
    
    def test_json_request_parsing(self):
        """测试JSON格式解析功能"""
        # 构造JSON格式的POST请求
        json_request = (
            "POST /process HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 83\r\n"
            "\r\n"
            "{\"info\":\"24680\",\"jihao\":\"3\",\"card\":\"I9J0K1L2\",\"dn\":\"9876543210123456\"}"
        )
        
        # 解析请求
        params = http_reader.parse_request(json_request)
        
        # 验证解析结果
        self.assertIn('info', params)
        self.assertEqual(params['info'], '24680')
        self.assertIn('jihao', params)
        self.assertEqual(params['jihao'], '3')
        self.assertIn('card', params)
        self.assertEqual(params['card'], 'I9J0K1L2')
        self.assertIn('dn', params)
        self.assertEqual(params['dn'], '9876543210123456')
    
    def test_error_response_creation(self):
        """测试错误响应创建函数"""
        # 测试基本错误响应
        info = "12345"
        error_msg = "卡片未激活"
        beep_code = 7
        
        response = http_reader.create_error_response(info, error_msg, beep_code)
        
        # 验证响应格式
        expected_start = f"Response=1,{info},"
        self.assertTrue(response.startswith(expected_start))
        self.assertIn(f",10,{beep_code},,0,0", response)
        
        # 验证包含编码后的错误信息
        encoded_msg = http_reader.GetChineseCode("{错误}" + error_msg)
        self.assertIn(encoded_msg, response)
        
        # 测试默认蜂鸣代码
        response = http_reader.create_error_response(info, error_msg)
        self.assertIn(",10,7,,0,0", response)


if __name__ == '__main__':
    unittest.main()
