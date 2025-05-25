# -*- coding: utf-8 -*-
"""
余额管理系统
使用数据库表kbk_ic_balance代替频繁Excel读写，实现用户余额管理
"""
import os
import sys
import time
import threading
import sqlite3
import logging
import pandas as pd
import schedule
import watchdog.observers
import watchdog.events
from datetime import datetime
from logging.handlers import RotatingFileHandler
import traceback
import hashlib
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor
import argparse

# 配置日志
def setup_logging():
    """设置日志系统"""
    logger = logging.getLogger('balance_manager')
    logger.setLevel(logging.INFO)
    
    # 创建按大小轮转的日志文件处理器
    handler = RotatingFileHandler(
        'balance_manager.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    
    # 设置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # 添加处理器到logger
    logger.addHandler(handler)
    
    # 添加控制台日志处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

# 初始化日志
logger = setup_logging()

# 配置常量
DB_PATH = './ic_manager.db'
EXCEL_DIR = './excel_balance'
BATCH_SIZE = 100
MAX_WORKERS = 4

# 指定的时间点
TIME_POINTS = {
    "a": "05:25",
    "b": "11:25", 
    "c": "16:55"
}

class ExcelFileHandler(watchdog.events.FileSystemEventHandler):
    """监控Excel文件变化的处理器"""
    
    def __init__(self, balance_manager):
        self.balance_manager = balance_manager
        super().__init__()
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到新文件: {event.src_path}")
            self.balance_manager.check_new_excel()
            
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到文件修改: {event.src_path}")
            if self.balance_manager.latest_excel and event.src_path.endswith(self.balance_manager.latest_excel):
                logger.info(f"当前使用的文件已修改，重新加载文件: {self.balance_manager.latest_excel}")
                self.balance_manager.reload_excel()

class BalanceManager:
    """余额管理系统核心类"""
    
    def __init__(self, excel_folder=EXCEL_DIR, batch_size=BATCH_SIZE, max_workers=MAX_WORKERS):
        """初始化余额管理系统"""
        self.excel_folder = excel_folder
        self.latest_excel = None
        self.current_file_hash = None
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # 健康状态
        self.health_status = {
            "status": "healthy",
            "last_import": None,
            "last_update": None,
            "latest_excel": None,
            "errors": []
        }
        
        # 确保Excel目录存在
        os.makedirs(self.excel_folder, exist_ok=True)
        
        # 确保数据库结构正确
        self.ensure_db_structure()
    
    def get_local_timestamp(self):
        """获取本地时区的时间戳字符串（UTC+10）"""
        # 使用UTC+10的时间
        utc_plus_10 = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return utc_plus_10
    
    def ensure_db_structure(self):
        """确保数据库结构正确，创建kbk_ic_balance表和索引"""
        try:
            logger.info("检查并初始化数据库结构")
            conn = sqlite3.connect(DB_PATH)
            # 设置数据库连接以使用本地时区
            conn.execute("PRAGMA timezone='localtime'")
            cursor = conn.cursor()
            
            # 检查kbk_ic_balance表是否存在，不存在则创建
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kbk_ic_balance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT NOT NULL,
                    department TEXT NOT NULL,
                    balance INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_user ON kbk_ic_balance(user)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_department ON kbk_ic_balance(department)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_user_dept ON kbk_ic_balance(user, department)")
            
            conn.commit()
            conn.close()
            logger.info("数据库结构检查/初始化完成")
            
        except Exception as e:
            logger.error(f"初始化数据库结构失败: {e}")
            logger.error(traceback.format_exc())
    
    def start_file_monitoring(self):
        """启动文件监控"""
        self.event_handler = ExcelFileHandler(self)
        self.observer = watchdog.observers.Observer()
        self.observer.schedule(self.event_handler, self.excel_folder, recursive=False)
        self.observer.start()
        logger.info(f"文件监控已启动，监控文件夹: {self.excel_folder}")
        
        # 首次启动时检查已有Excel文件
        self.check_new_excel()
    
    def get_file_hash(self, file_path):
        """获取文件的MD5哈希值，用于缓存标识"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()
    
    def _is_date_format(self, date_str):
        """检查字符串是否为日期格式 YYYY-MM-DD"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return False
    
    def check_new_excel(self):
        """检查是否有新的Excel文件"""
        try:
            excel_files = [f for f in os.listdir(self.excel_folder) 
                          if f.endswith('.xlsx') and self._is_date_format(f.split('.')[0])]
            
            if not excel_files:
                logger.info("未找到Excel文件")
                return
            
            # 按日期排序文件
            excel_files.sort(key=lambda x: datetime.strptime(x.split('.')[0], '%Y-%m-%d'), reverse=True)
            newest_file = excel_files[0]
            newest_file_path = os.path.join(self.excel_folder, newest_file)
            
            # 计算文件哈希值
            new_hash = self.get_file_hash(newest_file_path)
            
            # 如果是新文件或文件内容有变化
            if self.latest_excel != newest_file or self.current_file_hash != new_hash:
                logger.info(f"发现新的或已修改的余额文件: {newest_file}")
                self.latest_excel = newest_file
                self.current_file_hash = new_hash
                self.health_status["latest_excel"] = newest_file
                
                # Excel文件已更新，立即触发一次导入
                logger.info("Excel文件已更新，立即导入到数据库")
                self.import_excel_to_db(newest_file_path)
                
        except Exception as e:
            logger.error(f"检查新Excel文件时出错: {str(e)}")
            logger.error(traceback.format_exc())
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "file_check",
                "message": str(e)
            })
            self.health_status["status"] = "warning"
    
    def reload_excel(self):
        """重新加载当前Excel文件"""
        if not self.latest_excel:
            return
            
        try:
            file_path = os.path.join(self.excel_folder, self.latest_excel)
            
            # 计算新的哈希值
            new_hash = self.get_file_hash(file_path)
            
            # 如果文件内容有变化，更新
            if self.current_file_hash != new_hash:
                logger.info(f"文件内容已变更，重新导入: {self.latest_excel}")
                self.current_file_hash = new_hash
                
                # 执行导入
                self.import_excel_to_db(file_path)
                
        except Exception as e:
            logger.error(f"重新加载Excel文件时出错: {str(e)}")
            logger.error(traceback.format_exc())
    
    def import_excel_to_db(self, file_path):
        """导入Excel文件到数据库"""
        try:
            logger.info(f"开始导入Excel文件: {file_path}")
            start_time = time.time()
            
            # 读取Excel文件
            df = pd.read_excel(file_path)
            
            # 验证必需列是否存在
            required_columns = ['user', 'department', 'balance']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                error_msg = f"Excel文件缺少必需列: {', '.join(missing_columns)}"
                logger.error(error_msg)
                self.health_status["errors"].append({
                    "time": datetime.now().isoformat(),
                    "type": "import_validation",
                    "message": error_msg
                })
                return
            
            # 清理数据
            df = df.dropna(subset=['user', 'department'])  # 删除关键字段为空的行
            df['balance'] = df['balance'].fillna(0).astype(int)  # 余额为空用0填充并转为整型
            
            # 按批次处理数据
            records = df.to_dict('records')
            batches = [records[i:i+self.batch_size] for i in range(0, len(records), self.batch_size)]
            
            total_updated = 0
            total_inserted = 0
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            try:
                # 使用事务处理，确保原子性
                conn.execute('BEGIN TRANSACTION')
                
                # 处理每个批次
                for batch in batches:
                    for record in batch:
                        user = record['user']
                        department = record['department']
                        balance = record['balance']
                        
                        # 检查记录是否已存在
                        cursor.execute(
                            'SELECT id FROM kbk_ic_balance WHERE user = ? AND department = ?', 
                            (user, department)
                        )
                        result = cursor.fetchone()
                        
                        if result:
                            # 更新已存在的记录
                            local_time = self.get_local_timestamp()
                            cursor.execute(
                                '''UPDATE kbk_ic_balance 
                                   SET balance = ?, updated_at = ? 
                                   WHERE user = ? AND department = ?''', 
                                (balance, local_time, user, department)
                            )
                            total_updated += 1
                        else:
                            # 插入新记录
                            local_time = self.get_local_timestamp()
                            cursor.execute(
                                '''INSERT INTO kbk_ic_balance 
                                   (user, department, balance, created_at, updated_at) 
                                   VALUES (?, ?, ?, ?, ?)''', 
                                (user, department, balance, local_time, local_time)
                            )
                            total_inserted += 1
                
                # 提交事务
                conn.commit()
                
                process_time = time.time() - start_time
                logger.info(f"Excel导入完成，新增: {total_inserted}条，更新: {total_updated}条，耗时: {process_time:.2f}秒")
                
                # 更新健康状态
                self.health_status["last_import"] = datetime.now().isoformat()
                self.health_status["status"] = "healthy"
                
                # 移除自动触发余额检查，仅在预定时间点执行
                
            except Exception as e:
                conn.rollback()
                logger.error(f"导入过程中发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                self.health_status["errors"].append({
                    "time": datetime.now().isoformat(),
                    "type": "import_process",
                    "message": str(e)
                })
                self.health_status["status"] = "error"
                raise
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"导入Excel文件时出错: {str(e)}")
            logger.error(traceback.format_exc())
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "import_file",
                "message": str(e)
            })
            self.health_status["status"] = "error"
    
    def get_time_point_by_now(self):
        """根据当前时间判断应使用哪个时间点标识（a、b、c）"""
        now = datetime.now().time()
        a_time = datetime.strptime(TIME_POINTS["a"], "%H:%M").time()
        b_time = datetime.strptime(TIME_POINTS["b"], "%H:%M").time()
        c_time = datetime.strptime(TIME_POINTS["c"], "%H:%M").time()
        
        if now < a_time:
            return "a"
        elif a_time <= now < b_time:
            return "b"
        elif b_time <= now < c_time:
            return "c"
        else:
            # 超过c点后返回a，为第二天做准备
            return "a"
    
    def start_scheduler(self):
        """启动任务调度器"""
        # 设置定时任务，在每个时间点执行余额检查
        for point, time_value in TIME_POINTS.items():
            schedule.every().day.at(time_value).do(self.trigger_balance_check_with_point, time_point=point)
            logger.info(f"已设置时间点 {point} ({time_value}) 的定时任务")
        
        # 启动调度线程
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("任务调度器已启动")
    
    def _run_scheduler(self):
        """运行调度器"""
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except Exception as e:
            logger.error(f"调度器运行异常: {str(e)}")
            logger.error(traceback.format_exc())
    
    def trigger_balance_check_with_point(self, time_point):
        """使用指定时间点触发余额检查"""
        logger.info(f"触发时间点 {time_point} 的余额检查")
        self.executor.submit(self.process_balance_check, time_point)
        return schedule.CancelJob  # 返回CancelJob是避免schedule库的潜在问题
    
    def trigger_balance_check(self):
        """触发余额检查，自动判断时间点"""
        time_point = self.get_time_point_by_now()
        logger.info(f"手动触发余额检查 (自动时间点: {time_point})")
        self.executor.submit(self.process_balance_check, time_point)
    
    def process_balance_check(self, time_point):
        """处理余额检查和状态更新"""
        try:
            logger.info(f"开始处理余额检查，时间点: {time_point}")
            start_time = time.time()
            
            conn = sqlite3.connect(DB_PATH)
            # 设置数据库连接以使用本地时区
            conn.execute("PRAGMA timezone='localtime'")
            cursor = conn.cursor()
            
            try:
                # 使用事务确保原子性
                conn.execute('BEGIN TRANSACTION')
                
                # 1. 查询所有余额大于0的记录
                cursor.execute('SELECT user, department, balance FROM kbk_ic_balance WHERE balance > 0')
                positive_balance_records = cursor.fetchall()
                
                if not positive_balance_records:
                    logger.info("未找到余额大于0的记录")
                    conn.commit()
                    return
                
                total_updated = 0
                
                # 2. 更新kbk_ic_manager表中相应用户的status为1
                local_time = self.get_local_timestamp()
                for user, department, balance in positive_balance_records:
                    # 更新status为1
                    cursor.execute(
                        '''UPDATE kbk_ic_manager 
                           SET status = 1, last_updated = ? 
                           WHERE user = ? AND department = ?''',
                        (local_time, user, department)
                    )
                    if cursor.rowcount > 0:
                        total_updated += 1
                    else:
                        logger.warning(f"用户不存在: {user}, {department}")
                
                # 3. 原子性递减kbk_ic_balance表中的balance值
                # 每个时间点递减1
                local_time = self.get_local_timestamp()
                cursor.execute(
                    '''UPDATE kbk_ic_balance 
                       SET balance = balance - 1, updated_at = ? 
                       WHERE balance > 0''',
                    (local_time,)
                )
                decremented_count = cursor.rowcount
                
                # 4. 将余额为0的用户状态设置为0
                local_time = self.get_local_timestamp()
                cursor.execute(
                    '''UPDATE kbk_ic_manager 
                       SET status = 0, last_updated = ? 
                       WHERE user IN (
                           SELECT user FROM kbk_ic_balance WHERE balance = 0
                       ) AND department IN (
                           SELECT department FROM kbk_ic_balance WHERE balance = 0
                       )''',
                    (local_time,)
                )
                zero_balance_updated = cursor.rowcount
                
                # 提交事务
                conn.commit()
                
                process_time = time.time() - start_time
                logger.info(f"余额检查完成，用户状态更新: {total_updated}条，余额递减: {decremented_count}条，"
                          f"余额为0状态更新: {zero_balance_updated}条，耗时: {process_time:.2f}秒")
                
                # 更新健康状态
                self.health_status["last_update"] = datetime.now().isoformat()
                self.health_status["status"] = "healthy"
                
            except Exception as e:
                conn.rollback()
                logger.error(f"余额检查过程中发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                self.health_status["errors"].append({
                    "time": datetime.now().isoformat(),
                    "type": "balance_check_process",
                    "message": str(e)
                })
                self.health_status["status"] = "error"
                raise
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"余额检查时出错: {str(e)}")
            logger.error(traceback.format_exc())
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "balance_check",
                "message": str(e)
            })
            self.health_status["status"] = "error"
    
    def sync_zero_balance_users(self):
        """同步余额为0的用户状态为0"""
        try:
            logger.info("开始同步余额为0的用户状态")
            start_time = time.time()
            
            conn = sqlite3.connect(DB_PATH)
            # 设置数据库连接以使用本地时区
            conn.execute("PRAGMA timezone='localtime'")
            cursor = conn.cursor()
            
            try:
                # 使用事务确保原子性
                conn.execute('BEGIN TRANSACTION')
                
                # 查询所有余额为0的用户
                cursor.execute('SELECT user, department FROM kbk_ic_balance WHERE balance = 0')
                zero_balance_users = cursor.fetchall()
                
                if not zero_balance_users:
                    logger.info("未找到余额为0的用户")
                    conn.commit()
                    return
                
                total_updated = 0
                
                # 更新kbk_ic_manager表中相应用户的status为0
                local_time = self.get_local_timestamp()
                for user, department in zero_balance_users:
                    cursor.execute(
                        '''UPDATE kbk_ic_manager 
                           SET status = 0, last_updated = ? 
                           WHERE user = ? AND department = ?''',
                        (local_time, user, department)
                    )
                    if cursor.rowcount > 0:
                        total_updated += 1
                
                # 提交事务
                conn.commit()
                
                process_time = time.time() - start_time
                logger.info(f"余额为0的用户状态同步完成，更新: {total_updated}条，耗时: {process_time:.2f}秒")
                
            except Exception as e:
                conn.rollback()
                logger.error(f"同步余额为0的用户状态时出错: {str(e)}")
                logger.error(traceback.format_exc())
                raise
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"同步余额为0的用户状态时出错: {str(e)}")
            logger.error(traceback.format_exc())
    
    def cleanup(self):
        """清理资源"""
        logger.info("正在清理资源...")
        if hasattr(self, 'observer') and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
        
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
        
        logger.info("资源已清理")

# API服务器
class BalanceManagerServer:
    """提供REST API接口的服务器"""
    
    def __init__(self, balance_manager, port=5555):
        """初始化API服务器"""
        self.balance_manager = balance_manager
        self.port = port
        self.app = Flask(__name__)
        CORS(self.app)
        
        # 注册路由
        self.register_routes()
    
    def register_routes(self):
        """注册API路由"""
        # 健康检查
        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify(self.balance_manager.health_status)
        
        # 手动导入Excel
        @self.app.route('/api/import', methods=['GET'])
        def import_excel():
            try:
                self.balance_manager.check_new_excel()
                return jsonify({
                    "success": True,
                    "message": "导入操作已触发，请检查日志获取详细信息",
                    "latest_excel": self.balance_manager.latest_excel
                })
            except Exception as e:
                logger.error(f"API导入Excel时出错: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({
                    "success": False,
                    "message": f"导入失败: {str(e)}",
                    "error": str(e)
                }), 500
        
        # 立即执行余额检查
        @self.app.route('/api/check-balance', methods=['GET'])
        def check_balance():
            try:
                time_point = request.args.get('time_point')
                if not time_point:
                    time_point = self.balance_manager.get_time_point_by_now()
                
                self.balance_manager.trigger_balance_check_with_point(time_point)
                return jsonify({
                    "success": True,
                    "message": f"时间点 {time_point} 的余额检查已触发",
                    "time_point": time_point
                })
            except Exception as e:
                logger.error(f"API触发余额检查时出错: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({
                    "success": False,
                    "message": f"触发余额检查失败: {str(e)}",
                    "error": str(e)
                }), 500
        
        # 查询用户余额
        @self.app.route('/api/balance', methods=['GET'])
        def get_balance():
            try:
                user = request.args.get('user')
                department = request.args.get('department')
                
                if not user:
                    return jsonify({
                        "success": False,
                        "message": "请提供user参数"
                    }), 400
                
                conn = sqlite3.connect(DB_PATH)
                # 设置数据库连接以使用本地时区
                conn.execute("PRAGMA timezone='localtime'")
                cursor = conn.cursor()
                
                if department:
                    cursor.execute(
                        'SELECT balance FROM kbk_ic_balance WHERE user = ? AND department = ?',
                        (user, department)
                    )
                else:
                    cursor.execute(
                        'SELECT department, balance FROM kbk_ic_balance WHERE user = ?',
                        (user,)
                    )
                
                result = cursor.fetchall()
                conn.close()
                
                if not result:
                    return jsonify({
                        "success": False,
                        "message": "未找到记录"
                    }), 404
                
                if department:
                    balance = result[0][0]
                    return jsonify({
                        "success": True,
                        "user": user,
                        "department": department,
                        "balance": balance
                    })
                else:
                    balances = [{"department": row[0], "balance": row[1]} for row in result]
                    return jsonify({
                        "success": True,
                        "user": user,
                        "balances": balances
                    })
                    
            except Exception as e:
                logger.error(f"API查询余额时出错: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({
                    "success": False,
                    "message": f"查询余额失败: {str(e)}",
                    "error": str(e)
                }), 500
        
        # 同步余额为0的用户
        @self.app.route('/api/sync-zero', methods=['GET'])
        def sync_zero():
            try:
                self.balance_manager.sync_zero_balance_users()
                return jsonify({
                    "success": True,
                    "message": "余额为0的用户状态同步已完成"
                })
            except Exception as e:
                logger.error(f"API同步余额为0的用户时出错: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({
                    "success": False,
                    "message": f"同步失败: {str(e)}",
                    "error": str(e)
                }), 500
    
    def start(self):
        """启动API服务器"""
        self.app.run(host='0.0.0.0', port=self.port, debug=False, threaded=True)

def main():
    """主函数"""
    try:
        # 解析命令行参数
        parser = argparse.ArgumentParser(description='余额管理系统')
        parser.add_argument('-p', '--port', type=int, default=5555, help='API服务器端口 (默认: 5555)')
        parser.add_argument('-e', '--excel-dir', type=str, default=EXCEL_DIR, help=f'Excel文件目录 (默认: {EXCEL_DIR})')
        parser.add_argument('-b', '--batch-size', type=int, default=BATCH_SIZE, help=f'批处理大小 (默认: {BATCH_SIZE})')
        parser.add_argument('--no-server', action='store_true', help='不启动API服务器')
        args = parser.parse_args()
        
        logger.info("余额管理系统启动中...")
        
        # 创建余额管理器
        balance_manager = BalanceManager(
            excel_folder=args.excel_dir,
            batch_size=args.batch_size
        )
        
        # 启动文件监控
        balance_manager.start_file_monitoring()
        
        # 启动任务调度器
        balance_manager.start_scheduler()
        
        if not args.no_server:
            # 启动API服务器
            server = BalanceManagerServer(balance_manager, port=args.port)
            logger.info(f"API服务器启动在端口 {args.port}")
            server.start()
        else:
            # 不启动API服务器，保持主线程运行
            logger.info("API服务器未启动，系统以后台模式运行")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        
    except KeyboardInterrupt:
        logger.info("检测到中断信号，系统正在关闭...")
    except Exception as e:
        logger.error(f"系统运行时出错: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        # 清理资源
        if 'balance_manager' in locals():
            balance_manager.cleanup()
        logger.info("余额管理系统已关闭")

if __name__ == "__main__":
    main()
