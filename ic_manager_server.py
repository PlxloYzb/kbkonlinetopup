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

class TaskScheduler:
    def __init__(self):
        self.tasks: Dict[str, CustomTask] = {}
        self.running = False
        self.thread = None
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
        self.tasks[task.id] = task
        self.save_tasks()
        self._schedule_task(task)
    
    def update_task(self, task: CustomTask):
        """更新任务"""
        self.tasks[task.id] = task
        self.save_tasks()
        # 重新调度任务
        schedule.clear(task.id)
        if task.status == TaskStatus.ACTIVE:
            self._schedule_task(task)
    
    def delete_task(self, task_id: str):
        """删除任务"""
        if task_id in self.tasks:
            schedule.clear(task_id)
            del self.tasks[task_id]
            self.save_tasks()
    
    def pause_task(self, task_id: str):
        """暂停任务"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.PAUSED
            schedule.clear(task_id)
            self.save_tasks()
    
    def resume_task(self, task_id: str):
        """恢复任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.ACTIVE
            self._schedule_task(task)
            self.save_tasks()
    
    def execute_task_now(self, task_id: str):
        """立即执行任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            self._execute_task(task)
    
    def _schedule_task(self, task: CustomTask):
        """调度任务"""
        if task.status != TaskStatus.ACTIVE:
            return
        
        try:
            if task.task_type == TaskType.ONE_TIME:
                # 一次性任务
                execute_datetime = datetime.strptime(task.execute_time, '%Y-%m-%d %H:%M')
                if execute_datetime > datetime.now():
                    schedule.every().day.at(execute_datetime.strftime('%H:%M')).do(
                        self._execute_task, task
                    ).tag(task.id)
            else:
                # 重复任务
                time_str = task.execute_time.split(' ')[1] if ' ' in task.execute_time else task.execute_time
                
                if task.recurring_pattern == 'daily':
                    schedule.every().day.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'weekly':
                    schedule.every().week.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'monthly':
                    # 每月执行（简化处理，每30天执行一次）
                    schedule.every(30).days.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'monday':
                    schedule.every().monday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'tuesday':
                    schedule.every().tuesday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'wednesday':
                    schedule.every().wednesday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'thursday':
                    schedule.every().thursday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'friday':
                    schedule.every().friday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'saturday':
                    schedule.every().saturday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'sunday':
                    schedule.every().sunday.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'monthly_date':
                    # 每月特定日期（简化处理，每30天执行一次）
                    schedule.every(30).days.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
                elif task.recurring_pattern == 'selected_dates':
                    # 选定日期（简化处理，每天检查是否应该执行）
                    schedule.every().day.at(time_str).do(
                        self._execute_task, task
                    ).tag(task.id)
        except Exception as e:
            logger.error(f"调度任务失败 {task.name}: {e}")
    
    def _execute_task(self, task: CustomTask):
        """执行任务"""
        try:
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
            
            update_params = [task.target_status, datetime.now().isoformat()] + params
            cursor.execute(update_sql, update_params)
            
            affected_rows = cursor.rowcount
            conn.commit()
            conn.close()
            
            # 更新任务状态
            task.last_executed = datetime.now().isoformat()
            task.execution_count += 1
            
            if task.task_type == TaskType.ONE_TIME:
                task.status = TaskStatus.COMPLETED
                schedule.clear(task.id)
            
            self.save_tasks()
            
            logger.info(f"任务执行完成: {task.name}, 影响行数: {affected_rows}")
            
        except Exception as e:
            logger.error(f"任务执行失败 {task.name}: {e}")
            task.status = TaskStatus.FAILED
            self.save_tasks()
    
    def start_scheduler(self):
        """启动调度器"""
        if not self.running:
            self.running = True
            # 重新调度所有活跃任务
            for task in self.tasks.values():
                if task.status == TaskStatus.ACTIVE:
                    self._schedule_task(task)
            
            self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self.thread.start()
    
    def stop_scheduler(self):
        """停止调度器"""
        self.running = False
        schedule.clear()
    
    def _run_scheduler(self):
        """运行调度器"""
        while self.running:
            schedule.run_pending()
            time.sleep(1)

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
    
    params = [status, datetime.now().isoformat()] + list(users)
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

# 初始化任务调度器
if 'task_scheduler' not in st.session_state:
    st.session_state.task_scheduler = TaskScheduler()
    st.session_state.task_scheduler.start_scheduler()

def main():
    st.set_page_config(
        page_title="IC卡管理系统",
        page_icon="🏢",
        layout="wide"
    )
    
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
    
    # 任务操作选项卡
    tab1, tab2 = st.tabs(["创建任务", "管理任务"])
    
    with tab1:
        show_create_task()
    
    with tab2:
        show_manage_tasks()

def show_create_task():
    """显示创建任务界面"""
    st.subheader("创建新任务")
    
    with st.form("create_task_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            task_name = st.text_input("任务名称", placeholder="例如：夜间禁用所有卡片")
            task_description = st.text_area("任务描述", placeholder="详细描述任务的目的和作用")
            task_type = st.selectbox(
                "任务类型",
                [(TaskType.ONE_TIME, "一次性任务"), (TaskType.RECURRING, "重复任务")],
                format_func=lambda x: x[1]
            )[0]
        
        with col2:
            target_status = st.selectbox(
                "目标状态",
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
        st.subheader("执行时间设置")
        
        # 验证时间格式的函数
        def validate_time_format(time_str):
            try:
                # 验证格式：HH:MM
                if len(time_str) != 5 or time_str[2] != ':':
                    return False
                hour, minute = time_str.split(':')
                hour = int(hour)
                minute = int(minute)
                return 0 <= hour <= 23 and 0 <= minute <= 59
            except:
                return False
        
        if task_type == TaskType.ONE_TIME:
            execute_date = st.date_input("执行日期")
            execute_time_str = st.text_input(
                "执行时间", 
                placeholder="格式：HH:MM (例如：10:17)",
                help="请输入24小时制时间，格式为 HH:MM"
            )
            
            # 验证时间格式
            time_valid = True
            if execute_time_str and not validate_time_format(execute_time_str):
                st.error("时间格式不正确，请使用 HH:MM 格式（例如：10:17）")
                time_valid = False
            
            execute_datetime = f"{execute_date} {execute_time_str}" if execute_time_str else ""
            recurring_pattern = None
            recurring_details = None
        else:
            execute_time_str = st.text_input(
                "执行时间", 
                placeholder="格式：HH:MM (例如：10:17)",
                help="请输入24小时制时间，格式为 HH:MM"
            )
            
            # 验证时间格式
            time_valid = True
            if execute_time_str and not validate_time_format(execute_time_str):
                st.error("时间格式不正确，请使用 HH:MM 格式（例如：10:17）")
                time_valid = False
            
            # 扩展的重复模式选择
            recurring_pattern = st.selectbox(
                "重复模式",
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
                    task_type=task_type,
                    status=TaskStatus.ACTIVE,
                    target_status=target_status,
                    department_filter=department_filter if department_filter != "全部" else "",
                    user_filter=','.join(selected_users) if selected_users else "",  # 存储选中的用户列表
                    execute_time=execute_datetime,
                    recurring_pattern=recurring_pattern,
                    created_at=datetime.now().isoformat(),
                    recurring_details=json.dumps(recurring_details) if recurring_details else None
                )
                
                st.session_state.task_scheduler.add_task(task)
                st.success(f"任务 '{task_name}' 创建成功！")
                st.rerun()

def show_manage_tasks():
    """显示任务管理界面"""
    st.subheader("任务管理")
    
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
    
    task_data = []
    for task in tasks.values():
        task_data.append({
            '任务名称': task.name,
            '状态': task.status.value,
            '类型': '一次性' if task.task_type == TaskType.ONE_TIME else '重复',
            '目标状态': task.target_status,
            '执行时间': task.execute_time,
            '执行次数': task.execution_count,
            '上次执行': task.last_executed or '未执行',
            '创建时间': task.created_at
        })
    
    if task_data:
        df = pd.DataFrame(task_data)
        st.dataframe(df, use_container_width=True)
    
    # 刷新按钮
    if st.button("刷新数据"):
        st.rerun()

if __name__ == "__main__":
    main()
