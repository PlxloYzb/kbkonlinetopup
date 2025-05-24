import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import json
import schedule
import time
import threading
from typing import Dict, List, Any
import logging
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
import functools
import re

# 必须首先设置页面配置
st.set_page_config(
    page_title="IC卡管理系统",
    page_icon="🏢",
    layout="wide"
)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = './ic_manager.db'
TASKS_FILE = './custom_tasks.json'

class TaskStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskType(Enum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"

@dataclass
class CustomTask:
    id: str
    name: str
    description: str
    task_type: TaskType
    status: TaskStatus
    target_status: int  # 要设置的status值（0或1）
    department_filter: str  # 部门筛选条件
    user_filter: str  # 用户筛选条件
    execute_time: str  # 执行时间
    recurring_pattern: str  # 重复模式（daily, weekly, monthly等）
    created_at: str
    last_executed: str = None
    next_execution: str = None
    execution_count: int = 0
    recurring_details: str = None  # 存储重复任务的额外详情

def get_formatted_timestamp():
    """获取格式化的时间戳 (YYYY-MM-DD HH:MM:SS)"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

class TaskScheduler:
    def __init__(self):
        self.tasks: Dict[str, CustomTask] = {}
        self.running = False
        self.thread = None
        self._scheduler_lock = threading.Lock()
        self.load_tasks()
    
    def load_tasks(self):
        """从文件加载任务"""
        try:
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
                for task_data in tasks_data:
                    # 为兼容性添加默认的recurring_details字段
                    if 'recurring_details' not in task_data:
                        task_data['recurring_details'] = None
                    
                    # 确保recurring_pattern不是None（旧版本可能保存为None）
                    if task_data.get('recurring_pattern') is None and task_data.get('task_type') == 'recurring':
                        task_data['recurring_pattern'] = 'daily'  # 默认为每日
                        logger.warning(f"任务 {task_data.get('name', 'unknown')} 的recurring_pattern为None，设置为默认值'daily'")
                    
                    task = CustomTask(**task_data)
                    task.task_type = TaskType(task.task_type)
                    task.status = TaskStatus(task.status)
                    self.tasks[task.id] = task
        except FileNotFoundError:
            self.tasks = {}
        except Exception as e:
            logger.error(f"加载任务失败: {e}")
            self.tasks = {}
    
    def save_tasks(self):
        """保存任务到文件"""
        try:
            tasks_data = []
            for task in self.tasks.values():
                task_dict = asdict(task)
                task_dict['task_type'] = task.task_type.value
                task_dict['status'] = task.status.value
                tasks_data.append(task_dict)
            
            with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存任务失败: {e}")
    
    def add_task(self, task: CustomTask):
        """添加任务"""
        if task.status == TaskStatus.ACTIVE:
            task.next_execution = self._calculate_next_execution(task)
        self.tasks[task.id] = task
        self.save_tasks()
        self._schedule_task(task)
        self.ensure_scheduler_running()
        logger.info(f"任务 '{task.name}' 已添加并调度")
    
    def update_task(self, task: CustomTask):
        """更新任务"""
        if task.status == TaskStatus.ACTIVE:
            task.next_execution = self._calculate_next_execution(task)
        self.tasks[task.id] = task
        self.save_tasks()
        schedule.clear(task.id)
        if task.status == TaskStatus.ACTIVE:
            self._schedule_task(task)
        logger.info(f"任务 '{task.name}' 已更新")
    
    def delete_task(self, task_id: str):
        """删除任务"""
        if task_id in self.tasks:
            schedule.clear(task_id)
            del self.tasks[task_id]
            self.save_tasks()
            logger.info(f"任务ID '{task_id}' 已删除")
    
    def pause_task(self, task_id: str):
        """暂停任务"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.PAUSED
            schedule.clear(task_id)
            self.save_tasks()
            logger.info(f"任务ID '{task_id}' 已暂停")
    
    def resume_task(self, task_id: str):
        """恢复任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.ACTIVE
            task.next_execution = self._calculate_next_execution(task)
            self._schedule_task(task)
            self.save_tasks()
            self.ensure_scheduler_running()
            logger.info(f"任务ID '{task_id}' 已恢复")
    
    def execute_task_now(self, task_id: str):
        """立即执行任务"""
        if task_id in self.tasks:
            logger.info(f"立即执行任务ID '{task_id}'")
            self._execute_task(task_id)
    
    def _create_task_executor(self, task_id: str):
        """创建任务执行器，解决lambda闭包问题"""
        def executor():
            if task_id in self.tasks:
                self._execute_task(task_id)
        return executor
    
    def _create_conditional_executor(self, task_id: str, condition_func):
        """创建条件执行器"""
        def executor():
            if task_id in self.tasks and condition_func():
                self._execute_task(task_id)
        return executor
    
    def _schedule_task(self, task: CustomTask):
        """调度任务"""
        if task.status != TaskStatus.ACTIVE:
            logger.info(f"任务 '{task.name}' 状态为 {task.status.value}，不进行调度")
            return
        
        try:
            # 统一处理时间格式
            if ' ' in task.execute_time:  # 完整日期时间格式
                time_str = task.execute_time.split(' ')[1]
                date_str = task.execute_time.split(' ')[0]
            else:  # 只有时间部分
                time_str = task.execute_time
                date_str = None
            
            # 验证时间格式
            try:
                hour, minute = map(int, time_str.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except:
                logger.error(f"无效的时间格式: {time_str}")
                return

            if task.task_type == TaskType.ONE_TIME:
                # 一次性任务
                if date_str is None:
                    logger.error(f"一次性任务 '{task.name}' 缺少日期信息")
                    return
                
                execute_datetime = datetime.strptime(task.execute_time, '%Y-%m-%d %H:%M')
                if execute_datetime <= datetime.now():
                    logger.info(f"一次性任务 '{task.name}' 的执行时间已过期")
                    task.status = TaskStatus.COMPLETED
                    self.save_tasks()
                    return
                
                target_date = execute_datetime.date()
                target_time = execute_datetime.strftime('%H:%M')
                
                # 创建日期检查函数
                def check_date():
                    return datetime.now().date() == target_date
                
                # 使用固定的task_id而不是task对象
                job = schedule.every().day.at(target_time).do(
                    self._create_conditional_executor(task.id, check_date)
                )
                job.tag(task.id)
                logger.info(f"已调度一次性任务: {task.name} 在 {task.execute_time}")
            else:
                # 重复任务
                executor = self._create_task_executor(task.id)
                
                logger.info(f"正在调度重复任务 {task.name}, 模式: {task.recurring_pattern}, 时间: {time_str}")
                
                if task.recurring_pattern == 'daily':
                    job = schedule.every().day.at(time_str).do(executor)
                    job.tag(task.id)
                elif task.recurring_pattern == 'weekly':
                    job = schedule.every().week.at(time_str).do(executor)
                    job.tag(task.id)
                elif task.recurring_pattern == 'monthly':
                    job = schedule.every(30).days.at(time_str).do(executor)
                    job.tag(task.id)
                elif task.recurring_pattern in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    weekday_func = getattr(schedule.every(), task.recurring_pattern)
                    job = weekday_func.at(time_str).do(executor)
                    job.tag(task.id)
                elif task.recurring_pattern == 'monthly_date':
                    # 每月特定日期
                    try:
                        if task.recurring_details:
                            day_of_month = int(json.loads(task.recurring_details))
                        else:
                            day_of_month = 1
                        
                        def check_monthly_date():
                            return datetime.now().day == day_of_month
                        
                        job = schedule.every().day.at(time_str).do(
                            self._create_conditional_executor(task.id, check_monthly_date)
                        )
                        job.tag(task.id)
                    except Exception as e:
                        logger.error(f"调度monthly_date任务失败 {task.name}: {e}")
                        job = schedule.every(30).days.at(time_str).do(executor)
                        job.tag(task.id)
                elif task.recurring_pattern == 'selected_dates':
                    # 选定日期
                    try:
                        selected_dates = []
                        if task.recurring_details:
                            dates_data = json.loads(task.recurring_details)
                            if isinstance(dates_data, list):
                                selected_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in dates_data]
                        
                        def check_selected_date():
                            return datetime.now().date() in selected_dates
                        
                        job = schedule.every().day.at(time_str).do(
                            self._create_conditional_executor(task.id, check_selected_date)
                        )
                        job.tag(task.id)
                    except Exception as e:
                        logger.error(f"调度selected_dates任务失败 {task.name}: {e}")
                        job = schedule.every().day.at(time_str).do(executor)
                        job.tag(task.id)
                else:
                    # 如果没有recurring_pattern或未知模式，默认为每日
                    logger.warning(f"任务 {task.name} 的重复模式为 {task.recurring_pattern}，使用默认每日模式")
                    job = schedule.every().day.at(time_str).do(executor)
                    job.tag(task.id)
                
                logger.info(f"已成功调度重复任务: {task.name} 模式: {task.recurring_pattern} 时间: {time_str}")
            
            logger.info(f"当前schedule.jobs数量: {len(schedule.jobs)}")
        except Exception as e:
            logger.error(f"调度任务失败 {task.name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _execute_task(self, task_id: str):
        """执行任务"""
        try:
            if task_id not in self.tasks:
                logger.error(f"任务不存在: {task_id}")
                return
                
            task = self.tasks[task_id]
            logger.info(f"开始执行任务: {task.name}")
            
            # 构建SQL查询条件
            conditions = []
            params = []
            
            if task.department_filter:
                conditions.append("department LIKE ?")
                params.append(f"%{task.department_filter}%")
            
            if task.user_filter:
                # 处理用户筛选：如果包含逗号，说明是选中的用户列表
                if ',' in task.user_filter:
                    users = [user.strip() for user in task.user_filter.split(',')]
                    placeholders = ','.join(['?' for _ in users])
                    conditions.append(f"user IN ({placeholders})")
                    params.extend(users)
                else:
                    conditions.append("user LIKE ?")
                    params.append(f"%{task.user_filter}%")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 执行数据库更新
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            update_sql = f"""
                UPDATE kbk_ic_manager 
                SET status = ?, last_updated = ? 
                WHERE {where_clause}
            """
            
            # 使用格式化的时间戳
            update_params = [task.target_status, get_formatted_timestamp()] + params
            cursor.execute(update_sql, update_params)
            
            affected_rows = cursor.rowcount
            conn.commit()
            conn.close()
            
            # 更新任务状态
            task.last_executed = get_formatted_timestamp()
            task.execution_count += 1
            
            if task.task_type == TaskType.ONE_TIME:
                task.status = TaskStatus.COMPLETED
                task.next_execution = None
                schedule.clear(task.id)
            else:
                # 计算下一次执行时间
                task.next_execution = self._calculate_next_execution(task)
            
            self.save_tasks()
            
            logger.info(f"任务执行完成: {task.name}, 影响行数: {affected_rows}")
            
        except Exception as e:
            logger.error(f"任务执行失败 {task_id}: {e}")
            if task_id in self.tasks:
                self.tasks[task_id].status = TaskStatus.FAILED
                self.save_tasks()
    
    def _calculate_next_execution(self, task: CustomTask):
        """计算下一次执行时间"""
        try:
            # 统一处理时间格式
            if ' ' in task.execute_time:  # 完整日期时间格式
                time_str = task.execute_time.split(' ')[1]
                date_str = task.execute_time.split(' ')[0]
            else:  # 只有时间部分
                time_str = task.execute_time
                date_str = None
            
            hour, minute = map(int, time_str.split(':'))
            
            now = datetime.now()
            today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if task.task_type == TaskType.ONE_TIME:
                if date_str is None:
                    return None
                execute_datetime = datetime.strptime(task.execute_time, '%Y-%m-%d %H:%M')
                return execute_datetime.strftime('%Y-%m-%d %H:%M')
            
            # 重复任务计算
            if task.recurring_pattern == 'daily':
                next_run = today if today > now else today + timedelta(days=1)
            elif task.recurring_pattern == 'weekly':
                next_run = today + timedelta(days=7)
            elif task.recurring_pattern in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                weekday_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}
                target_day = weekday_map.get(task.recurring_pattern, 0)
                days_ahead = (target_day - now.weekday()) % 7
                if days_ahead == 0 and today <= now:
                    days_ahead = 7
                next_run = today + timedelta(days=days_ahead)
            elif task.recurring_pattern == 'monthly_date':
                if task.recurring_details:
                    day_of_month = int(json.loads(task.recurring_details))
                else:
                    day_of_month = 1
                    
                current_month = now.month
                current_year = now.year
                
                if now.day < day_of_month:
                    next_run = now.replace(day=day_of_month, hour=hour, minute=minute)
                else:
                    if current_month == 12:
                        next_month = 1
                        next_year = current_year + 1
                    else:
                        next_month = current_month + 1
                        next_year = current_year
                    
                    import calendar
                    last_day = calendar.monthrange(next_year, next_month)[1]
                    actual_day = min(day_of_month, last_day)
                    
                    next_run = datetime(next_year, next_month, actual_day, hour, minute)
            elif task.recurring_pattern == 'selected_dates':
                if task.recurring_details:
                    dates_data = json.loads(task.recurring_details)
                    if isinstance(dates_data, list) and dates_data:
                        future_dates = []
                        for date_str in dates_data:
                            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                            if date_obj >= now.date():
                                future_dates.append(date_obj)
                        
                        if future_dates:
                            next_date = min(future_dates)
                            next_run = datetime.combine(next_date, datetime.strptime(time_str, '%H:%M').time())
                        else:
                            return None
                    else:
                        return None
                else:
                    return None
            else:
                next_run = today + timedelta(days=1)
            
            return next_run.strftime('%Y-%m-%d %H:%M')
        except Exception as e:
            logger.error(f"计算下一次执行时间失败: {e}")
            return None
    
    def ensure_scheduler_running(self):
        """确保调度器正在运行并且任务已正确调度"""
        with self._scheduler_lock:
            # 检查是否有活跃任务但没有调度的情况
            active_task_count = sum(1 for task in self.tasks.values() if task.status == TaskStatus.ACTIVE)
            scheduled_job_count = len(schedule.jobs)
            
            logger.info(f"检查调度器状态 - 活跃任务数: {active_task_count}, 已调度任务数: {scheduled_job_count}")
            
            # 打印所有活跃任务的详细信息（仅在有差异时）
            if active_task_count != scheduled_job_count:
                logger.warning("活跃任务数与已调度任务数不匹配")
                for task in self.tasks.values():
                    if task.status == TaskStatus.ACTIVE:
                        is_scheduled = any(task.id in job.tags for job in schedule.jobs)
                        logger.info(f"任务 '{task.name}': 活跃={task.status == TaskStatus.ACTIVE}, 已调度={is_scheduled}")
            
            # 只有在真正需要时才重新调度
            if active_task_count > 0 and scheduled_job_count == 0:
                logger.warning("检测到所有任务未调度，正在重新调度所有任务")
                self._reschedule_all_tasks()
            elif active_task_count > scheduled_job_count:
                logger.warning(f"检测到部分任务未调度（活跃: {active_task_count}, 已调度: {scheduled_job_count}），正在重新调度所有任务")
                self._reschedule_all_tasks()
            else:
                logger.info("任务调度状态正常")
            
            # 确保后台线程在运行
            if not self.running or self.thread is None or not self.thread.is_alive():
                logger.warning("调度器线程未运行，正在启动...")
                self.running = True
                self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
                self.thread.start()
                logger.info("调度器线程已启动")
    
    def _reschedule_all_tasks(self):
        """重新调度所有任务"""
        schedule.clear()
        logger.info("已清除所有现有调度任务")
        
        active_tasks = 0
        for task in self.tasks.values():
            if task.status == TaskStatus.ACTIVE:
                self._schedule_task(task)
                active_tasks += 1
        
        logger.info(f"已重新调度 {active_tasks} 个活跃任务")
    
    def start_scheduler(self):
        """启动调度器"""
        with self._scheduler_lock:
            # 总是重新调度所有任务，确保状态同步
            self._reschedule_all_tasks()
            
            # 如果线程未运行，启动它
            if not self.running or self.thread is None or not self.thread.is_alive():
                self.running = True
                self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
                self.thread.start()
                logger.info("任务调度器后台线程已启动")
            else:
                logger.info("调度器线程已在运行")
    
    def stop_scheduler(self):
        """停止调度器"""
        self.running = False
        schedule.clear()
        logger.info("调度器已停止")
    
    def _run_scheduler(self):
        """运行调度器"""
        logger.info("调度器线程开始运行")
        last_check_time = datetime.now()
        
        while self.running:
            try:
                # 每分钟检查一次调度状态
                if (datetime.now() - last_check_time).total_seconds() > 60:
                    self.ensure_scheduler_running()
                    last_check_time = datetime.now()
                    
                    # 记录当前所有调度任务
                    if schedule.jobs:
                        logger.info("当前调度的任务:")
                        for job in schedule.jobs:
                            logger.info(f"- {job.tags}: 下次执行 {job.next_run}")
                    else:
                        logger.info("没有调度的任务")
                
                # 执行待处理任务
                schedule.run_pending()
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"调度器运行出错: {e}", exc_info=True)
                time.sleep(5)
    
    def get_scheduler_status(self):
        """获取调度器状态"""
        return {
            'running': self.running,
            'thread_alive': self.thread.is_alive() if self.thread else False,
            'active_tasks': sum(1 for t in self.tasks.values() if t.status == TaskStatus.ACTIVE),
            'scheduled_jobs': len(schedule.jobs),
            'next_run': schedule.next_run().strftime('%Y-%m-%d %H:%M:%S') if schedule.jobs else None
        }

def get_database_connection():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def get_departments():
    """获取所有部门列表"""
    conn = get_database_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT department FROM kbk_ic_manager WHERE department IS NOT NULL ORDER BY department")
    departments = [row[0] for row in cursor.fetchall()]
    conn.close()
    return departments

def get_users_by_department(department=None):
    """根据部门获取用户列表"""
    conn = get_database_connection()
    cursor = conn.cursor()
    
    if department:
        cursor.execute("SELECT user, card, status FROM kbk_ic_manager WHERE department = ? ORDER BY user", (department,))
    else:
        cursor.execute("SELECT user, card, status FROM kbk_ic_manager ORDER BY user")
    
    users = cursor.fetchall()
    conn.close()
    return users

def update_user_status(users, status):
    """批量更新用户状态"""
    if not users:
        return 0
    
    conn = get_database_connection()
    cursor = conn.cursor()
    
    placeholders = ','.join(['?' for _ in users])
    sql = f"""
        UPDATE kbk_ic_manager 
        SET status = ?, last_updated = ? 
        WHERE user IN ({placeholders})
    """
    
    # 使用格式化的时间戳
    params = [status, get_formatted_timestamp()] + list(users)
    cursor.execute(sql, params)
    
    affected_rows = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected_rows

def get_user_statistics():
    """获取用户统计信息"""
    conn = get_database_connection()
    cursor = conn.cursor()
    
    # 总用户数
    cursor.execute("SELECT COUNT(*) FROM kbk_ic_manager")
    total_users = cursor.fetchone()[0]
    
    # 活跃用户数（status=1）
    cursor.execute("SELECT COUNT(*) FROM kbk_ic_manager WHERE status = 1")
    active_users = cursor.fetchone()[0]
    
    # 按部门统计
    cursor.execute("""
        SELECT department, 
               COUNT(*) as total,
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as active
        FROM kbk_ic_manager 
        GROUP BY department 
        ORDER BY department
    """)
    
    dept_stats = cursor.fetchall()
    conn.close()
    
    return {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': total_users - active_users,
        'department_stats': dept_stats
    }

# 初始化任务调度器 - 使用缓存确保单例模式
@st.cache_resource
def get_task_scheduler():
    """获取全局任务调度器实例"""
    scheduler = TaskScheduler()
    scheduler.start_scheduler()
    logger.info("任务调度器已初始化并启动")
    return scheduler

# 获取全局任务调度器实例
if 'task_scheduler' not in st.session_state:
    st.session_state.task_scheduler = get_task_scheduler()

def main():
    st.title("🏢 IC卡管理系统")
    
    # 侧边栏导航
    st.sidebar.title("导航菜单")
    page = st.sidebar.selectbox(
        "选择功能",
        ["📊 数据概览", "👥 批量管理", "⚙️ 自定义任务", "📋 任务监控"]
    )
    
    if page == "📊 数据概览":
        show_overview()
    elif page == "👥 批量管理":
        show_batch_management()
    elif page == "⚙️ 自定义任务":
        show_custom_tasks()
    elif page == "📋 任务监控":
        show_task_monitoring()

def show_overview():
    """显示数据概览页面"""
    st.header("📊 数据概览")
    
    # 获取统计信息
    stats = get_user_statistics()
    
    # 显示总体统计
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("总用户数", stats['total_users'])
    
    with col2:
        st.metric("活跃用户", stats['active_users'])
    
    with col3:
        st.metric("非活跃用户", stats['inactive_users'])
    
    # 部门统计表格
    st.subheader("部门统计")
    if stats['department_stats']:
        df = pd.DataFrame(stats['department_stats'], columns=['部门', '总数', '活跃数'])
        df['非活跃数'] = df['总数'] - df['活跃数']
        df['活跃率'] = (df['活跃数'] / df['总数'] * 100).round(2).astype(str) + '%'
        st.dataframe(df, use_container_width=True)
    else:
        st.info("暂无数据")

def show_batch_management():
    """显示批量管理页面"""
    st.header("👥 批量管理")
    
    # 筛选条件
    col1, col2 = st.columns(2)
    
    with col1:
        departments = get_departments()
        selected_dept = st.selectbox(
            "选择部门",
            ["全部"] + departments,
            key="batch_dept_filter"
        )
    
    with col2:
        target_status = st.selectbox(
            "目标状态",
            [(0, "非活跃 (0)"), (1, "活跃 (1)")],
            format_func=lambda x: x[1],
            key="batch_target_status"
        )[0]
    
    # 获取用户列表
    dept_filter = None if selected_dept == "全部" else selected_dept
    users = get_users_by_department(dept_filter)
    
    if users:
        st.subheader(f"用户列表 ({len(users)} 人)")
        
        # 创建DataFrame
        df = pd.DataFrame(users, columns=['用户', '卡号', '当前状态'])
        df['状态显示'] = df['当前状态'].map({0: '非活跃', 1: '活跃'})
        df['选择'] = False
        
        # 全选/取消全选
        col1, col2, col3 = st.columns([1, 1, 4])
        
        with col1:
            if st.button("全选", key="select_all"):
                st.session_state.selected_users = df['用户'].tolist()
        
        with col2:
            if st.button("取消全选", key="deselect_all"):
                st.session_state.selected_users = []
        
        # 初始化选中用户列表
        if 'selected_users' not in st.session_state:
            st.session_state.selected_users = []
        
        # 用户选择
        selected_users = st.multiselect(
            "选择要修改的用户",
            df['用户'].tolist(),
            default=st.session_state.selected_users,
            key="user_multiselect"
        )
        
        st.session_state.selected_users = selected_users
        
        # 显示选中的用户
        if selected_users:
            st.info(f"已选择 {len(selected_users)} 个用户")
            
            # 确认修改
            if st.button(f"确认将选中用户状态设置为: {target_status}", type="primary"):
                affected_rows = update_user_status(selected_users, target_status)
                st.success(f"成功更新 {affected_rows} 个用户的状态")
                st.rerun()
        
        # 显示用户表格
        display_df = df[['用户', '卡号', '状态显示']].copy()
        st.dataframe(display_df, use_container_width=True)
        
    else:
        st.info("没有找到用户数据")

def show_custom_tasks():
    """显示自定义任务页面"""
    st.header("⚙️ 自定义任务")
    
    # 显示调度器状态
    col1, col2 = st.columns([3, 1])
    with col1:
        scheduled_jobs = len(schedule.jobs)
        active_tasks = sum(1 for task in st.session_state.task_scheduler.tasks.values() if task.status == TaskStatus.ACTIVE)
        if active_tasks > scheduled_jobs:
            st.warning(f"有 {active_tasks} 个活跃任务，但只有 {scheduled_jobs} 个已调度")
        else:
            st.info(f"活跃任务: {active_tasks} | 已调度: {scheduled_jobs}")
    with col2:
        if st.button("🔄 刷新调度器", help="确保所有任务被正确调度"):
            st.session_state.task_scheduler.ensure_scheduler_running()
            st.success("已刷新")
            st.rerun()
    
    # 任务操作选项卡
    tab1, tab2 = st.tabs(["创建任务", "管理任务"])
    
    with tab1:
        show_create_task()
    
    with tab2:
        show_manage_tasks()

def show_create_task():
    """显示创建任务界面"""
    st.subheader("创建新任务")
    
    # 初始化session state用于存储任务类型
    if 'task_type' not in st.session_state:
        st.session_state.task_type = TaskType.ONE_TIME
    
    with st.form("create_task_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            task_name = st.text_input("任务名称*", placeholder="例如：夜间禁用所有卡片")
            task_description = st.text_area("任务描述", placeholder="详细描述任务的目的和作用")
            
            # 将任务类型选择移到表单内
            task_type = st.selectbox(
                "任务类型*",
                [(TaskType.ONE_TIME, "一次性任务"), (TaskType.RECURRING, "重复任务")],
                format_func=lambda x: x[1],
                index=0 if st.session_state.task_type == TaskType.ONE_TIME else 1,
                key="task_type_select"
            )[0]
            # 更新session state中的任务类型
            st.session_state.task_type = task_type
        
        with col2:
            target_status = st.selectbox(
                "目标状态*",
                [(0, "设置为非活跃 (0)"), (1, "设置为活跃 (1)")],
                format_func=lambda x: x[1]
            )[0]
            
            departments = get_departments()
            department_filter = st.selectbox(
                "部门筛选",
                ["全部"] + departments
            )
        
        # 用户选择界面 - 类似批量管理界面
        st.subheader("用户选择")
        
        # 获取用户列表
        dept_filter = None if department_filter == "全部" else department_filter
        users = get_users_by_department(dept_filter)
        
        if users:
            # 创建DataFrame
            df = pd.DataFrame(users, columns=['用户', '卡号', '当前状态'])
            df['状态显示'] = df['当前状态'].map({0: '非活跃', 1: '活跃'})
            
            # 全选/取消全选
            col1, col2, col3 = st.columns([1, 1, 4])
            
            with col1:
                select_all = st.form_submit_button("全选")
            
            with col2:
                deselect_all = st.form_submit_button("取消全选")
            
            # 初始化选中用户列表
            if 'task_selected_users' not in st.session_state:
                st.session_state.task_selected_users = []
            
            # 处理全选/取消全选
            if select_all:
                st.session_state.task_selected_users = df['用户'].tolist()
            elif deselect_all:
                st.session_state.task_selected_users = []
            
            # 用户选择
            selected_users = st.multiselect(
                "选择要应用任务的用户",
                df['用户'].tolist(),
                default=st.session_state.task_selected_users,
                key="task_user_multiselect"
            )
            
            st.session_state.task_selected_users = selected_users
            
            if selected_users:
                st.info(f"已选择 {len(selected_users)} 个用户")
        else:
            st.warning("没有找到用户数据")
            selected_users = []
        
        # 时间设置
        st.subheader("执行时间设置*")
        
        # 根据session state中的任务类型显示不同的UI
        if st.session_state.task_type == TaskType.ONE_TIME:
            execute_date = st.date_input("执行日期*", min_value=datetime.now().date())
            execute_time_str = st.text_input(
                "执行时间* (HH:MM)", 
                placeholder="例如：23:30",
                help="请输入24小时制时间，格式为 HH:MM"
            )
            
            # 验证时间格式
            time_valid = True
            if execute_time_str:
                if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', execute_time_str):
                    st.error("时间格式不正确，请使用 HH:MM 格式（例如：23:30）")
                    time_valid = False
            
            execute_datetime = f"{execute_date} {execute_time_str}" if execute_time_str else ""
            recurring_pattern = None
            recurring_details = None
        else:
            execute_time_str = st.text_input(
                "执行时间* (HH:MM)", 
                placeholder="例如：23:30",
                help="请输入24小时制时间，格式为 HH:MM"
            )
            
            # 验证时间格式
            time_valid = True
            if execute_time_str:
                if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', execute_time_str):
                    st.error("时间格式不正确，请使用 HH:MM 格式（例如：23:30）")
                    time_valid = False
            
            # 扩展的重复模式选择
            recurring_pattern = st.selectbox(
                "重复模式*",
                [
                    "daily", "weekly", "monthly",
                    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                    "monthly_date", "selected_dates"
                ],
                format_func=lambda x: {
                    "daily": "每日", "weekly": "每周", "monthly": "每月",
                    "monday": "每周一", "tuesday": "每周二", "wednesday": "每周三", 
                    "thursday": "每周四", "friday": "每周五", "saturday": "每周六", "sunday": "每周日",
                    "monthly_date": "每月特定日期", "selected_dates": "选定日期"
                }[x]
            )
            
            # 根据重复模式显示额外选项
            recurring_details = None
            if recurring_pattern == "monthly_date":
                recurring_details = st.selectbox(
                    "选择月内日期",
                    list(range(1, 32)),
                    format_func=lambda x: f"每月{x}日"
                )
            elif recurring_pattern == "selected_dates":
                recurring_details = st.multiselect(
                    "选择具体日期",
                    [
                        "2025-01-01", "2025-01-15", "2025-02-01", "2025-02-15",
                        "2025-03-01", "2025-03-15", "2025-04-01", "2025-04-15",
                        "2025-05-01", "2025-05-15", "2025-06-01", "2025-06-15",
                        "2025-07-01", "2025-07-15", "2025-08-01", "2025-08-15",
                        "2025-09-01", "2025-09-15", "2025-10-01", "2025-10-15",
                        "2025-11-01", "2025-11-15", "2025-12-01", "2025-12-15"
                    ]
                )
                # 也可以添加自定义日期输入
                custom_date = st.date_input("添加自定义日期", value=None)
                if custom_date:
                    if recurring_details is None:
                        recurring_details = []
                    if str(custom_date) not in recurring_details:
                        recurring_details.append(str(custom_date))
            
            execute_datetime = execute_time_str
        
        submitted = st.form_submit_button("创建任务", type="primary")
        
        if submitted:
            if not task_name:
                st.error("请输入任务名称")
            elif not execute_time_str:
                st.error("请输入执行时间")
            elif not time_valid:
                st.error("请输入正确的时间格式")
            elif not selected_users and department_filter == "全部":
                st.error("请选择要应用任务的用户或指定部门")
            else:
                # 创建任务
                task = CustomTask(
                    id=str(uuid.uuid4()),
                    name=task_name,
                    description=task_description,
                    task_type=st.session_state.task_type,  # 使用session state中的任务类型
                    status=TaskStatus.ACTIVE,
                    target_status=target_status,
                    department_filter=department_filter if department_filter != "全部" else "",
                    user_filter=','.join(selected_users) if selected_users else "",  # 存储选中的用户列表
                    execute_time=execute_datetime,
                    recurring_pattern=(recurring_pattern if st.session_state.task_type == TaskType.RECURRING and recurring_pattern else "daily") if st.session_state.task_type == TaskType.RECURRING else "",  # 修正：确保recurring任务类型时recurring_pattern不能为空
                    created_at=get_formatted_timestamp(),
                    recurring_details=json.dumps(recurring_details) if recurring_details else None
                )
                
                logger.info(f"创建任务: {task.name}, task_type={task.task_type.value}, recurring_pattern={task.recurring_pattern}, execute_time={task.execute_time}")
                
                st.session_state.task_scheduler.add_task(task)
                st.success(f"✅ 任务 '{task_name}' 创建成功并已添加到调度器！")
                
                # 显示任务调度信息
                if task.task_type == TaskType.ONE_TIME:
                    st.info(f"📅 任务将在 {task.execute_time} 执行")
                else:
                    pattern_map = {
                        "daily": "每日", "weekly": "每周", "monthly": "每月",
                        "monday": "每周一", "tuesday": "每周二", "wednesday": "每周三",
                        "thursday": "每周四", "friday": "每周五", "saturday": "每周六", "sunday": "每周日",
                        "monthly_date": "每月特定日期", "selected_dates": "选定日期"
                    }
                    st.info(f"🔄 任务将{pattern_map.get(task.recurring_pattern, task.recurring_pattern)}在 {task.execute_time} 执行")
                # 清理session state
                if 'task_selected_users' in st.session_state:
                    del st.session_state.task_selected_users
                st.rerun()

def show_manage_tasks():
    """显示任务管理界面"""
    st.subheader("任务管理")
    
    # 调度器状态和手动刷新按钮
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        scheduled_jobs = len(schedule.jobs)
        active_tasks = sum(1 for task in st.session_state.task_scheduler.tasks.values() if task.status == TaskStatus.ACTIVE)
        st.info(f"活跃任务: {active_tasks} | 已调度: {scheduled_jobs}")
    
    with col2:
        if schedule.jobs:
            next_run = schedule.next_run()
            if next_run:
                st.info(f"下次执行: {next_run.strftime('%H:%M:%S')}")
        else:
            st.warning("无调度任务")
    
    with col3:
        if st.button("🔄 刷新调度器", help="手动刷新调度器，确保所有活跃任务被正确调度"):
            st.session_state.task_scheduler.ensure_scheduler_running()
            st.success("调度器已刷新")
            st.rerun()
    
    tasks = st.session_state.task_scheduler.tasks
    
    if not tasks:
        st.info("暂无任务")
        return
    
    # 任务列表
    for task_id, task in tasks.items():
        with st.expander(f"📋 {task.name} ({task.status.value})"):
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                st.write(f"**描述:** {task.description}")
                st.write(f"**类型:** {'一次性' if task.task_type == TaskType.ONE_TIME else '重复'}")
                st.write(f"**目标状态:** {task.target_status}")
                st.write(f"**部门筛选:** {task.department_filter or '全部'}")
                st.write(f"**用户筛选:** {task.user_filter or '全部'}")
                st.write(f"**执行时间:** {task.execute_time}")
                if task.recurring_pattern:
                    pattern_map = {
                        "daily": "每日", "weekly": "每周", "monthly": "每月",
                        "monday": "每周一", "tuesday": "每周二", "wednesday": "每周三",
                        "thursday": "每周四", "friday": "每周五", "saturday": "每周六", "sunday": "每周日",
                        "monthly_date": "每月特定日期", "selected_dates": "选定日期"
                    }
                    st.write(f"**重复模式:** {pattern_map.get(task.recurring_pattern, task.recurring_pattern)}")
                if task.recurring_details:
                    try:
                        details = json.loads(task.recurring_details)
                        st.write(f"**重复详情:** {details}")
                    except:
                        pass
                st.write(f"**创建时间:** {task.created_at}")
                if task.last_executed:
                    st.write(f"**上次执行:** {task.last_executed}")
                st.write(f"**执行次数:** {task.execution_count}")
                
                # 检查任务是否在调度器中
                task_scheduled = any(task_id in job.tags for job in schedule.jobs if job.tags)
                if task.status == TaskStatus.ACTIVE:
                    if task_scheduled:
                        st.success("✅ 任务已调度")
                    else:
                        st.error("❌ 任务未调度")
            
            with col2:
                if task.status == TaskStatus.ACTIVE:
                    if st.button("暂停", key=f"pause_{task_id}"):
                        st.session_state.task_scheduler.pause_task(task_id)
                        st.rerun()
                elif task.status == TaskStatus.PAUSED:
                    if st.button("恢复", key=f"resume_{task_id}"):
                        st.session_state.task_scheduler.resume_task(task_id)
                        st.rerun()
                
                if st.button("立即执行", key=f"execute_{task_id}"):
                    st.session_state.task_scheduler.execute_task_now(task_id)
                    st.success("任务已执行")
                    st.rerun()
            
            with col3:
                if st.button("删除", key=f"delete_{task_id}", type="secondary"):
                    st.session_state.task_scheduler.delete_task(task_id)
                    st.success("任务已删除")
                    st.rerun()

def show_task_monitoring():
    """显示任务监控页面"""
    st.header("📋 任务监控")
    
    tasks = st.session_state.task_scheduler.tasks
    
    if not tasks:
        st.info("暂无任务")
        return
    
    # 显示调度器状态和控制按钮
    scheduler = st.session_state.task_scheduler
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.info(f"调度器状态: {'运行中' if scheduler.running else '已停止'}")
    with col2:
        scheduled_jobs = len(schedule.jobs)
        st.info(f"当前调度的任务数: {scheduled_jobs}")
    with col3:
        if schedule.jobs:
            next_run = schedule.next_run()
            if next_run:
                st.info(f"下次执行: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.info("无待执行任务")
    with col4:
        if st.button("🔄 刷新调度器", type="primary", help="立即检查并刷新所有任务的调度状态"):
            scheduler.ensure_scheduler_running()
            st.success("调度器已刷新")
            st.rerun()
    
    # 显示当前调度的任务详情
    if schedule.jobs:
        st.subheader("当前调度的任务")
        job_info = []
        for job in schedule.jobs:
            job_info.append({
                "标签": ', '.join(job.tags) if job.tags else "无标签",
                "下次运行时间": job.next_run.strftime('%Y-%m-%d %H:%M:%S') if job.next_run else "未知",
                "时间间隔": str(job.interval) if hasattr(job, 'interval') else "未知",
                "时间单位": str(job.unit) if hasattr(job, 'unit') else "未知"
            })
        if job_info:
            st.dataframe(pd.DataFrame(job_info), use_container_width=True)
        
    # 如果调度器没有任务但有活跃任务，显示警告
    active_tasks = sum(1 for task in tasks.values() if task.status == TaskStatus.ACTIVE)
    if scheduled_jobs == 0 and active_tasks > 0:
        st.warning(f"警告：有 {active_tasks} 个活跃任务，但调度器中没有任务。请点击上方的'刷新调度器'按钮。")
    elif scheduled_jobs < active_tasks:
        st.warning(f"警告：有 {active_tasks} 个活跃任务，但只有 {scheduled_jobs} 个已调度。请点击上方的'刷新调度器'按钮。")
    
    # 任务状态统计
    status_counts = {}
    for task in tasks.values():
        status = task.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("总任务数", len(tasks))
    
    with col2:
        st.metric("活跃任务", status_counts.get('active', 0))
    
    with col3:
        st.metric("暂停任务", status_counts.get('paused', 0))
    
    with col4:
        st.metric("已完成任务", status_counts.get('completed', 0))
    
    # 任务详情表格
    st.subheader("任务详情")
    
    # 计算下一次执行时间
    def calculate_next_execution(task):
        if task.status != TaskStatus.ACTIVE:
            return "任务未激活"
        
        try:
            if task.task_type == TaskType.ONE_TIME:
                execute_datetime = datetime.strptime(task.execute_time, '%Y-%m-%d %H:%M')
                if execute_datetime > datetime.now():
                    return execute_datetime.strftime('%Y-%m-%d %H:%M')
                else:
                    return "已过期"
            else:
                # 重复任务，根据模式计算下一次执行时间
                time_str = task.execute_time.split(' ')[1] if ' ' in task.execute_time else task.execute_time
                hour, minute = map(int, time_str.split(':'))
                
                now = datetime.now()
                today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if task.recurring_pattern == 'daily':
                    next_run = today if today > now else today + timedelta(days=1)
                elif task.recurring_pattern == 'weekly':
                    days_ahead = 7 - now.weekday()
                    next_run = today + timedelta(days=days_ahead)
                elif task.recurring_pattern in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    weekday_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}
                    target_day = weekday_map.get(task.recurring_pattern, 0)
                    days_ahead = (target_day - now.weekday()) % 7
                    if days_ahead == 0 and today < now:
                        days_ahead = 7
                    next_run = today + timedelta(days=days_ahead)
                elif task.recurring_pattern == 'monthly_date':
                    try:
                        if task.recurring_details:
                            day_of_month = int(json.loads(task.recurring_details))
                        else:
                            day_of_month = 1
                        
                        # 计算下一个月的对应日期
                        current_month = now.month
                        current_year = now.year
                        
                        # 如果当前日期小于目标日期，使用当前月份
                        if now.day < day_of_month:
                            next_run = now.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
                        else:
                            # 否则使用下个月
                            if current_month == 12:
                                next_month = 1
                                next_year = current_year + 1
                            else:
                                next_month = current_month + 1
                                next_year = current_year
                            
                            # 处理月份天数问题
                            import calendar
                            last_day = calendar.monthrange(next_year, next_month)[1]
                            actual_day = min(day_of_month, last_day)
                            
                            next_run = datetime(next_year, next_month, actual_day, hour, minute)
                    except:
                        return "计算错误"
                elif task.recurring_pattern == 'selected_dates':
                    try:
                        if task.recurring_details:
                            dates_data = json.loads(task.recurring_details)
                            if isinstance(dates_data, list) and dates_data:
                                future_dates = []
                                for date_str in dates_data:
                                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                                    if date_obj >= now.date():
                                        future_dates.append(date_obj)
                                
                                if future_dates:
                                    next_date = min(future_dates)
                                    next_run = datetime.combine(next_date, datetime.strptime(time_str, '%H:%M').time())
                                else:
                                    return "无未来日期"
                            else:
                                return "无选定日期"
                        else:
                            return "无选定日期"
                    except:
                        return "计算错误"
                else:
                    return "未知模式"
                
                return next_run.strftime('%Y-%m-%d %H:%M')
        except Exception as e:
            return f"计算错误: {str(e)}"
    
    task_data = []
    for task in tasks.values():
        # 使用任务中已保存的下次执行时间，如果没有则计算
        if task.status == TaskStatus.ACTIVE:
            if task.next_execution:
                next_execution = task.next_execution
            else:
                next_execution = calculate_next_execution(task)
        else:
            next_execution = "未激活"
        
        # 检查任务是否在调度器中
        task_scheduled = any(task.id in job.tags for job in schedule.jobs if job.tags)
        
        task_data.append({
            '任务名称': task.name,
            '状态': task.status.value,
            '已调度': '✅' if task_scheduled else '❌',
            '类型': '一次性' if task.task_type == TaskType.ONE_TIME else '重复',
            '重复模式': task.recurring_pattern or 'N/A',
            '目标状态': task.target_status,
            '执行时间': task.execute_time,
            '执行次数': task.execution_count,
            '上次执行': task.last_executed or '未执行',
            '下次执行': next_execution,
            '创建时间': task.created_at
        })
    
    if task_data:
        df = pd.DataFrame(task_data)
        st.dataframe(df, use_container_width=True)
    
    # 操作按钮
    st.subheader("操作")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("📊 刷新数据"):
            st.rerun()
    with col2:
        if st.button("🔄 重启调度器", type="secondary"):
            scheduler.stop_scheduler()
            scheduler.start_scheduler()
            st.success("调度器已重启")
            st.rerun()
    with col3:
        if st.button("▶️ 执行所有活跃任务", type="secondary"):
            executed = 0
            for task in tasks.values():
                if task.status == TaskStatus.ACTIVE:
                    scheduler.execute_task_now(task.id)
                    executed += 1
            if executed > 0:
                st.success(f"已执行 {executed} 个活跃任务")
                st.rerun()
            else:
                st.info("没有活跃任务")
    with col4:
        if st.button("📝 查看日志", type="secondary"):
            st.session_state.show_logs = not st.session_state.get('show_logs', False)
            
    # 显示最近的日志（如果启用）
    if st.session_state.get('show_logs', False):
        st.subheader("最近日志")
        st.text_area("日志输出", value="查看控制台输出以获取详细日志", height=200)

if __name__ == "__main__":
    main()