import streamlit as st

# --- Streamlit UI Page Config (MUST BE FIRST STREAMLIT COMMAND) ---
st.set_page_config(layout="wide")

import sqlite3
import pandas as pd
import schedule
import time
import threading
import json # Added for JSON operations
from datetime import datetime, time as dt_time, timezone, timedelta # Added timezone and timedelta

DB_PATH = './ic_manager.db'
TABLE_NAME = 'kbk_ic_manager'
DISPATCH_SERVER_JSON_PATH = 'dispatch_server.json' # Path for storing scheduled tasks

# --- Database Functions ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_departments(include_all=False):
    conn = get_db_connection()
    try:
        departments = pd.read_sql_query(f'SELECT DISTINCT department FROM {TABLE_NAME} WHERE department IS NOT NULL AND department != "" ORDER BY department', conn)['department'].tolist()
        if include_all:
            departments.insert(0, "(所有部门)")
    except Exception as e:
        st.error(f"Error fetching departments: {e}")
        departments = []
    finally:
        conn.close()
    return departments

def get_users_by_department(department):
    if not department or department == "(选择一个部门)":
        return []
    conn = get_db_connection()
    try:
        if department == "(所有部门)":
            users = pd.read_sql_query(f'SELECT DISTINCT user FROM {TABLE_NAME} ORDER BY user', conn)['user'].tolist()
        else:
            users = pd.read_sql_query(f'SELECT DISTINCT user FROM {TABLE_NAME} WHERE department = ? ORDER BY user', conn, params=(department,))['user'].tolist()
    except Exception as e:
        st.error(f"Error fetching users for department '{department}': {e}")
        users = []
    finally:
        conn.close()
    return users

def update_user_status(users_to_update, new_status):
    if not users_to_update:
        st.warning("No users selected to update.")
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        placeholders = ', '.join(['?'] * len(users_to_update))
        # Get current UTC+10 time for last_updated
        utc_plus_10_time = datetime.now(timezone(timedelta(hours=10))).strftime('%Y-%m-%d %H:%M:%S')
        sql = f"UPDATE {TABLE_NAME} SET status = ?, last_updated = ? WHERE user IN ({placeholders})"
        # Parameters: new_status, utc_plus_10_time, followed by all users in users_to_update
        params = [new_status, utc_plus_10_time] + users_to_update
        cursor.execute(sql, params)
        conn.commit()
        st.success(f"Successfully updated status to {new_status} and last_updated to {utc_plus_10_time} for {len(users_to_update)} users: {', '.join(users_to_update)}")
        return True
    except Exception as e:
        st.error(f"Error updating user status: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# --- Scheduling Logic ---
def job_to_schedule(users_to_update, new_status, job_id):
    print(f"[{datetime.now()}] Running job {job_id}: Setting status to {new_status} for users: {users_to_update}")
    update_user_status(users_to_update, new_status)
    # Optional: Remove job if it's a one-time task or meant to run only once then be re-scheduled manually
    # For recurring jobs, this is not needed unless you want to manage their lifecycle more dynamically.

# --- Persistence Functions for Scheduled Jobs ---
def load_scheduled_jobs():
    """Loads scheduled jobs from the JSON file and re-schedules them."""
    jobs_to_load = []
    try:
        with open(DISPATCH_SERVER_JSON_PATH, 'r') as f:
            jobs_to_load = json.load(f)
    except FileNotFoundError:
        st.info(f"{DISPATCH_SERVER_JSON_PATH} not found. Starting with no pre-loaded scheduled tasks.")
        return [] # No file, no jobs to load
    except json.JSONDecodeError:
        st.error(f"Error decoding JSON from {DISPATCH_SERVER_JSON_PATH}. Please check the file format.")
        return [] # Corrupted file
    except Exception as e:
        st.error(f"An unexpected error occurred while loading jobs: {e}")
        return []

    loaded_job_infos = []
    for job_data in jobs_to_load:
        try:
            # Reconstruct the schedule
            parsed_time_str = job_data['time'] # HH:MM format
            current_job = None
            schedule_details_reloaded = f"于 {parsed_time_str}"

            if job_data['type'] == "每日":
                current_job = schedule.every().day.at(parsed_time_str)
                schedule_details_reloaded = f"每日 {schedule_details_reloaded}"
            elif job_data['type'] == "每周" and job_data.get('day_of_week'):
                days_map_inv = {v: k for k, v in {"周一": "monday", "周二": "tuesday", "周三": "wednesday", "周四": "thursday", "周五": "friday", "周六": "saturday", "周日": "sunday"}.items()}
                day_attr_name = days_map_inv.get(job_data['day_of_week_internal']) # Use internal day name
                if day_attr_name:
                    day_attr = getattr(schedule.every(), day_attr_name)
                    current_job = day_attr.at(parsed_time_str)
                    schedule_details_reloaded = f"每周{job_data['day_of_week']} {schedule_details_reloaded}"
            
            if current_job:
                current_job.do(job_to_schedule, users_to_update=list(job_data['users']), new_status=job_data['status_to_set'], job_id=job_data['id']).tag(job_data['id'])
                job_info_reloaded = {
                    "id": job_data['id'],
                    "description": job_data['description'],
                    "schedule": schedule_details_reloaded, # Use re-constructed schedule string
                    "users": list(job_data['users']),
                    "status_to_set": job_data['status_to_set'],
                    "type": job_data['type'],
                    "day_of_week": job_data.get('day_of_week'),
                    "day_of_week_internal": job_data.get('day_of_week_internal'), # Store internal day name
                    "time": parsed_time_str
                }
                loaded_job_infos.append(job_info_reloaded)
            else:
                st.warning(f"Could not re-schedule job ID {job_data['id']} due to missing schedule type/day.")
        except Exception as e:
            st.error(f"Error re-scheduling job ID {job_data.get('id', 'N/A')}: {e}")
    return loaded_job_infos

def save_scheduled_jobs():
    """Saves the current list of scheduled jobs to the JSON file."""
    try:
        with open(DISPATCH_SERVER_JSON_PATH, 'w') as f:
            json.dump(st.session_state.scheduled_jobs_info, f, indent=4, ensure_ascii=False)
        # st.toast("Scheduled jobs saved.") # Optional: provide feedback
    except Exception as e:
        st.error(f"Error saving scheduled jobs to {DISPATCH_SERVER_JSON_PATH}: {e}")

# Store scheduled jobs in session state to persist them across reruns
if 'scheduled_jobs_info' not in st.session_state:
    st.session_state.scheduled_jobs_info = load_scheduled_jobs() # Load jobs on first run/session start
    if not st.session_state.scheduled_jobs_info: # If loading returned empty (e.g. no file, error), initialize as empty list
        st.session_state.scheduled_jobs_info = []

# Note: job_to_schedule is now defined before load_scheduled_jobs to resolve NameError
# def job_to_schedule(users_to_update, new_status, job_id): # This line is now removed as it's defined earlier

# The following block was a duplicated and misplaced part of job_to_schedule, causing NameError.
# It has been removed.
#    print(f"[{datetime.now()}] Running job {job_id}: Setting status to {new_status} for users: {users_to_update}")
#    update_user_status(users_to_update, new_status)
#    # Optional: Remove job if it's a one-time task or meant to run only once then be re-scheduled manually
#    # For recurring jobs, this is not needed unless you want to manage their lifecycle more dynamically.

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Start scheduler in a separate thread
# This ensures it runs in the background without blocking the Streamlit app
# Only start it once
if 'scheduler_thread_started' not in st.session_state:
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    st.session_state.scheduler_thread_started = True

# --- Streamlit UI ---
# st.set_page_config(layout="wide") # Moved to the top of the script
st.title("任务调度器 - 用户状态管理")

# --- Manual Status Update Section ---
st.header("手动更新用户状态")

manual_departments_list = get_departments(include_all=True)
if not manual_departments_list:
    st.warning("No departments found in the database. Please check the database connection and data.")
else:
    manual_selected_department = st.selectbox("选择部门 (手动):", ["(选择一个部门)"] + manual_departments_list, key="manual_dept")

    manual_users_in_department = []
    if manual_selected_department and manual_selected_department != "(选择一个部门)":
        manual_users_in_department = get_users_by_department(manual_selected_department)
        if not manual_users_in_department and manual_selected_department == "(所有部门)": # Handle case where 'All Departments' might return empty if DB is empty
             manual_users_in_department = get_users_by_department("(所有部门)") # Re-fetch all users explicitly
    
    if manual_users_in_department:
        st.write(f"部门 '{manual_selected_department}'下的用户:")
        
        col1_manual, col2_manual = st.columns(2)
        with col1_manual:
            if st.button("全选 (手动)", key="manual_select_all"):
                st.session_state.manual_selected_users = manual_users_in_department
        with col2_manual:
            if st.button("取消全选 (手动)", key="manual_deselect_all"):
                st.session_state.manual_selected_users = []

        manual_selected_users = st.multiselect(
            "选择用户 (手动):", 
            manual_users_in_department, 
            default=st.session_state.get('manual_selected_users', []),
            key="manual_user_select"
        )
        st.session_state.manual_selected_users = manual_selected_users # Keep session state updated

        col_set0, col_set1 = st.columns(2)
        with col_set0:
            if st.button("将选中用户状态置为 0", key="manual_set_0"):
                if manual_selected_users:
                    update_user_status(manual_selected_users, 0)
                else:
                    st.warning("请先选择用户。")
        with col_set1:
            if st.button("将选中用户状态置为 1", key="manual_set_1"):
                if manual_selected_users:
                    update_user_status(manual_selected_users, 1)
                else:
                    st.warning("请先选择用户。")
    elif manual_selected_department and manual_selected_department != "(选择一个部门)":
        st.info(f"部门 '{manual_selected_department}' 下没有找到用户。")

st.divider()

# --- Scheduled Task Section ---
st.header("计划任务 - 更新用户状态")

scheduled_departments_list = get_departments(include_all=True)
if not scheduled_departments_list:
    st.warning("无法加载部门用于计划任务。")
else:
    scheduled_selected_department = st.selectbox("选择部门 (计划):", ["(选择一个部门)"] + scheduled_departments_list, key="sched_dept")

    scheduled_users_in_department = []
    if scheduled_selected_department and scheduled_selected_department != "(选择一个部门)":
        scheduled_users_in_department = get_users_by_department(scheduled_selected_department)
        if not scheduled_users_in_department and scheduled_selected_department == "(所有部门)": # Handle case where 'All Departments' might return empty if DB is empty
            scheduled_users_in_department = get_users_by_department("(所有部门)") # Re-fetch all users explicitly

    if scheduled_users_in_department:
        st.write(f"部门 '{scheduled_selected_department}'下的用户 (计划任务):")
        col1_sched, col2_sched = st.columns(2)
        with col1_sched:
            if st.button("全选 (计划)", key="sched_select_all"):
                st.session_state.sched_selected_users = scheduled_users_in_department
        with col2_sched:
            if st.button("取消全选 (计划)", key="sched_deselect_all"):
                st.session_state.sched_selected_users = []
        
        sched_selected_users = st.multiselect(
            "选择用户 (计划):", 
            scheduled_users_in_department, 
            default=st.session_state.get('sched_selected_users', []),
            key="sched_user_select"
        )
        st.session_state.sched_selected_users = sched_selected_users

        if sched_selected_users:
            task_status_to_set = st.radio("设置状态为:", (0, 1), key="sched_status_val", horizontal=True)
            
            schedule_type = st.selectbox("选择计划类型:", ["每日", "每周"], key="sched_type")
            
            selected_day_of_week = None
            if schedule_type == "每周":
                days_map = {"周一": "monday", "周二": "tuesday", "周三": "wednesday", "周四": "thursday", "周五": "friday", "周六": "saturday", "周日": "sunday"}
                selected_day_display = st.selectbox("选择星期几:", list(days_map.keys()), key="sched_day_of_week")
                selected_day_of_week = days_map[selected_day_display]
            
            schedule_time_str = st.text_input("输入执行时间 (HH:MM 格式):", "09:00", key="sched_time_text")
            
            if st.button("创建计划任务", key="create_schedule_task"):
                if not sched_selected_users:
                    st.warning("请选择要执行计划任务的用户。")
                else:
                    try:
                        parsed_time = datetime.strptime(schedule_time_str, "%H:%M").time()
                    except ValueError:
                        st.error("时间格式无效，请输入 HH:MM 格式的时间，例如 09:30 或 17:00。")
                        st.stop() # Stop execution if time is invalid

                    job_id = f"job_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                    task_description = f"将用户 {', '.join(sched_selected_users)} 的状态设置为 {task_status_to_set}"
                    schedule_details = f"于 {parsed_time.strftime('%H:%M')}"

                    current_job = None
                    schedule_time_for_lib = parsed_time.strftime("%H:%M") # schedule library expects HH:MM string

                    if schedule_type == "每日":
                        current_job = schedule.every().day.at(schedule_time_for_lib)
                        schedule_details = f"每日 {schedule_details}"
                    elif schedule_type == "每周" and selected_day_of_week:
                        day_attr = getattr(schedule.every(), selected_day_of_week)
                        current_job = day_attr.at(schedule_time_for_lib)
                        schedule_details = f"每周{selected_day_display} {schedule_details}"
                    
                    if current_job:
                        current_job.do(job_to_schedule, users_to_update=list(sched_selected_users), new_status=task_status_to_set, job_id=job_id).tag(job_id)
                        
                        job_info_to_save = {
                            "id": job_id,
                            "description": task_description,
                            "schedule": schedule_details, # This is for display, actual scheduling done above
                            "users": list(sched_selected_users),
                            "status_to_set": task_status_to_set,
                            "type": schedule_type,
                            "day_of_week": selected_day_display if selected_day_of_week else None,
                            "day_of_week_internal": selected_day_of_week, # Store the internal schedule library day name
                            "time": parsed_time.strftime('%H:%M')
                        }
                        st.session_state.scheduled_jobs_info.append(job_info_to_save)
                        save_scheduled_jobs() # Save after adding a new job
                        st.success(f"计划任务已创建: {task_description} {schedule_details}")
                    else:
                        st.error("无法创建计划任务，请检查配置。")
    elif scheduled_selected_department and scheduled_selected_department != "(选择一个部门)":
        st.info(f"部门 '{scheduled_selected_department}' 下没有找到用户用于计划任务。")

st.divider()
st.header("当前计划的任务")
if not st.session_state.scheduled_jobs_info:
    st.info("当前没有计划中的任务。")
else:
    for i, job_info in enumerate(st.session_state.scheduled_jobs_info):
        cols = st.columns([0.1, 0.6, 0.2, 0.1])
        cols[0].write(f"#{i+1}")
        cols[1].write(f"**任务**: {job_info['description']}\n**计划**: {job_info['schedule']}")
        # cols[2].write(f"{job_info['id']}") # Display job_id for debugging or advanced management
        if cols[3].button("删除", key=f"del_job_{job_info['id']}"):
            schedule.clear(job_info['id']) # Remove from schedule library
            st.session_state.scheduled_jobs_info = [j for j in st.session_state.scheduled_jobs_info if j['id'] != job_info['id']]
            save_scheduled_jobs() # Save after deleting a job
            st.rerun()

# To run this Streamlit app: streamlit run dispatch_server.py