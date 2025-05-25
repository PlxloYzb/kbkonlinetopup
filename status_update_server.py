import os
import time
import pandas as pd
import schedule
import logging
import sqlite3
import aiohttp
import asyncio
import hashlib
import json
import watchdog.observers
import watchdog.events
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import prometheus_client as prom

# 设置Prometheus指标
REQUEST_COUNT = prom.Counter('duty_update_requests_total', '更新请求总数', ['time_point'])
UPDATE_COUNT = prom.Counter('duty_update_records_total', '更新记录总数', ['department'])
ERROR_COUNT = prom.Counter('duty_update_errors_total', '错误总数', ['type'])
PROCESS_TIME = prom.Histogram('duty_update_process_seconds', '处理时间(秒)')
MEAL_UPDATE_COUNT = prom.Counter('meal_update_records_total', '餐饮更新记录总数', ['meal_type'])

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ExcelFileHandler(watchdog.events.FileSystemEventHandler):
    """监控Excel文件变化的处理器"""
    
    def __init__(self, service):
        self.service = service
        super().__init__()
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到新文件: {event.src_path}")
            self.service.check_new_excel()
            
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到文件修改: {event.src_path}")
            # 如果是当前正在使用的文件被修改
            if self.service.latest_excel and event.src_path.endswith(self.service.latest_excel):
                logger.info(f"当前使用的文件已修改，重新加载文件: {self.service.latest_excel}")
                self.service.reload_excel()

class UniqueExcelFileHandler(watchdog.events.FileSystemEventHandler):
    """监控餐饮Excel文件变化的处理器"""
    
    def __init__(self, service):
        self.service = service
        super().__init__()
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到新餐饮文件: {event.src_path}")
            self.service.check_new_unique_excel()
            
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.xlsx'):
            logger.info(f"检测到餐饮文件修改: {event.src_path}")
            # 如果是当前正在使用的文件被修改
            if self.service.latest_unique_excel and event.src_path.endswith(self.service.latest_unique_excel):
                logger.info(f"当前使用的餐饮文件已修改，重新加载文件: {self.service.latest_unique_excel}")
                self.service.reload_unique_excel()

class DutyUpdateService:
    def __init__(self, excel_folder, db_config, time_points, unique_excel_folder=None, cache_size=500, batch_size=100, max_workers=4, monitor_port=5551):
        """
        初始化服务
        excel_folder: Excel文件存储路径
        db_config: 数据库配置信息，支持SQLite、MySQL和PostgreSQL
        time_points: 需要更新状态的时间点，格式为 {"a": "08:00", "b": "12:00", "c": "18:00"}
        unique_excel_folder: 餐饮Excel文件存储路径
        cache_size: 缓存大小
        batch_size: 批处理大小
        max_workers: 最大并发工作线程数
        monitor_port: prometheus监控端口，None表示不启动监控
        """
        self.excel_folder = excel_folder
        self.unique_excel_folder = unique_excel_folder
        self.db_config = db_config
        self.time_points = time_points
        self.latest_excel = None
        self.current_file_hash = None
        self.latest_unique_excel = None  # 最新的餐饮Excel文件
        self.current_unique_file_hash = None  # 餐饮文件哈希值
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.db_pool = None
        self.monitor_port = monitor_port
        # 健康状态
        self.health_status = {
            "status": "healthy",
            "last_update": None,
            "latest_excel": None,
            "latest_unique_excel": None,  # 添加餐饮Excel文件状态
            "errors": []
        }
        # 启动监控服务（仅当端口不为None时）
        if self.monitor_port is not None:
            self.start_monitoring(self.monitor_port)
        
    def start_monitoring(self, port):
        """启动Prometheus监控服务"""
        prom.start_http_server(port)
        logger.info(f"监控服务已启动在端口 {port}")
        
    def start(self):
        """启动服务"""
        # 设置定时任务
        for point, time_value in self.time_points.items():
            schedule.every().day.at(time_value).do(self.trigger_update, time_point=point)
        
        # 添加餐饮数据定时任务
        if self.unique_excel_folder:
            # a时间点后2分钟的周一早餐任务
            a_time = datetime.strptime(self.time_points["a"], "%H:%M")
            a_plus_2min = a_time + timedelta(minutes=1)
            c_time = datetime.strptime(self.time_points["c"], "%H:%M")
            c_plus_2min = c_time + timedelta(minutes=1)
            
            # 周一早餐任务
            schedule.every().monday.at(a_plus_2min.strftime("%H:%M")).do(
                self.trigger_unique_update, meal_type="breakfast"
            )
            
            # 周日晚餐任务
            schedule.every().sunday.at(c_plus_2min.strftime("%H:%M")).do(
                self.trigger_unique_update, meal_type="dinner"
            )
            logger.info(f"设置了餐饮任务: 周一 {a_plus_2min.strftime('%H:%M')} 早餐, 周日 {c_plus_2min.strftime('%H:%M')} 晚餐")
        
        # 启动文件监控
        self.start_file_monitoring()
        
        # 启动异步事件循环
        loop = asyncio.get_event_loop()
        
        # 初始化数据库连接池
        loop.run_until_complete(self.initialize_db_pool())
        
        try:
            logger.info("服务已启动")
            # 首次运行时检查一次
            self.check_new_excel()
            if self.unique_excel_folder:
                self.check_new_unique_excel()
            
            # 保持服务运行
            while True:
                loop.run_until_complete(self.run_scheduled_tasks())
                time.sleep(1)  # 每秒检查一次调度任务
        except KeyboardInterrupt:
            logger.info("服务已停止")
        finally:
            # 关闭数据库连接池
            if self.db_pool:
                loop.run_until_complete(self.close_db_pool())
            self.executor.shutdown(wait=True)
            
    def start_file_monitoring(self):
        """启动文件监控"""
        # 监控普通排班Excel文件
        self.event_handler = ExcelFileHandler(self)
        self.observer = watchdog.observers.Observer()
        self.observer.schedule(self.event_handler, self.excel_folder, recursive=False)
        self.observer.start()
        logger.info(f"文件监控已启动，监控文件夹: {self.excel_folder}")
        
        # 监控餐饮Excel文件
        if self.unique_excel_folder:
            self.unique_event_handler = UniqueExcelFileHandler(self)
            self.unique_observer = watchdog.observers.Observer()
            self.unique_observer.schedule(self.unique_event_handler, self.unique_excel_folder, recursive=False)
            self.unique_observer.start()
            logger.info(f"餐饮文件监控已启动，监控文件夹: {self.unique_excel_folder}")
            
    async def run_scheduled_tasks(self):
        """运行所有待执行的调度任务"""
        schedule.run_pending()
        
    def check_new_excel(self):
        """检查是否有新的Excel文件"""
        try:
            excel_files = [f for f in os.listdir(self.excel_folder) 
                          if f.endswith('.xlsx') and self._is_date_format(f.split('.')[0])]
            
            if not excel_files:
                return
            
            # 按日期排序文件
            excel_files.sort(key=lambda x: datetime.strptime(x.split('.')[0], '%Y-%m-%d'), reverse=True)
            newest_file = excel_files[0]
            newest_file_path = os.path.join(self.excel_folder, newest_file)
            
            # 计算文件哈希值
            new_hash = self.get_file_hash(newest_file_path)
            
            # 如果是新文件或文件内容有变化
            if self.latest_excel != newest_file or self.current_file_hash != new_hash:
                logger.info(f"发现新的或已修改的排班文件: {newest_file}")
                self.latest_excel = newest_file
                self.current_file_hash = new_hash
                self.health_status["latest_excel"] = newest_file
                # 清除缓存
                self.get_sheet_data.cache_clear()
                
                # Excel文件已更新，立即触发一次数据库更新（根据当前时间判断时间点）
                logger.info("Excel文件已更新，立即触发一次数据库更新")
                self.trigger_update()
                
        except Exception as e:
            ERROR_COUNT.labels(type='file_check').inc()
            logger.error(f"检查新Excel文件时出错: {str(e)}")
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
            
            # 如果文件内容有变化，更新缓存
            if self.current_file_hash != new_hash:
                logger.info(f"文件内容已变更，更新缓存: {self.latest_excel}")
                self.current_file_hash = new_hash
                
                # 清除缓存
                self.get_sheet_data.cache_clear()
                
                # Excel文件已更新，立即触发一次数据库更新（根据当前时间判断时间点）
                logger.info("Excel文件已更新，立即触发一次数据库更新")
                self.trigger_update()
                
        except Exception as e:
            ERROR_COUNT.labels(type='file_reload').inc()
            logger.error(f"重新加载Excel文件时出错: {str(e)}")
    
    def _is_date_format(self, date_str):
        """检查字符串是否为日期格式 YYYY-MM-DD"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return False
            
    def get_time_point_by_now(self):
        """根据当前时间判断应使用哪个时间点标识（a、b、c）"""
        now = datetime.now().time()
        a_time = datetime.strptime(self.time_points["a"], "%H:%M").time()
        b_time = datetime.strptime(self.time_points["b"], "%H:%M").time()
        c_time = datetime.strptime(self.time_points["c"], "%H:%M").time()
        if now < a_time:
            return "a"
        elif a_time <= now < b_time:
            return "b"
        elif b_time <= now < c_time:
            return "c"
        else:
            # 超过c点后不再有区间，可根据实际业务返回None或c，这里返回None
            return "a"
    def trigger_update(self, time_point=None):
        """触发异步更新任务，支持自动判断时间点"""
        if time_point is None:
            time_point = self.get_time_point_by_now()
        REQUEST_COUNT.labels(time_point=time_point).inc()
        logger.info(f"触发时间点 {time_point} 的更新任务")
        self.executor.submit(self.run_async_update, time_point)
        return schedule.CancelJob
        
    def run_async_update(self, time_point):
        """在线程池中运行异步更新任务"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self.update_status(time_point))
        except Exception as e:
            logger.error(f"执行更新任务时出错: {str(e)}")
        finally:
            loop.close()
            
    @lru_cache(maxsize=10)
    def get_sheet_data(self, file_path, sheet_name):
        """
        读取并缓存Excel表格数据
        使用LRU缓存减少重复读取
        """
        logger.info(f"读取并缓存sheet: {sheet_name}")
        return pd.read_excel(file_path, sheet_name=sheet_name)
    
    def get_file_hash(self, file_path):
        """获取文件的MD5哈希值，用于缓存标识"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()
    
    async def initialize_db_pool(self):
        """初始化数据库连接池"""
        try:
            self.db_pool = await self.create_db_pool()
            logger.info("数据库连接池初始化成功")
        except Exception as e:
            logger.error(f"初始化数据库连接池失败: {str(e)}")
            raise
            
    async def close_db_pool(self):
        """关闭数据库连接池"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("数据库连接池已关闭")
            
    async def create_db_pool(self):
        """创建异步数据库连接池"""
        db_type = self.db_config.get("type", "sqlite").lower()
        
        if db_type == "sqlite":
            # SQLite连接
            import aiosqlite
            conn = await aiosqlite.connect(self.db_config["path"])
            conn.row_factory = aiosqlite.Row
            return conn
        
        # elif db_type == "mysql":
        #     # MySQL连接
        #     import aiomysql
        #     pool = await aiomysql.create_pool(
        #         host=self.db_config["host"],
        #         port=self.db_config.get("port", 3306),
        #         user=self.db_config["user"],
        #         password=self.db_config["password"],
        #         db=self.db_config["database"],
        #         charset=self.db_config.get("charset", "utf8mb4"),
        #         autocommit=False,
        #         maxsize=self.db_config.get("pool_size", 10),
        #         minsize=self.db_config.get("min_size", 1)
        #     )
        #     return pool
            
        # elif db_type == "postgresql":
        #     # PostgreSQL连接
        #     import asyncpg
        #     pool = await asyncpg.create_pool(
        #         host=self.db_config["host"],
        #         port=self.db_config.get("port", 5432),
        #         user=self.db_config["user"],
        #         password=self.db_config["password"],
        #         database=self.db_config["database"],
        #         min_size=self.db_config.get("min_size", 1),
        #         max_size=self.db_config.get("pool_size", 10)
        #     )
        #     return pool
        
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")
            
    async def update_status(self, time_point):
        """在指定时间点异步更新数据库状态"""
        start_time = time.time()
        
        if not self.latest_excel:
            logger.warning("未找到有效的排班文件，跳过更新")
            return
            
        try:
            # 打开Excel文件
            file_path = os.path.join(self.excel_folder, self.latest_excel)
            excel = pd.ExcelFile(file_path)
            
            # 获取所有部门的sheet
            departments = excel.sheet_names
            
            total_updates = 0
            
            # 并发处理所有部门
            tasks = []
            for dept in departments:
                task = self.process_department(file_path, dept, time_point)
                tasks.append(task)
                
            # 等待所有部门处理完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"处理部门时出错: {str(result)}")
                    ERROR_COUNT.labels(type='department_process').inc()
                else:
                    total_updates += result
            
            # 更新健康状态
            self.health_status["last_update"] = datetime.now().isoformat()
            self.health_status["status"] = "healthy"
            
            process_time = time.time() - start_time
            PROCESS_TIME.observe(process_time)
            
            logger.info(f"时间点 {time_point} 的更新完成，共更新 {total_updates} 条记录，耗时 {process_time:.2f} 秒")
            
        except Exception as e:
            ERROR_COUNT.labels(type='update_process').inc()
            logger.error(f"更新状态时出错: {str(e)}")
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "update_process",
                "message": str(e)
            })
            self.health_status["status"] = "error"
            
    async def process_department(self, file_path, dept, time_point):
        """处理单个部门的数据更新"""
        try:
            # 读取并缓存部门的排班数据
            df = self.get_sheet_data(file_path, dept)
            
            # 筛选需要更新的用户
            users_to_update = []
            
            # 遍历员工排班信息
            for _, row in df.iterrows():
                user = row['user']
                is_on_duty = row['is_on_duty']
                shift = str(row['shift']).lower() if pd.notna(row['shift']) else ""
                card = row['card'] if 'card' in row and pd.notna(row['card']) else None
                
                # 分开处理值班状态为1和0的情况
                if is_on_duty == 1:
                    # 值班状态为1时，根据班次和时间点决定是否更新
                    should_update = False
                    
                    if shift in ['ns', 'lds'] and time_point in ['a', 'b', 'c']:
                        should_update = True
                    elif shift == 'ds' and time_point in ['a', 'c']:
                        should_update = True
                        
                    if should_update:
                        users_to_update.append({
                            "user": user,
                            "department": dept,
                            "card": card,
                            "status": 1
                        })
                elif is_on_duty == 0:
                    # 值班状态为0时，将状态更新为0（仅执行更新操作，不执行插入）
                    users_to_update.append({
                        "user": user,
                        "department": dept,
                        "card": card,
                        "status": 0,
                        "update_only": True  # 标记仅执行更新，不执行插入
                    })
            
            # 如果没有需要更新的用户，直接返回
            if not users_to_update:
                return 0
                
            # 批量更新数据库
            update_count = await self.batch_update_users(users_to_update)
            UPDATE_COUNT.labels(department=dept).inc(update_count)
            
            logger.info(f"部门 {dept} 在时间点 {time_point} 更新了 {update_count} 条记录")
            return update_count
            
        except Exception as e:
            logger.error(f"处理部门 {dept} 时出错: {str(e)}")
            raise
            
    async def batch_update_users(self, users):
        """批量更新用户状态，不存在则插入，插入时带department、card、status字段，更新时也同步更新card、department、status（不处理is_on_duty）"""
        db_type = self.db_config.get("type", "sqlite").lower()
        total_updated = 0
        # 获取本地当前时间字符串
        from datetime import datetime
        local_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 将用户列表分成批次
        batches = [users[i:i+self.batch_size] for i in range(0, len(users), self.batch_size)]
        try:
            if db_type == "sqlite":
                # SQLite批量更新
                # 将 cursor 操作和 commit 分开
                async with self.db_pool.cursor() as cursor:
                    for batch in batches:
                        user_names = [u["user"] for u in batch]
                        # 依次更新每个用户的所有字段（不处理is_on_duty）
                        updated_count = 0
                        for u in batch:
                            await cursor.execute(
                                "UPDATE kbk_ic_manager SET card = ?, department = ?, status = ?, last_updated = ? WHERE user = ?",
                                (u["card"], u["department"], u["status"], local_now, u["user"])
                            )
                            updated_count += cursor.rowcount
                        total_updated += updated_count
                        # 查找未被更新的用户（即数据库不存在的用户）
                        if updated_count < len(user_names):
                            placeholders = ','.join(['?'] * len(user_names))
                            await cursor.execute(f"SELECT user, card FROM kbk_ic_manager WHERE user IN ({placeholders})", user_names)
                            exist_users = set([row[0] for row in await cursor.fetchall()])
                            # 新增：查找已存在的card，避免唯一性冲突
                            card_values = [u["card"] for u in batch if u["card"] is not None]
                            if card_values:
                                card_placeholders = ','.join(['?'] * len(card_values))
                                await cursor.execute(f"SELECT card FROM kbk_ic_manager WHERE card IN ({card_placeholders})", card_values)
                                exist_cards = set([row[0] for row in await cursor.fetchall()])
                            else:
                                exist_cards = set()
                            # 只对没有update_only标记且card未冲突的用户执行插入操作
                            to_insert_candidates = [u for u in batch if u["user"] not in exist_users and not u.get("update_only", False) and (u["card"] is None or u["card"] not in exist_cards)]
                            
                            actually_inserted_cards_in_batch = set() # To track cards inserted in THIS loop iteration for THIS batch
                            
                            for u_candidate in to_insert_candidates:
                                if u_candidate["card"] is not None and u_candidate["card"] in actually_inserted_cards_in_batch:
                                    logger.warning(f"Skipping insertion of user {u_candidate['user']} with card {u_candidate['card']} as this card was already used for insertion in the current batch.")
                                    continue

                                try:
                                    await cursor.execute(
                                        "INSERT INTO kbk_ic_manager (user, card, department, status, last_updated) VALUES (?, ?, ?, ?, ?)",
                                        (u_candidate["user"], u_candidate["card"], u_candidate["department"], u_candidate["status"], local_now)
                                    )
                                    if u_candidate["card"] is not None:
                                        actually_inserted_cards_in_batch.add(u_candidate["card"])
                                    total_updated += 1 
                                except sqlite3.IntegrityError as integrity_error:
                                    logger.error(f"IntegrityError during insertion for user {u_candidate['user']} with card {u_candidate['card']}: {integrity_error}. This card might have been inserted by a concurrent operation or pre-check missed it.")
                                    ERROR_COUNT.labels(type='batch_insert_integrity_error').inc()
                                except Exception as general_insert_error:
                                    logger.error(f"Unexpected error during insertion for user {u_candidate['user']} with card {u_candidate['card']}: {general_insert_error}")
                                    ERROR_COUNT.labels(type='batch_insert_unexpected_error').inc()
                            # 记录日志：标记为update_only但未找到的用户
                            update_only_users = [u["user"] for u in batch if u["user"] not in exist_users and u.get("update_only", False)]
                            if update_only_users:
                                logger.info(f"跳过插入update_only标记的用户: {', '.join(update_only_users)}")
                # commit 操作移到 cursor 上下文管理器外面
                await self.db_pool.commit()
            else:
                raise ValueError(f"不支持的数据库类型: {db_type}")
            return total_updated
        except Exception as e:
            logger.error(f"批量更新用户时出错: {str(e)}")
            raise
        
    async def get_health(self, request):
        """返回服务健康状态"""
        # 健康检查API
        return aiohttp.web.json_response(self.health_status)
    
    def cleanup(self):
        """清理资源"""
        if hasattr(self, 'observer') and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
            
        # 清理餐饮文件监控器
        if hasattr(self, 'unique_observer') and self.unique_observer.is_alive():
            self.unique_observer.stop()
            self.unique_observer.join()
        
        # 关闭线程池
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
        
        logger.info("资源已清理")

    def check_new_unique_excel(self):
        """检查是否有新的餐饮Excel文件"""
        if not self.unique_excel_folder:
            return
            
        try:
            excel_files = [f for f in os.listdir(self.unique_excel_folder) 
                          if f.endswith('.xlsx') and self._is_date_format(f.split('.')[0])]
            
            if not excel_files:
                return
            
            # 按日期排序文件
            excel_files.sort(key=lambda x: datetime.strptime(x.split('.')[0], '%Y-%m-%d'), reverse=True)
            newest_file = excel_files[0]
            newest_file_path = os.path.join(self.unique_excel_folder, newest_file)
            
            # 计算文件哈希值
            new_hash = self.get_file_hash(newest_file_path)
            
            # 如果是新文件或文件内容有变化
            if self.latest_unique_excel != newest_file or self.current_unique_file_hash != new_hash:
                logger.info(f"发现新的或已修改的餐饮文件: {newest_file}")
                self.latest_unique_excel = newest_file
                self.current_unique_file_hash = new_hash
                self.health_status["latest_unique_excel"] = newest_file
                # 清除缓存
                self.get_sheet_data.cache_clear()
                
        except Exception as e:
            ERROR_COUNT.labels(type='unique_file_check').inc()
            logger.error(f"检查新餐饮Excel文件时出错: {str(e)}")
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "unique_file_check",
                "message": str(e)
            })
            self.health_status["status"] = "warning"
    
    def reload_unique_excel(self):
        """重新加载当前餐饮Excel文件"""
        if not self.latest_unique_excel or not self.unique_excel_folder:
            return
            
        try:
            file_path = os.path.join(self.unique_excel_folder, self.latest_unique_excel)
            
            # 计算新的哈希值
            new_hash = self.get_file_hash(file_path)
            
            # 如果文件内容有变化，更新缓存
            if self.current_unique_file_hash != new_hash:
                logger.info(f"餐饮文件内容已变更，更新缓存: {self.latest_unique_excel}")
                self.current_unique_file_hash = new_hash
                
                # 清除缓存
                self.get_sheet_data.cache_clear()
                
        except Exception as e:
            ERROR_COUNT.labels(type='unique_file_reload').inc()
            logger.error(f"重新加载餐饮Excel文件时出错: {str(e)}")
    
    def trigger_unique_update(self, meal_type):
        """触发餐饮异步更新任务"""
        logger.info(f"触发{meal_type}餐饮更新任务")
        self.executor.submit(self.run_async_unique_update, meal_type)
        return schedule.CancelJob
        
    def run_async_unique_update(self, meal_type):
        """在线程池中运行餐饮异步更新任务"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self.update_meal_status(meal_type))
        except Exception as e:
            logger.error(f"执行餐饮更新任务时出错: {str(e)}")
        finally:
            loop.close()
            
    async def update_meal_status(self, meal_type):
        """更新餐饮状态"""
        start_time = time.time()
        
        if not self.latest_unique_excel or not self.unique_excel_folder:
            logger.warning(f"未找到有效的餐饮文件，跳过{meal_type}更新")
            return
            
        try:
            # 打开Excel文件
            file_path = os.path.join(self.unique_excel_folder, self.latest_unique_excel)
            excel = pd.ExcelFile(file_path)
            
            # 获取所有部门的sheet
            departments = excel.sheet_names
            
            total_updates = 0
            
            # 并发处理所有部门
            tasks = []
            for dept in departments:
                task = self.process_meal_department(file_path, dept, meal_type)
                tasks.append(task)
                
            # 等待所有部门处理完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"处理部门餐饮时出错: {str(result)}")
                    ERROR_COUNT.labels(type='meal_department_process').inc()
                else:
                    total_updates += result
            
            # 更新健康状态
            self.health_status["last_update"] = datetime.now().isoformat()
            self.health_status["status"] = "healthy"
            
            process_time = time.time() - start_time
            PROCESS_TIME.observe(process_time)
            
            logger.info(f"餐饮类型 {meal_type} 的更新完成，共更新 {total_updates} 条记录，耗时 {process_time:.2f} 秒")
            MEAL_UPDATE_COUNT.labels(meal_type=meal_type).inc(total_updates)
            
        except Exception as e:
            ERROR_COUNT.labels(type='meal_update_process').inc()
            logger.error(f"更新餐饮状态时出错: {str(e)}")
            self.health_status["errors"].append({
                "time": datetime.now().isoformat(),
                "type": "meal_update_process",
                "message": str(e)
            })
            self.health_status["status"] = "error"

    async def process_meal_department(self, file_path, dept, meal_type):
        """处理单个部门的餐饮数据更新"""
        try:
            # 读取并缓存部门的餐饮数据
            df = self.get_sheet_data(file_path, dept)
            
            # 确保需要的列存在
            if meal_type not in df.columns:
                logger.warning(f"部门 {dept} 的表格中没有 {meal_type} 列")
                return 0
                
            # 筛选需要更新的用户
            users_to_update = []
            
            # 遍历员工餐饮信息，找出有值的用户
            for _, row in df.iterrows():
                if pd.notna(row[meal_type]) and row[meal_type]:
                    user = str(row[meal_type]).strip()  # 确保用户名是字符串并去除空格
                    if user:  # 确保用户名不为空
                        users_to_update.append({
                            "user": user,
                            "department": dept,
                            "status": 1  # 设置状态为1
                        })
            
            # 如果没有需要更新的用户，直接返回
            if not users_to_update:
                return 0
                
            # 批量更新数据库
            update_count = await self.batch_meal_update_users(users_to_update)
            
            logger.info(f"部门 {dept} 的 {meal_type} 更新了 {update_count} 条记录")
            return update_count
            
        except Exception as e:
            logger.error(f"处理部门 {dept} 的 {meal_type} 时出错: {str(e)}")
            raise
            
    async def batch_meal_update_users(self, users):
        """批量更新餐饮用户状态，只更新status为1，不执行插入操作"""
        db_type = self.db_config.get("type", "sqlite").lower()
        total_updated = 0
        # 获取本地当前时间字符串
        local_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 将用户列表分成批次
        batches = [users[i:i+self.batch_size] for i in range(0, len(users), self.batch_size)]
        
        try:
            if db_type == "sqlite":
                # SQLite批量更新
                async with self.db_pool.cursor() as cursor:
                    for batch in batches:
                        # 只更新status字段为1，不执行插入操作
                        for u in batch:
                            await cursor.execute(
                                "UPDATE kbk_ic_manager SET status = ?, last_updated = ? WHERE user = ?",
                                (u["status"], local_now, u["user"])
                            )
                            if cursor.rowcount > 0:
                                total_updated += cursor.rowcount
                
                # 提交事务
                await self.db_pool.commit()
            else:
                raise ValueError(f"不支持的数据库类型: {db_type}")
            
            return total_updated
        except Exception as e:
            logger.error(f"批量更新餐饮用户时出错: {str(e)}")
            raise

# 使用示例
if __name__ == "__main__":
    # 配置参数
    excel_folder = "./excel"
    unique_excel_folder = "./excel_unique"  # 餐饮Excel文件夹
    
    # 支持多种数据库配置
    # SQLite 配置
    sqlite_config = {
        "type": "sqlite",
        "path": "./ic_manager.db"
    }
    
    # # MySQL 配置
    # mysql_config = {
    #     "type": "mysql",
    #     "host": "localhost",
    #     "port": 3306,
    #     "user": "username",
    #     "password": "password",
    #     "database": "employees_db",
    #     "charset": "utf8mb4",
    #     "pool_size": 10
    # }
    
    # # PostgreSQL 配置
    # postgresql_config = {
    #     "type": "postgresql",
    #     "host": "localhost",
    #     "port": 5432,
    #     "user": "username",
    #     "password": "password",
    #     "database": "employees_db",
    #     "pool_size": 10
    # }
    
    # 选择要使用的数据库配置
    db_config = sqlite_config  # 或 mysql_config 或 postgresql_config
    
    time_points = {
        "a": "05:25",
        "b": "11:25", 
        "c": "16:55"
    }
    
    # 创建并启动HTTP服务器来提供健康状态API
    async def start_http_server(service):
        from aiohttp import web
        app = web.Application()
        app.router.add_get('/health', service.get_health)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 5552)
        
        await site.start()
        logger.info("HTTP服务器已启动在端口 5552")
    
    # 创建服务实例
    service = DutyUpdateService(
        excel_folder, db_config, time_points, 
        unique_excel_folder=unique_excel_folder,  # 添加餐饮Excel文件夹
        cache_size=20, batch_size=100, max_workers=4
    )
    
    try:
        # 启动HTTP服务器
        loop = asyncio.get_event_loop()
        loop.create_task(start_http_server(service))
        
        # 启动主服务
        service.start()
    except KeyboardInterrupt:
        logger.info("收到终止信号，正在关闭服务...")
    finally:
        # 清理资源
        service.cleanup()
