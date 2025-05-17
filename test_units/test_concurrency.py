# -*- coding: utf-8 -*-
"""
并发测试单元
测试多个读卡器同时请求的并发处理能力和数据一致性
"""
import unittest
import os
import sqlite3
import sys
import threading
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# 添加项目根目录到系统路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入服务器模块
import http_reader
from test_units.test_integration import MockSocket


class TestConcurrency(unittest.TestCase):
    """并发测试类"""
    
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
        
        # 添加测试卡片数据 - 10张有效卡
        for i in range(10):
            username = f"用户{i+1}"
            cardnum = f"CARD{i+1:04d}"
            department = f"部门{(i % 5) + 1}"
            self.cursor.execute(
                'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
                (username, cardnum, department, 1)
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
    
    def test_concurrent_card_processing(self):
        """测试并发刷卡处理"""
        # 并发线程数
        num_threads = 10
        # 每个线程处理的请求数
        requests_per_thread = 5
        
        # 创建请求处理函数
        def process_request(card_index):
            card_num = f"CARD{card_index+1:04d}"
            jihao = str(random.randint(1, 3))
            info = str(random.randint(10000, 99999))
            
            # 构造刷卡请求
            card_request = (
                f"GET /index.html?info={info}&jihao={jihao}&card={card_num}&dn=1234567890123456 HTTP/1.1\r\n"
                "Host: localhost:88\r\n"
                "\r\n"
            ).encode('utf-8')
            
            # 创建模拟Socket
            mock_socket = MockSocket(card_request)
            
            # 处理客户端连接
            http_reader.service_client(mock_socket)
            
            # 返回响应和卡号
            return mock_socket.sent_data.decode('gbk'), card_num
        
        # 创建并发任务
        tasks = []
        for _ in range(requests_per_thread):
            for i in range(num_threads):
                tasks.append(i)
        
        random.shuffle(tasks)  # 随机打乱，增加并发冲突可能性
        
        # 使用线程池执行并发任务
        results = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = list(executor.map(process_request, tasks))
        
        # 验证所有响应
        for response, card_num in results:
            self.assertTrue(response.startswith('Response=1,'))
            # 所有卡应该都处理成功
            self.assertIn(',10,5,', response)
        
        # 验证数据库状态
        for i in range(num_threads):
            card_num = f"CARD{i+1:04d}"
            self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', (card_num,))
            status = self.cursor.fetchone()[0]
            # 所有卡的状态应该都是0（已使用）
            self.assertEqual(status, 0)
    
    def test_concurrent_update_consistency(self):
        """测试并发更新的数据一致性"""
        # 测试卡号
        test_card = "CARD0001"
        
        # 重置卡片状态为1（有效）
        self.cursor.execute('UPDATE kbk_ic_manager SET status = ? WHERE card = ?', (1, test_card))
        self.conn.commit()
        
        # 并发线程数
        num_threads = 5
        
        # 创建状态更新函数
        def update_status():
            return http_reader.update_card_status(test_card, 0)
        
        # 使用线程池执行并发更新
        results = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = list(executor.map(lambda _: update_status(), range(num_threads)))
        
        # 验证结果：只有一个线程应该成功更新
        success_count = results.count(True)
        self.assertEqual(success_count, 1)
        
        # 验证数据库状态
        self.cursor.execute('SELECT status FROM kbk_ic_manager WHERE card = ?', (test_card,))
        status = self.cursor.fetchone()[0]
        self.assertEqual(status, 0)
    
    def test_high_concurrency_heartbeats(self):
        """测试高并发心跳包处理"""
        # 并发线程数
        num_threads = 50
        
        # 创建心跳包处理函数
        def process_heartbeat():
            info = str(random.randint(10000, 99999))
            device_id = ''.join([str(random.randint(0, 9)) for _ in range(16)])
            
            # 构造心跳包请求
            heartbeat_request = (
                f"GET /index.html?info={info}&heartbeattype=1&dn={device_id} HTTP/1.1\r\n"
                "Host: localhost:88\r\n"
                "\r\n"
            ).encode('utf-8')
            
            # 创建模拟Socket
            mock_socket = MockSocket(heartbeat_request)
            
            # 处理客户端连接
            http_reader.service_client(mock_socket)
            
            # 返回响应
            return mock_socket.sent_data.decode('gbk')
        
        # 使用线程池执行并发任务
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            responses = list(executor.map(lambda _: process_heartbeat(), range(num_threads)))
        end_time = time.time()
        
        # 验证所有响应都是成功的
        for response in responses:
            self.assertTrue(response.startswith('Response=1,'))
        
        # 验证处理时间合理（每个请求平均不超过10ms）
        total_time = end_time - start_time
        avg_time_per_request = total_time / num_threads
        self.assertLess(avg_time_per_request, 0.01)  # 每个请求平均不超过10ms
    
    def test_mixed_concurrent_requests(self):
        """测试混合并发请求处理"""
        # 并发线程数
        num_threads = 20
        
        # 创建请求处理函数
        def process_random_request():
            request_type = random.choice(['heartbeat', 'valid_card', 'invalid_card', 'nonexistent_card'])
            info = str(random.randint(10000, 99999))
            device_id = ''.join([str(random.randint(0, 9)) for _ in range(16)])
            
            if request_type == 'heartbeat':
                request = (
                    f"GET /index.html?info={info}&heartbeattype=1&dn={device_id} HTTP/1.1\r\n"
                    "Host: localhost:88\r\n"
                    "\r\n"
                ).encode('utf-8')
            elif request_type == 'valid_card':
                card_index = random.randint(0, 9)
                card_num = f"CARD{card_index+1:04d}"
                jihao = str(random.randint(1, 3))
                request = (
                    f"GET /index.html?info={info}&jihao={jihao}&card={card_num}&dn={device_id} HTTP/1.1\r\n"
                    "Host: localhost:88\r\n"
                    "\r\n"
                ).encode('utf-8')
            elif request_type == 'invalid_card':
                # 无效卡号（不存在的卡）
                card_num = f"INVALID{random.randint(1000, 9999)}"
                jihao = str(random.randint(1, 3))
                request = (
                    f"GET /index.html?info={info}&jihao={jihao}&card={card_num}&dn={device_id} HTTP/1.1\r\n"
                    "Host: localhost:88\r\n"
                    "\r\n"
                ).encode('utf-8')
            else:  # nonexistent_card - 格式错误的请求
                request = (
                    f"GET /index.html?invalid_format HTTP/1.1\r\n"
                    "Host: localhost:88\r\n"
                    "\r\n"
                ).encode('utf-8')
            
            # 创建模拟Socket
            mock_socket = MockSocket(request)
            
            # 处理客户端连接
            http_reader.service_client(mock_socket)
            
            # 返回响应和请求类型
            return mock_socket.sent_data, request_type
        
        # 使用线程池执行并发任务
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = list(executor.map(lambda _: process_random_request(), range(num_threads)))
        
        # 验证所有Socket连接都已关闭
        for mock_socket, _ in results:
            self.assertTrue(mock_socket.closed)
        
        # 检查数据库一致性
        # 查询卡片管理表中所有状态为0的卡片数量
        self.cursor.execute('SELECT COUNT(*) FROM kbk_ic_manager WHERE status = 0')
        inactive_cards = self.cursor.fetchone()[0]
        
        # 查询各计数表中的记录总数
        self.cursor.execute('SELECT COUNT(*) FROM kbk_ic_cn_count')
        cn_count = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM kbk_ic_en_count')
        en_count = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM kbk_ic_nm_count')
        nm_count = self.cursor.fetchone()[0]
        
        # 总计数应等于无效卡数量
        self.assertEqual(inactive_cards, cn_count + en_count + nm_count)


if __name__ == '__main__':
    unittest.main()
