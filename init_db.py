#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sqlite3
import pandas as pd
from datetime import datetime

def create_database(db_path="test_database.db"):
    """创建SQLite数据库和表结构"""
    print(f"正在创建数据库: {db_path}")
    
    if os.path.exists(db_path):
        print(f"数据库文件已存在，删除旧文件")
        os.remove(db_path)
    
    # 连接数据库
    conn = sqlite3.connect(db_path)
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
    
    print("成功创建employees表")
    
    # 提交更改
    conn.commit()
    conn.close()
    
    return db_path

def insert_sample_data(db_path):
    """向数据库中添加示例数据"""
    print(f"正在添加示例数据到数据库: {db_path}")
    
    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 定义示例部门
    departments = ["技术部", "运维部", "安全部", "产品部", "客服部"]
    
    # 为每个部门创建示例员工
    employees_data = []
    
    # 技术部员工
    for i in range(1, 11):
        employees_data.append({
            "username": f"tech{i}",
            "name": f"技术员工{i}",
            "department": "技术部",
            "position": "工程师",
            "status": 0
        })
    
    # 运维部员工
    for i in range(1, 8):
        employees_data.append({
            "username": f"ops{i}",
            "name": f"运维员工{i}",
            "department": "运维部",
            "position": "运维工程师",
            "status": 0
        })
    
    # 安全部员工
    for i in range(1, 6):
        employees_data.append({
            "username": f"sec{i}",
            "name": f"安全员工{i}",
            "department": "安全部",
            "position": "安全工程师",
            "status": 0
        })
    
    # 产品部员工
    for i in range(1, 4):
        employees_data.append({
            "username": f"prod{i}",
            "name": f"产品员工{i}",
            "department": "产品部",
            "position": "产品经理",
            "status": 0
        })
    
    # 客服部员工
    for i in range(1, 7):
        employees_data.append({
            "username": f"cs{i}",
            "name": f"客服员工{i}",
            "department": "客服部",
            "position": "客服专员",
            "status": 0
        })
    
    # 添加员工数据
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for employee in employees_data:
        cursor.execute('''
        INSERT INTO employees (username, name, department, position, status, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            employee["username"],
            employee["name"],
            employee["department"],
            employee["position"],
            employee["status"],
            current_time
        ))
    
    # 提交并关闭
    conn.commit()
    print(f"成功添加 {len(employees_data)} 条员工记录")
    
    # 验证数据
    cursor.execute("SELECT COUNT(*) FROM employees")
    count = cursor.fetchone()[0]
    print(f"数据库中共有 {count} 条员工记录")
    
    cursor.execute("SELECT department, COUNT(*) FROM employees GROUP BY department")
    dept_counts = cursor.fetchall()
    print("各部门员工数量:")
    for dept, count in dept_counts:
        print(f"  {dept}: {count} 人")
    
    conn.close()

def create_sample_excel(excel_folder="test_excel", file_name=None):
    """创建示例Excel排班文件"""
    if file_name is None:
        # 使用当前日期作为文件名
        file_name = datetime.now().strftime("%Y-%m-%d.xlsx")
    
    # 确保文件夹存在
    if not os.path.exists(excel_folder):
        os.makedirs(excel_folder)
        print(f"创建文件夹: {excel_folder}")
    
    # 完整的文件路径
    file_path = os.path.join(excel_folder, file_name)
    
    # 创建Excel writer
    writer = pd.ExcelWriter(file_path, engine='openpyxl')
    
    # 为每个部门创建排班表
    departments = ["技术部", "运维部", "安全部", "产品部", "客服部"]
    
    for dept in departments:
        # 获取部门人数和员工前缀
        if dept == "技术部":
            count = 10
            prefix = "tech"
        elif dept == "运维部":
            count = 7
            prefix = "ops"
        elif dept == "安全部":
            count = 5
            prefix = "sec"
        elif dept == "产品部":
            count = 3
            prefix = "prod"
        elif dept == "客服部":
            count = 6
            prefix = "cs"
        
        # 创建排班数据
        data = []
        for i in range(1, count + 1):
            # 随机安排值班情况 - 为了测试，我们设置一部分人为值班状态
            is_on_duty = 1 if i % 3 == 0 else 0
            shift = "ds" if i % 4 != 0 else "ns" if i % 4 == 0 else ""
            
            data.append({
                "user": f"{prefix}{i}",
                "name": f"{dept}员工{i}",
                "is_on_duty": is_on_duty,
                "shift": shift
            })
        
        # 创建DataFrame并保存到Excel
        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name=dept, index=False)
    
    # 保存Excel文件
    writer.close()
    
    print(f"成功创建排班Excel文件: {file_path}")
    return file_path

if __name__ == "__main__":
    # 创建数据库并添加示例数据
    db_path = create_database()
    insert_sample_data(db_path)
    
    # 创建示例Excel排班文件
    excel_file = create_sample_excel()
    
    print(f"\n初始化完成!")
    print(f"数据库路径: {os.path.abspath(db_path)}")
    print(f"Excel文件路径: {os.path.abspath(excel_file)}")
    print("\n您现在可以使用这些数据来测试status_update_server.py") 