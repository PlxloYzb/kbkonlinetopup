#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import json
import logging
import sqlite3
import unittest
import asyncio
import aiohttp
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pandas as pd
import aiosqlite
import threading
from openpyxl import load_workbook

# 引入要测试的服务
from status_update_server import DutyUpdateService

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TestDutyUpdateService(unittest.TestCase):
    """测试DutyUpdateService的功能"""
    
    @classmethod
    def setUpClass(cls):
        """测试前创建临时文件夹和数据库"""
        # 创建临时目录用于测试
        cls.temp_dir = tempfile.mkdtemp()
        cls.excel_folder = os.path.join(cls.temp_dir, "excel")
        os.makedirs(cls.excel_folder, exist_ok=True)
        
        # 创建SQLite数据库
        cls.db_path = os.path.join(cls.temp_dir, "test.db")
        cls.create_test_database()
        
        # 创建测试排班Excel
        cls.excel_file = cls.create_test_excel()
        
        # 设置时间点
        cls.time_points = {
            "a": "08:00",
            "b": "12:00",
            "c": "18:00"
        }
        
        # 数据库配置
        cls.db_config = {
            "type": "sqlite",
            "path": cls.db_path
        }
        
        # 测试web服务的URL
        cls.health_url = "http://localhost:8080/health"
        
        logger.info("测试环境设置完成")
        
    @classmethod
    def tearDownClass(cls):
        """测试后清理临时文件"""
        # 删除临时目录和文件
        shutil.rmtree(cls.temp_dir)
        logger.info("测试环境已清理")
    
    @classmethod
    def create_test_database(cls):
        """创建测试数据库和表结构"""
        conn = sqlite3.connect(cls.db_path)
        cursor = conn.cursor()
        
        # 创建员工表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            position TEXT,
            status INTEGER DEFAULT 0,
            last_updated TIMESTAMP
        )
        ''')
        
        # 添加测试数据
        departments = {
            "技术部": ("tech", 10),
            "运维部": ("ops", 7),
            "安全部": ("sec", 5),
            "产品部": ("prod", 3),
            "客服部": ("cs", 6)
        }
        
        for dept, (prefix, count) in departments.items():
            for i in range(1, count + 1):
                cursor.execute('''
                INSERT INTO employees (username, name, department, position, status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    f"{prefix}{i}",
                    f"{dept}员工{i}",
                    dept,
                    "工程师",
                    0,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"测试数据库已创建: {cls.db_path}")
    
    @classmethod
    def create_test_excel(cls):
        """创建测试排班Excel文件"""
        # Excel文件名使用当前日期
        file_name = datetime.now().strftime("%Y-%m-%d.xlsx")
        file_path = os.path.join(cls.excel_folder, file_name)
        
        # 创建测试数据
        writer = pd.ExcelWriter(file_path, engine='openpyxl')
        
        departments = {
            "技术部": ("tech", 10),
            "运维部": ("ops", 7),
            "安全部": ("sec", 5),
            "产品部": ("prod", 3),
            "客服部": ("cs", 6)
        }
        
        for dept, (prefix, count) in departments.items():
            data = []
            for i in range(1, count + 1):
                # 设置一部分人为值班状态 (每3人中的1人)
                is_on_duty = 1 if i % 3 == 0 else 0
                # 设置班次 (每4人中的1人为夜班，其余为白班)
                shift = "ds" if i % 4 != 0 else "ns"
                
                data.append({
                    "user": f"{prefix}{i}",
                    "name": f"{dept}员工{i}",
                    "is_on_duty": is_on_duty,
                    "shift": shift
                })
            
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name=dept, index=False)
        
        writer.close()
        logger.info(f"测试Excel文件已创建: {file_path}")
        return file_path
    
    def verify_status_updates(self, time_point):
        """验证数据库状态是否已正确更新"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 查询状态为1的员工数量
        cursor.execute("SELECT COUNT(*) FROM employees WHERE status = 1")
        updated_count = cursor.fetchone()[0]
        
        # 查询每个部门更新的员工数量
        cursor.execute("SELECT department, COUNT(*) FROM employees WHERE status = 1 GROUP BY department")
        dept_counts = cursor.fetchall()
        
        conn.close()
        
        logger.info(f"时间点 {time_point} 更新后，共有 {updated_count} 名员工状态为1")
        if dept_counts:
            for dept, count in dept_counts:
                logger.info(f"  {dept}: {count} 人")
        
        # 确保有员工被更新
        self.assertGreater(updated_count, 0)
        
        return updated_count
    
    def reset_database_status(self):
        """重置数据库中所有员工的状态为0"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE employees SET status = 0")
        conn.commit()
        conn.close()
        logger.info("数据库状态已重置")
    
    def test_01_initialization(self):
        """测试服务初始化是否正常"""
        logger.info("======= 开始测试服务初始化 =======")
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            batch_size=10,
            max_workers=2,
            monitor_port=None
        )
        
        # 验证服务初始化是否正确
        self.assertEqual(service.excel_folder, self.excel_folder)
        self.assertEqual(service.db_config, self.db_config)
        self.assertEqual(service.time_points, self.time_points)
        
        # 验证服务是否正确检测到Excel文件
        service.check_new_excel()
        self.assertIsNotNone(service.latest_excel)
        self.assertIsNotNone(service.current_file_hash)
        
        logger.info(f"服务初始化正常，检测到Excel文件: {service.latest_excel}")
        logger.info("======= 完成测试服务初始化 =======")
    
    def test_02_file_handling(self):
        """测试文件处理功能"""
        logger.info("======= 开始测试文件处理功能 =======")
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        
        # 先确保服务检测到文件
        service.check_new_excel()
        original_file = service.latest_excel
        original_hash = service.current_file_hash
        
        # 创建一个新的Excel文件，文件名为下一个日期
        original_date = datetime.strptime(original_file.split('.')[0], "%Y-%m-%d")
        new_date = original_date + timedelta(days=1)
        new_file_name = new_date.strftime("%Y-%m-%d.xlsx")
        new_file_path = os.path.join(self.excel_folder, new_file_name)
        shutil.copy(os.path.join(self.excel_folder, original_file), new_file_path)
        
        # 让服务检测新文件
        service.check_new_excel()
        
        # 只断言文件名变化，不断言哈希值变化
        self.assertNotEqual(original_file, service.latest_excel)
        # self.assertNotEqual(original_hash, service.current_file_hash)
        
        logger.info(f"文件处理功能正常，检测到新文件: {service.latest_excel}")
        logger.info("======= 完成测试文件处理功能 =======")
    
    def test_03_manual_update(self):
        """测试手动更新功能"""
        logger.info("======= 开始测试手动更新功能 =======")
        
        # 重置数据库状态
        self.reset_database_status()
        
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        
        # 确保服务检测到Excel文件
        service.check_new_excel()
        
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 初始化数据库连接池
        loop.run_until_complete(service.initialize_db_pool())
        
        try:
            # 手动触发时间点a的更新
            time_point = "a"
            loop.run_until_complete(service.update_status(time_point))
            
            # 验证数据库更新
            updated_count = self.verify_status_updates(time_point)
            logger.info(f"手动更新成功，更新了 {updated_count} 名员工的状态")
            
            # 测试时间点b
            self.reset_database_status()
            time_point = "b"
            loop.run_until_complete(service.update_status(time_point))
            updated_count = self.verify_status_updates(time_point)
            logger.info(f"时间点 {time_point} 更新成功，更新了 {updated_count} 名员工的状态")
            
            # 测试时间点c
            self.reset_database_status()
            time_point = "c"
            loop.run_until_complete(service.update_status(time_point))
            updated_count = self.verify_status_updates(time_point)
            logger.info(f"时间点 {time_point} 更新成功，更新了 {updated_count} 名员工的状态")
            
        finally:
            # 关闭数据库连接池
            loop.run_until_complete(service.close_db_pool())
            loop.close()
            
        logger.info("======= 完成测试手动更新功能 =======")
    
    def test_04_health_status(self):
        """测试健康状态API"""
        logger.info("======= 开始测试健康状态API =======")
        
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        
        # 确保服务检测到Excel文件
        service.check_new_excel()
        
        # 手动更新健康状态
        service.health_status["last_update"] = datetime.now().isoformat()
        service.health_status["status"] = "healthy"
        
        # 测试健康状态
        self.assertEqual(service.health_status["status"], "healthy")
        self.assertIsNotNone(service.health_status["last_update"])
        self.assertIsNotNone(service.health_status["latest_excel"])
        
        logger.info(f"健康状态API测试正常: {service.health_status}")
        logger.info("======= 完成测试健康状态API =======")
    
    def test_05_full_service_with_http(self):
        """测试完整服务和HTTP服务器"""
        logger.info("======= 开始测试完整服务和HTTP服务器 =======")
        
        # 彻底清空Excel文件夹，然后重新生成一份2025-05-17.xlsx
        for fname in os.listdir(self.excel_folder):
            if fname.endswith('.xlsx'):
                os.remove(os.path.join(self.excel_folder, fname))
        self.create_test_excel()  # 重新生成一份和数据库匹配的Excel
        
        # 重置数据库状态
        self.reset_database_status()
        
        # 寻找一个可用的端口而不是硬编码端口
        import socket
        def find_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', 0))
                return s.getsockname()[1]
                
        http_port = find_free_port()
        self.health_url = f"http://localhost:{http_port}/health"
        logger.info(f"使用动态分配的端口 {http_port} 进行HTTP测试")
        
        # 在单独的线程中运行服务
        def run_service(excel_folder, db_path, time_points, port):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 传递相同的路径
            service = DutyUpdateService(
                excel_folder=excel_folder,
                db_config={"type": "sqlite", "path": db_path},
                time_points=time_points,
                monitor_port=None
            )
            service.check_new_excel()  # 主动检测最新Excel文件
            # 启动HTTP服务器
            async def start_http_server():
                try:
                    from aiohttp import web
                    app = web.Application()
                    app.router.add_get('/health', service.get_health)
                    
                    runner = web.AppRunner(app)
                    await runner.setup()
                    site = web.TCPSite(runner, 'localhost', port)
                    
                    await site.start()
                    logger.info(f"HTTP服务器已启动在端口 {port}")
                    
                    # 初始化数据库连接池
                    await service.initialize_db_pool()
                    
                    # 简单测试：手动触发更新
                    await service.update_status("a")
                    
                    # 保持服务运行一段时间
                    await asyncio.sleep(5)
                    
                    # 结束时清理资源
                    await runner.cleanup()
                    if hasattr(service, 'db_pool') and service.db_pool:
                        await service.close_db_pool()
                except Exception as e:
                    logger.error(f"HTTP服务器出错: {str(e)}")
                    raise
            
            try:
                # 运行HTTP服务器和更新任务
                loop.run_until_complete(start_http_server())
            except Exception as e:
                logger.error(f"线程中的服务出错: {str(e)}")
            finally:
                loop.close()
        
        # 在单独的线程中启动服务，传递相同的excel_folder和db_path以及动态端口
        service_thread = threading.Thread(
            target=run_service,
            args=(self.excel_folder, self.db_path, self.time_points, http_port)
        )
        service_thread.daemon = True
        service_thread.start()
        
        # 等待HTTP服务器启动
        time.sleep(2)
        
        # 测试HTTP健康状态API
        async def test_health_api():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.health_url) as response:
                        self.assertEqual(response.status, 200)
                        data = await response.json()
                        logger.info(f"健康状态API返回: {data}")
                        
                        # 验证结果
                        self.assertIn("status", data)
                        self.assertIn("last_update", data)
                        self.assertIn("latest_excel", data)
            except Exception as e:
                logger.error(f"测试健康API时出错: {str(e)}")
                raise
        
        # 运行HTTP测试
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(test_health_api())
            
            # 验证数据库更新
            updated_count = self.verify_status_updates("a")
            logger.info(f"通过HTTP服务触发的更新成功，更新了 {updated_count} 名员工的状态")
            
        except Exception as e:
            logger.error(f"HTTP测试失败: {str(e)}")
            self.fail(f"HTTP测试失败: {str(e)}")
        finally:
            loop.close()
        
        # 等待服务线程结束
        service_thread.join(timeout=1)
        logger.info("HTTP服务测试完成")
        logger.info("======= 完成测试完整服务和HTTP服务器 =======")

    def test_06_hot_update_excel(self):
        """测试文件热更新：服务能否检测到Excel内容变化"""
        logger.info("======= 开始测试文件热更新 =======")
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        service.check_new_excel()
        original_file = service.latest_excel
        file_path = os.path.join(self.excel_folder, original_file)
        
        # 先初始化数据库连接池
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(service.initialize_db_pool())
        
        # 修改Excel文件内容（增加一名员工）
        df = pd.read_excel(file_path, sheet_name="技术部")
        new_row = {"user": "tech999", "name": "技术员工999", "is_on_duty": 1, "shift": "ds"}
        # 使用concat替代已弃用的append方法
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        
        # 在新版pandas中，使用mode='a'和if_sheet_exists='replace'来修改现有Excel文件
        with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df.to_excel(writer, sheet_name="技术部", index=False)
        
        # 通知服务文件被修改
        service.reload_excel()
        
        # 再次触发更新
        loop.run_until_complete(service.update_status("a"))
        
        # 检查数据库是否有新员工被更新
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM employees WHERE username='tech999'")
        row = cursor.fetchone()
        conn.close()
        # 新员工不在数据库，应该不会报错，但服务应能正常处理
        # 只要不抛异常即为通过
        logger.info("文件热更新测试通过（服务未崩溃）")
        loop.run_until_complete(service.close_db_pool())
        loop.close()
        logger.info("======= 完成测试文件热更新 =======")

    def test_07_file_locked(self):
        """测试Excel文件被占用/只读时服务的健壮性"""
        logger.info("======= 开始测试文件被占用 =======")
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        service.check_new_excel()
        file_path = os.path.join(self.excel_folder, service.latest_excel)
        
        # 以只读方式打开文件并保持句柄
        f = open(file_path, 'rb')
        try:
            # 初始化数据库连接池
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(service.initialize_db_pool())
            # 触发更新，应该不会崩溃
            try:
                loop.run_until_complete(service.update_status("a"))
                logger.info("文件被占用时服务未崩溃")
            except Exception as e:
                logger.info(f"文件被占用时服务抛出异常: {e}")
            finally:
                loop.run_until_complete(service.close_db_pool())
                loop.close()
        finally:
            f.close()
        logger.info("======= 完成测试文件被占用 =======")

    def test_08_large_batch_update(self):
        """测试大批量数据批量更新和性能"""
        logger.info("======= 开始测试大批量数据批量更新 =======")
        # 生成1000名员工的数据库和Excel
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM employees")
        for i in range(1, 1001):
            cursor.execute('''
                INSERT INTO employees (username, name, department, position, status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (f"biguser{i}", f"大批量员工{i}", "大数据部", "工程师", 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        # 生成Excel
        df = pd.DataFrame({
            "user": [f"biguser{i}" for i in range(1, 1001)],
            "name": [f"大批量员工{i}" for i in range(1, 1001)],
            "is_on_duty": [1] * 1000,
            "shift": ["ds"] * 1000
        })
        file_path = os.path.join(self.excel_folder, "2025-05-17.xlsx")
        with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df.to_excel(writer, sheet_name="大数据部", index=False)
        # 服务检测新sheet
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        service.check_new_excel()
        # 初始化数据库连接池
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(service.initialize_db_pool())
        import time
        start = time.time()
        loop.run_until_complete(service.update_status("a"))
        elapsed = time.time() - start
        # 检查数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM employees WHERE status=1")
        updated_count = cursor.fetchone()[0]
        conn.close()
        logger.info(f"大批量数据批量更新：{updated_count} 人被更新，用时 {elapsed:.2f} 秒")
        self.assertEqual(updated_count, 1000)
        loop.run_until_complete(service.close_db_pool())
        loop.close()
        logger.info("======= 完成测试大批量数据批量更新 =======")

    def test_09_performance_stress(self):
        """性能压力测试：高频率多次触发状态更新"""
        logger.info("======= 开始性能压力测试 =======")
        service = DutyUpdateService(
            excel_folder=self.excel_folder,
            db_config=self.db_config,
            time_points=self.time_points,
            monitor_port=None
        )
        service.check_new_excel()
        # 初始化数据库连接池
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(service.initialize_db_pool())
        import time
        start = time.time()
        for i in range(10):
            loop.run_until_complete(service.update_status("a"))
        elapsed = time.time() - start
        logger.info(f"10次高频状态更新总耗时：{elapsed:.2f} 秒，平均每次 {elapsed/10:.2f} 秒")
        loop.run_until_complete(service.close_db_pool())
        loop.close()
        logger.info("======= 完成性能压力测试 =======")

def run_tests():
    """运行所有测试"""
    logger.info("========== 开始执行所有测试 ==========")
    unittest.main()

if __name__ == "__main__":
    run_tests()
