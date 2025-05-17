# -*- coding: utf-8 -*-
"""
IC卡刷卡管理系统服务器
基于HTTP协议与读卡器通信，使用SQLite数据库存储相关数据
"""
import socket
import threading
import sqlite3
import logging
import time
import datetime
from logging.handlers import RotatingFileHandler
import os
from datetime import time as time_obj


# 定义允许刷卡的时间段
breakfast = (time_obj(3, 25), time_obj(5, 35))  # 03:25-05:35
lunch = (time_obj(9, 20), time_obj(10, 35))     # 09:20-10:35
dinner = (time_obj(14, 55), time_obj(17, 40))   # 14:55-17:40


# 设置日志系统
def setup_logging():
    """设置日志系统"""
    # 创建logger
    logger = logging.getLogger('ic_manager')
    logger.setLevel(logging.INFO)
    
    # 创建按大小轮转的日志文件处理器
    handler = RotatingFileHandler(
        'ic_manager.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    
    # 设置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S.%f'
    )
    handler.setFormatter(formatter)
    
    # 添加处理器到logger
    logger.addHandler(handler)
    
    return logger


# 初始化日志
logger = setup_logging()


# 创建线程锁，用于关键资源访问
card_lock = threading.Lock()


def init_database():
    """初始化数据库结构"""
    conn = sqlite3.connect('ic_manager.db')
    cursor = conn.cursor()
    
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
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")


def GetChineseCode(inputstr):
    """将中文信息转换编码"""
    strlen = len(inputstr)
    hexcode = ""
    for num in range(0, strlen):
        str_char = inputstr[num:num+1]
        sdata = bytes(str_char, encoding='gbk')  # 将信息转为bytes
        if len(sdata) == 1:
            hexcode = hexcode + str_char
        else:
            hexcode = hexcode + "\\x" + '%02X' % (sdata[0]) + '%02X' % (sdata[1])
    return hexcode


def create_error_response(info, error_msg, beep_code=7):
    """创建错误响应"""
    response = "Response=1," + info
    response += "," + GetChineseCode("{错误}" + error_msg)
    response += ",10," + str(beep_code) + ",,0,0"
    return response


def is_time_within_allowed_periods(current_time):
    """检查当前时间是否在允许的时间段内"""
    # 获取当前时间的小时和分钟
    time_now = time_obj(current_time.hour, current_time.minute)
    
    # 检查是否在任一允许的时间段内
    return ((breakfast[0] <= time_now <= breakfast[1]) or
            (lunch[0] <= time_now <= lunch[1]) or
            (dinner[0] <= time_now <= dinner[1]))


def process_card(card, jihao, info, dn=None):
    """处理刷卡业务逻辑"""
    conn = None
    try:
        # 构造基本响应
        response_base = f"Response=1,{info}"
        
        # 检查当前时间是否在允许的时间段内
        current_time = datetime.datetime.now()
        if not is_time_within_allowed_periods(current_time):
            # 记录时间段错误
            conn = sqlite3.connect('ic_manager.db')
            conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
            cursor = conn.cursor()
            
            # 查询用户信息（如果卡存在）
            cursor.execute('SELECT user, department FROM kbk_ic_manager WHERE card = ?', (card,))
            result = cursor.fetchone()
            
            if result:
                user, department = result
                cursor.execute(
                    'INSERT INTO kbk_ic_failure_records (user, department, failure_type, transaction_date) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                    (user, department, 3)  # 时间段错误
                )
            else:
                cursor.execute(
                    'INSERT INTO kbk_ic_failure_records (failure_type, transaction_date) VALUES (?, CURRENT_TIMESTAMP)',
                    (3,)  # 时间段错误，卡不存在
                )
            
            conn.commit()
            logger.warning(f"Card swiped outside allowed time periods: {card}")
            
            # 构造失败响应
            display_text = GetChineseCode("{错误}不在允许的用餐时间")
            return f"{response_base},{display_text},10,7,,0,0"
        
        # 连接数据库
        conn = sqlite3.connect('ic_manager.db')
        # 设置超时
        conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 开始事务
        conn.execute('BEGIN IMMEDIATE TRANSACTION')
        
        # 查询卡片信息
        cursor.execute('SELECT * FROM kbk_ic_manager WHERE card = ?', (card,))
        card_info = cursor.fetchone()
        
        
        # 如果卡号不存在
        if not card_info:
            # 记录失败信息
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (failure_type, transaction_date) VALUES (?, CURRENT_TIMESTAMP)',
                (2,)  # 卡号不存在
            )
            conn.commit()
            logger.warning(f"Card not found: {card}")
            
            # 构造失败响应
            display_text = GetChineseCode("{错误}卡号不存在")
            return f"{response_base},{display_text},10,7,,0,0"
        
        # 获取卡片信息
        user = card_info['user']
        department = card_info['department']
        status = card_info['status']
        
        # 如果卡片未激活
        if status != 1:
            # 记录失败信息
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (user, department, failure_type, transaction_date) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                (user, department, 1)  # 未激活
            )
            conn.commit()
            logger.warning(f"Card inactive: {card}, User: {user}")
            
            # 构造失败响应
            display_text = GetChineseCode("{失败}卡片未激活")
            return f"{response_base},{display_text},10,7,,0,0"
        
        # 卡片有效，更新状态
        cursor.execute(
            'UPDATE kbk_ic_manager SET status = 0, last_updated = CURRENT_TIMESTAMP WHERE card = ?',
            (card,)
        )
        
        # 根据jihao插入对应计数表
        count_table = ""
        if jihao == "1":
            count_table = "kbk_ic_cn_count"
        elif jihao == "2":
            count_table = "kbk_ic_en_count"
        elif jihao == "3":
            count_table = "kbk_ic_nm_count"
        
        if count_table:
            cursor.execute(
                f'INSERT INTO {count_table} (user, department, transaction_date) VALUES (?, ?, CURRENT_TIMESTAMP)',
                (user, department)
            )
        
        # 提交事务
        conn.commit()
        
        logger.info(f"Card processed successfully: {card}, User: {user}, Jihao: {jihao}")
        
        # 构造成功响应
        display_text = GetChineseCode("{成功}") + user + " " + department
        voice_text = GetChineseCode("[v8]刷卡成功")
        
        return f"{response_base},{display_text},10,5,{voice_text},0,0"
        
    except sqlite3.Error as e:
        # 发生错误时回滚事务
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        display_text = GetChineseCode("{错误}系统异常")
        return f"{response_base},{display_text},10,7,,0,0"
        
    finally:
        # 关闭数据库连接
        if conn:
            conn.close()


def process_heartbeat(info, dn):
    """处理心跳包"""
    logger.debug(f"Heartbeat received from device: {dn}")
    return f"Response=1,{info},,0,0,,"


def parse_request(request):
    """解析HTTP请求获取参数"""
    request_header_lines = request.splitlines()
    requestlines = len(request_header_lines)
    
    # 解析GET请求
    if request.startswith("GET"):
        try:
            start_idx = request_header_lines[0].find("?") + 1
            end_idx = request_header_lines[0].find("HTTP/1.1") - 1
            if start_idx > 0 and end_idx > start_idx:
                CommitParameter = request_header_lines[0][start_idx:end_idx]
            else:
                return {}
        except:
            return {}
    # 解析POST请求
    elif request.startswith("POST"):
        try:
            CommitParameter = request_header_lines[requestlines-1]
            # 处理JSON格式
            if "Content-Type: application/json" in request:
                CommitParameter = CommitParameter.replace("{", "")
                CommitParameter = CommitParameter.replace("\"", "")
                CommitParameter = CommitParameter.replace(":", "=")
                CommitParameter = CommitParameter.replace(",", "&")
                CommitParameter = CommitParameter.replace("}", "")
        except:
            return {}
    else:
        return {}
    
    # 解析参数
    params = {}
    FieldsList = CommitParameter.split('&')
    for field in FieldsList:
        if '=' in field:
            key, value = field.split('=', 1)
            params[key.strip()] = value.strip()
    
    return params


def service_client(new_socket):
    """处理客户端连接"""
    try:
        # 接收HTTP请求
        request = new_socket.recv(1024).decode('utf-8')
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.debug(f"Request received at {current_time}")
        
        # 解析请求参数
        params = parse_request(request)
        if not params:
            new_socket.close()
            return
        
        # 提取关键参数
        info = params.get('info', '')
        dn = params.get('dn', '')
        heartbeattype = params.get('heartbeattype', '')
        card = params.get('card', '')
        jihao = params.get('jihao', '')
        
        # 处理心跳包
        if heartbeattype == "1" and len(dn) == 16 and len(info) > 0:
            ResponseStr = process_heartbeat(info, dn)
            new_socket.send(ResponseStr.encode("gbk"))
            logger.debug(f"Heartbeat response sent: {ResponseStr}")
            new_socket.close()
            return
        
        # 处理刷卡
        if len(dn) == 16 and len(card) > 4 and len(info) > 0:
            ResponseStr = process_card(card, jihao, info, dn)
            new_socket.send(ResponseStr.encode("gbk"))
            logger.debug(f"Card response sent: {ResponseStr}")
            new_socket.close()
            return
        
        # 其他未知情况
        new_socket.close()
        logger.warning(f"Unknown request parameters: {params}")
        
    except Exception as e:
        logger.error(f"Error handling client: {e}")
        try:
            new_socket.close()
        except:
            pass


def update_card_status(card, new_status):
    """更新卡片状态，带并发控制"""
    # 使用锁保护数据库操作
    with card_lock:
        conn = sqlite3.connect('ic_manager.db')
        try:
            # 设置超时
            conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
            # 使用事务保证原子性
            conn.execute('BEGIN IMMEDIATE TRANSACTION')  # IMMEDIATE提供写锁
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE kbk_ic_manager SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE card = ?',
                (new_status, card)
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            return False
        finally:
            conn.close()


def main():
    """主函数，启动服务器"""
    # 初始化数据库
    init_database()
    
    # 创建TCP服务器
    tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        # 绑定端口并监听
        tcp_server_socket.bind(("", 99))  # 使用88端口，与读卡器默认端口一致
        tcp_server_socket.listen(128)
        logger.info("Server started, listening on port 99")
        
        # 主循环
        while True:
            try:
                # 接受新连接
                new_socket, client_addr = tcp_server_socket.accept()
                logger.debug(f"New connection from {client_addr}")
                
                # 创建新线程处理连接
                t = threading.Thread(target=service_client, args=(new_socket,))
                t.start()
            except Exception as e:
                logger.error(f"Error accepting connection: {e}")
    
    except KeyboardInterrupt:
        logger.info("Server stopping due to keyboard interrupt")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        # 关闭服务器套接字
        tcp_server_socket.close()
        logger.info("Server stopped")


if __name__ == '__main__':
    main()
