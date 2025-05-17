# -*- coding: utf-8 -*-
"""
完整流程测试单元
测试心跳包处理流程、有效卡刷卡流程、无效卡刷卡流程和不存在卡刷卡流程
"""
import unittest
import os
import sqlite3
import sys
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目根目录到系统路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入服务器模块
import http_reader


class MockSocket:
    """模拟Socket类"""
    
    def __init__(self, request_data):
        self.request_data = request_data
        self.sent_data = b''
        self.closed = False
    
    def recv(self, buffer_size):
        return self.request_data
    
    def send(self, data):
        self.sent_data = data
        return len(data)
    
    def close(self):
        self.closed = True


class TestIntegration(unittest.TestCase):
    """完整流程测试类"""
    
    def setUp(self):
        """测试前准备工作"""
        # 使用测试数据库文件
        self.db_file = "test_ic_manager.db"
        
        # 如果测试数据库已存在，则删除
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
            
        # 初始化测试数据库
        self.conn = sqlite3.connect(self.db_file)
        self.cursor = self.conn.cursor()
        
        # 创建表结构
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS kbk_ic_manager (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            card TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_card ON kbk_ic_manager(card)')
        
        for table in ['kbk_ic_en_count', 'kbk_ic_cn_count', 'kbk_ic_nm_count']:
            self.cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                department TEXT NOT NULL,
                transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            ''')
        
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS kbk_ic_failure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            department TEXT,
            transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            failure_type INTEGER NOT NULL
        )
        ''')
        
        # 添加测试卡片数据
        self.cursor.execute(
            'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
            ('张三', 'A1B2C3D4', '技术部', 1)  # 有效卡
        )
        
        self.cursor.execute(
            'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
            ('李四', 'E5F6G7H8', '市场部', 0)  # 无效卡
        )
        
        self.conn.commit()
        
        # 修改http_reader模块中的数据库文件名
        self.original_db_name = sqlite3.connect
        
        def mock_connect(database, *args, **kwargs):
            if database == 'ic_manager.db':
                return sqlite3.connect(self.db_file, *args, **kwargs)
            return self.original_db_name(database, *args, **kwargs)
        
        # 替换sqlite3.connect函数
        sqlite3.connect = mock_connect
        
    def tearDown(self):
        """测试后清理工作"""
        self.conn.close()
        
        # 删除测试数据库文件
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
            
        # 恢复sqlite3.connect函数
        sqlite3.connect = self.original_db_name
    
    def test_heartbeat_process(self):
        """测试心跳包处理流程"""
        # 构造心跳包请求
        heartbeat_request = (
            "GET /index.html?info=12345&heartbeattype=1&dn=1234567890123456 HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(heartbeat_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,12345'))
        self.assertTrue(mock_socket.closed)
    
    def test_valid_card_process(self):
        """测试有效卡刷卡流程"""
        # 构造有效卡请求
        valid_card_request = (
            "GET /index.html?info=12345&jihao=1&card=A1B2C3D4&dn=1234567890123456 HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(valid_card_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,12345'))
        self.assertIn(',10,5,', response)  # 成功蜂鸣代码
        self.assertTrue(mock_socket.closed)
        
        # 验证数据库更新
        self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', ('A1B2C3D4',))
        status = self.cursor.fetchone()[0]
        self.assertEqual(status, 0)  # 状态应该更新为0
        
        # 验证计数表插入
        self.cursor.execute('SELECT * FROM kbk_ic_cn_count WHERE user = ?', ('张三',))
        record = self.cursor.fetchone()
        self.assertIsNotNone(record)
    
    def test_invalid_card_process(self):
        """测试无效卡刷卡流程"""
        # 构造无效卡请求
        invalid_card_request = (
            "GET /index.html?info=12345&jihao=1&card=E5F6G7H8&dn=1234567890123456 HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(invalid_card_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,12345'))
        self.assertIn(',10,7,', response)  # 失败蜂鸣代码
        self.assertTrue(mock_socket.closed)
        
        # 验证失败记录表插入
        self.cursor.execute('SELECT * FROM kbk_ic_failure_records WHERE user = ? AND failure_type = ?', ('李四', 1))
        record = self.cursor.fetchone()
        self.assertIsNotNone(record)
    
    def test_nonexistent_card_process(self):
        """测试不存在卡刷卡流程"""
        # 构造不存在卡请求
        nonexistent_card_request = (
            "GET /index.html?info=12345&jihao=1&card=Z9Y8X7W6&dn=1234567890123456 HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "\r\n"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(nonexistent_card_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,12345'))
        self.assertIn(',10,7,', response)  # 失败蜂鸣代码
        self.assertTrue(mock_socket.closed)
        
        # 验证失败记录表插入
        self.cursor.execute('SELECT * FROM kbk_ic_failure_records WHERE failure_type = ?', (2,))
        record = self.cursor.fetchone()
        self.assertIsNotNone(record)
    
    def test_post_card_process(self):
        """测试POST方式刷卡流程"""
        # 构造POST方式的有效卡请求
        post_card_request = (
            "POST /process HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "Content-Length: 56\r\n"
            "\r\n"
            "info=67890&jihao=2&card=A1B2C3D4&dn=1234567890123456"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(post_card_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,67890'))
        self.assertIn(',10,5,', response)  # 成功蜂鸣代码
        self.assertTrue(mock_socket.closed)
        
        # 验证数据库更新
        self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', ('A1B2C3D4',))
        status = self.cursor.fetchone()[0]
        self.assertEqual(status, 0)  # 状态应该更新为0
        
        # 验证计数表插入
        self.cursor.execute('SELECT * FROM kbk_ic_en_count WHERE user = ?', ('张三',))
        record = self.cursor.fetchone()
        self.assertIsNotNone(record)
    
    def test_json_card_process(self):
        """测试JSON格式刷卡流程"""
        # 构造JSON格式的有效卡请求
        json_card_request = (
            "POST /process HTTP/1.1\r\n"
            "Host: localhost:88\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 83\r\n"
            "\r\n"
            "{\"info\":\"24680\",\"jihao\":\"3\",\"card\":\"A1B2C3D4\",\"dn\":\"1234567890123456\"}"
        ).encode('utf-8')
        
        # 创建模拟Socket
        mock_socket = MockSocket(json_card_request)
        
        # 处理客户端连接
        http_reader.service_client(mock_socket)
        
        # 验证响应
        response = mock_socket.sent_data.decode('gbk')
        self.assertTrue(response.startswith('Response=1,24680'))
        self.assertIn(',10,5,', response)  # 成功蜂鸣代码
        self.assertTrue(mock_socket.closed)
        
        # 验证数据库更新
        self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', ('A1B2C3D4',))
        status = self.cursor.fetchone()[0]
        self.assertEqual(status, 0)  # 状态应该更新为0
        
        # 验证计数表插入
        self.cursor.execute('SELECT * FROM kbk_ic_nm_count WHERE user = ?', ('张三',))
        record = self.cursor.fetchone()
        self.assertIsNotNone(record)


if __name__ == '__main__':
    unittest.main()
