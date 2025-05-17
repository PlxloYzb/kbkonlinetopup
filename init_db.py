# -*- coding: utf-8 -*-
"""
IC卡刷卡管理系统数据库初始化脚本
创建数据库表结构并插入示例数据
"""
import sqlite3
import os
import datetime
import argparse


def init_database(db_file='ic_manager.db', with_sample_data=True):
    """初始化数据库"""
    # 如果数据库文件已存在，询问是否覆盖
    if os.path.exists(db_file) and not with_sample_data:
        choice = input(f"数据库文件 {db_file} 已存在，是否覆盖? (y/n): ")
        if choice.lower() != 'y':
            print("操作已取消")
            return False
    
    # 连接数据库
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    try:
        # 创建卡片管理表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS kbk_ic_manager (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            card TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建卡号索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_card ON kbk_ic_manager(card)')
        
        # 创建计数表
        for table in ['kbk_ic_en_count', 'kbk_ic_cn_count', 'kbk_ic_nm_count']:
            cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                department TEXT NOT NULL,
                transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            ''')
        
        # 创建失败记录表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS kbk_ic_failure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            department TEXT,
            transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            failure_type INTEGER NOT NULL
        )
        ''')
        
        # 如果需要，插入示例数据
        if with_sample_data:
            # 插入卡片数据
            sample_cards = [
                ('张三', 'A1B2C3D4', '技术部', 1),
                ('李四', 'E5F6G7H8', '市场部', 1),
                ('王五', 'I9J0K1L2', '财务部', 1),
                ('赵六', 'M3N4O5P6', '人事部', 0),
                ('钱七', 'Q7R8S9T0', '行政部', 0)
            ]
            
            for card in sample_cards:
                try:
                    cursor.execute(
                        'INSERT INTO kbk_ic_manager (user, card, department, status) VALUES (?, ?, ?, ?)',
                        card
                    )
                except sqlite3.IntegrityError:
                    # 如果卡号已存在，则更新
                    cursor.execute(
                        'UPDATE kbk_ic_manager SET user = ?, department = ?, status = ? WHERE card = ?',
                        (card[0], card[2], card[3], card[1])
                    )
            
            # 插入一些计数记录
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 中文计数表
            cursor.execute(
                'INSERT INTO kbk_ic_cn_count (user, department, transaction_date) VALUES (?, ?, ?)',
                ('张三', '技术部', current_time)
            )
            
            # 英文计数表
            cursor.execute(
                'INSERT INTO kbk_ic_en_count (user, department, transaction_date) VALUES (?, ?, ?)',
                ('李四', '市场部', current_time)
            )
            
            # 其他语言计数表
            cursor.execute(
                'INSERT INTO kbk_ic_nm_count (user, department, transaction_date) VALUES (?, ?, ?)',
                ('王五', '财务部', current_time)
            )
            
            # 失败记录表
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (user, department, failure_type, transaction_date) VALUES (?, ?, ?, ?)',
                ('赵六', '人事部', 1, current_time)  # 未激活
            )
            
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (failure_type, transaction_date) VALUES (?, ?)',
                (2, current_time)  # 卡号不存在
            )
        
        # 提交事务
        conn.commit()
        print(f"数据库 {db_file} 初始化成功" + (" 并已插入示例数据" if with_sample_data else ""))
        return True
        
    except sqlite3.Error as e:
        # 发生错误时回滚事务
        conn.rollback()
        print(f"数据库错误: {e}")
        return False
        
    finally:
        # 关闭数据库连接
        conn.close()


if __name__ == '__main__':
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='IC卡刷卡管理系统数据库初始化脚本')
    parser.add_argument('-d', '--database', default='ic_manager.db', help='数据库文件名 (默认: ic_manager.db)')
    parser.add_argument('-s', '--sample', action='store_true', help='插入示例数据')
    
    args = parser.parse_args()
    
    # 初始化数据库
    init_database(args.database, args.sample)
