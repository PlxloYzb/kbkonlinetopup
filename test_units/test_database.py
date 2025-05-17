# -*- coding: utf-8 -*-
"""
数据库操作测试单元
测试卡片添加、更新和查询功能以及各类计数表的插入功能
"""
import unittest
import os
import sqlite3
import sys
import time
import datetime
from pathlib import Path

# 添加项目根目录到系统路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入服务器模块
import http_reader


class TestDatabase(unittest.TestCase):
    """数据库操作测试类"""
    
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
        
        self.conn.commit()
        
    def tearDown(self):
        """测试后清理工作"""
        self.conn.close()
        
        # 删除测试数据库文件
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
    
    def test_card_operations(self):
        """测试卡片添加、更新和查询功能"""
        # 添加测试卡片
        self.cursor.execute(
            'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
            ('张三', 'A1B2C3D4', '技术部', 1)
        )
        self.conn.commit()
        
        # 查询卡片
        self.cursor.execute('SELECT * FROM kbk_ic_manager WHERE card = ?', ('A1B2C3D4',))
        card = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(card)
        self.assertEqual(card[1], '张三')
        self.assertEqual(card[2], 'A1B2C3D4')
        self.assertEqual(card[3], '技术部')
        self.assertEqual(card[4], 1)
        
        # 更新卡片状态
        self.cursor.execute(
            'UPDATE kbk_ic_manager SET status = ? WHERE card = ?',
            (0, 'A1B2C3D4')
        )
        self.conn.commit()
        
        # 再次查询卡片
        self.cursor.execute('SELECT * FROM kbk_ic_manager WHERE card = ?', ('A1B2C3D4',))
        card = self.cursor.fetchone()
        
        # 验证更新结果
        self.assertEqual(card[4], 0)
    
    def test_count_tables(self):
        """测试各类计数表的插入功能"""
        # 添加测试卡片
        self.cursor.execute(
            'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
            ('李四', 'E5F6G7H8', '市场部', 1)
        )
        self.conn.commit()
        
        # 测试中文计数表
        self.cursor.execute(
            'INSERT INTO kbk_ic_cn_count (user, department) VALUES (?, ?)',
            ('李四', '市场部')
        )
        self.conn.commit()
        
        # 查询中文计数表
        self.cursor.execute('SELECT * FROM kbk_ic_cn_count')
        record = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(record)
        self.assertEqual(record[1], '李四')
        self.assertEqual(record[2], '市场部')
        
        # 测试英文计数表
        self.cursor.execute(
            'INSERT INTO kbk_ic_en_count (user, department) VALUES (?, ?)',
            ('李四', '市场部')
        )
        self.conn.commit()
        
        # 查询英文计数表
        self.cursor.execute('SELECT * FROM kbk_ic_en_count')
        record = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(record)
        self.assertEqual(record[1], '李四')
        self.assertEqual(record[2], '市场部')
        
        # 测试其他语言计数表
        self.cursor.execute(
            'INSERT INTO kbk_ic_nm_count (user, department) VALUES (?, ?)',
            ('李四', '市场部')
        )
        self.conn.commit()
        
        # 查询其他语言计数表
        self.cursor.execute('SELECT * FROM kbk_ic_nm_count')
        record = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(record)
        self.assertEqual(record[1], '李四')
        self.assertEqual(record[2], '市场部')
    
    def test_failure_records(self):
        """测试失败记录表的插入功能"""
        # 测试卡号不存在的失败记录
        self.cursor.execute(
            'INSERT INTO kbk_ic_failure_records (failure_type) VALUES (?)',
            (2,)
        )
        self.conn.commit()
        
        # 查询失败记录
        self.cursor.execute('SELECT * FROM kbk_ic_failure_records WHERE failure_type = 2')
        record = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(record)
        self.assertEqual(record[4], 2)
        
        # 测试卡片未激活的失败记录
        self.cursor.execute(
            'INSERT INTO kbk_ic_failure_records (user, department, failure_type) VALUES (?, ?, ?)',
            ('王五', '人事部', 1)
        )
        self.conn.commit()
        
        # 查询失败记录
        self.cursor.execute('SELECT * FROM kbk_ic_failure_records WHERE failure_type = 1')
        record = self.cursor.fetchone()
        
        # 验证查询结果
        self.assertIsNotNone(record)
        self.assertEqual(record[1], '王五')
        self.assertEqual(record[2], '人事部')
        self.assertEqual(record[4], 1)
    
    def test_process_card_function(self):
        """测试process_card函数的数据库操作"""
        # 修改http_reader模块中的数据库文件名
        original_db_name = sqlite3.connect
        
        def mock_connect(database, *args, **kwargs):
            if database == 'ic_manager.db':
                return sqlite3.connect(self.db_file, *args, **kwargs)
            return original_db_name(database, *args, **kwargs)
        
        # 替换sqlite3.connect函数
        sqlite3.connect = mock_connect
        
        try:
            # 添加测试卡片
            self.cursor.execute(
                'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
                ('赵六', 'I9J0K1L2', '财务部', 1)
            )
            self.conn.commit()
            
            # 测试刷卡处理
            response = http_reader.process_card('I9J0K1L2', '1', '12345')
            
            # 验证卡片状态已更新
            self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', ('I9J0K1L2',))
            status = self.cursor.fetchone()[0]
            self.assertEqual(status, 0)
            
            # 验证中文计数表已插入记录
            self.cursor.execute('SELECT * FROM kbk_ic_cn_count WHERE user = ?', ('赵六',))
            record = self.cursor.fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record[1], '赵六')
            self.assertEqual(record[2], '财务部')
            
            # 验证响应格式正确
            self.assertTrue(response.startswith('Response=1,12345'))
            self.assertTrue(',10,5,' in response)
        
        finally:
            # 恢复sqlite3.connect函数
            sqlite3.connect = original_db_name


if __name__ == '__main__':
    unittest.main()
