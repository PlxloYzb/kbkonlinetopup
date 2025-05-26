# -*- coding: utf-8 -*-
"""
IC卡刷卡管理系统服务器
基于HTTP协议与读卡器通信，使用SQLite数据库存储相关数据
增强版本 - 针对Ubuntu Server环境优化网络处理
"""
import socket
import threading
import sqlite3
import logging
import time
import datetime
import signal
import sys
import errno
from logging.handlers import RotatingFileHandler
import os
from datetime import time as time_obj


# 定义允许刷卡的时间段
breakfast = (time_obj(5, 25), time_obj(7, 40))  # 05:25-07:40
lunch = (time_obj(10, 20), time_obj(12, 35))     # 11:20-12:35
dinner = (time_obj(16, 00), time_obj(23, 40))   # 16:00-23:40

# 全局服务器套接字引用（用于优雅关闭）
tcp_server_socket = None

# 设置日志系统
def setup_logging():
    """设置日志系统"""
    # 创建logger
    logger = logging.getLogger('ic_manager')
    logger.setLevel(logging.INFO)
    
    # 清除已有的处理器
    logger.handlers.clear()
    
    # 创建按大小轮转的日志文件处理器
    handler = RotatingFileHandler(
        'ic_manager.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    
    # 设置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
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


# 创建线程锁，用于关键资源访问
card_lock = threading.Lock()
connection_count_lock = threading.Lock()
active_connections = 0


def signal_handler(signum, frame):
    """信号处理器，用于优雅关闭服务器"""
    global tcp_server_socket
    logger.info(f"[SYS] 接收到信号 {signum}，准备关闭服务器")
    if tcp_server_socket:
        try:
            tcp_server_socket.close()
            logger.info("[SYS] 服务器套接字已关闭")
        except Exception as e:
            logger.error(f"[SYS] 关闭服务器套接字时出错: {e}")
    logger.info("[SYS] 服务器正在退出...")
    sys.exit(0)


def init_database():
    """初始化数据库结构"""
    logger.info("[DB] 连接数据库: ic_manager.db")
    try:
        conn = sqlite3.connect('ic_manager.db', timeout=30.0)
        # 设置数据库连接以使用本地时区
        conn.execute("PRAGMA timezone='localtime'")
        # 设置WAL模式以提高并发性能
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        cursor = conn.cursor()
        
        # 创建卡片管理表
        logger.info("[DB] 创建表: kbk_ic_manager")
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
        logger.info("[DB] 创建索引: idx_card ON kbk_ic_manager(card)")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_card ON kbk_ic_manager(card)')
        
        # 创建计数表
        for table in ['kbk_ic_en_count', 'kbk_ic_cn_count', 'kbk_ic_nm_count']:
            logger.info(f"[DB] 创建表: {table}")
            cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                department TEXT NOT NULL,
                transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            ''')
        
        # 创建失败记录表
        logger.info("[DB] 创建表: kbk_ic_failure_records")
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
        logger.info("[DB] 数据库初始化完成并已提交更改")
        conn.close()
        logger.info("[DB] Database initialized successfully")
        
    except sqlite3.Error as e:
        logger.error(f"[DB] 数据库初始化失败: {e}")
        raise
    except Exception as e:
        logger.error(f"[DB] 初始化过程中发生未知错误: {e}")
        raise


def GetChineseCode(inputstr):
    """将中文信息转换编码"""
    strlen = len(inputstr)
    hexcode = ""
    for num in range(0, strlen):
        str_char = inputstr[num:num+1]
        try:
            sdata = bytes(str_char, encoding='gbk')  # 将信息转为bytes
            if len(sdata) == 1:
                hexcode = hexcode + str_char
            else:
                hexcode = hexcode + "\\x" + '%02X' % (sdata[0]) + '%02X' % (sdata[1])
        except UnicodeEncodeError as e:
            logger.warning(f"[ENCODE] 字符编码失败: {str_char}, 错误: {e}")
            hexcode = hexcode + str_char  # 如果编码失败，保持原字符
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


def get_local_timestamp():
    """获取本地时区的时间戳字符串"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def process_card(card, jihao, info, dn=None):
    """处理刷卡业务逻辑"""
    conn = None
    try:
        logger.info(f"[BUSINESS] 开始处理刷卡: card={card}, jihao={jihao}, info={info}, dn={dn}")
        # 构造基本响应
        response_base = f"Response=1,{info}"
        
        # 检查当前时间是否在允许的时间段内
        current_time = datetime.datetime.now()
        logger.info(f"[TIME] 当前时间: {current_time.strftime('%H:%M:%S')}")
        if not is_time_within_allowed_periods(current_time):
            # 记录时间段错误
            logger.warning(f"[TIME] 不在允许的用餐时间段内: {current_time.strftime('%H:%M:%S')}")
            logger.info("[DB] 连接数据库: ic_manager.db")
            conn = sqlite3.connect('ic_manager.db', timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
            cursor = conn.cursor()
            # 查询用户信息（如果卡存在）
            logger.info(f"[DB] 查询卡片用户信息: SELECT user, department FROM kbk_ic_manager WHERE card = {card}")
            cursor.execute('SELECT user, department FROM kbk_ic_manager WHERE card = ?', (card,))
            result = cursor.fetchone()
            if result:
                user, department = result
                logger.info(f"[DB] 插入失败记录: user={user}, department={department}, failure_type=3")
                cursor.execute(
                    'INSERT INTO kbk_ic_failure_records (user, department, failure_type, transaction_date) VALUES (?, ?, ?, ?)',
                    (user, department, 3, get_local_timestamp())  # 时间段错误
                )
            else:
                logger.info(f"[DB] 插入失败记录: 卡不存在, failure_type=3")
                cursor.execute(
                    'INSERT INTO kbk_ic_failure_records (failure_type, transaction_date) VALUES (?, ?)',
                    (3, get_local_timestamp())  # 时间段错误，卡不存在
                )
            conn.commit()
            logger.info("[DB] 已提交失败记录（时间段错误）")
            logger.warning(f"[BUSINESS] Card swiped outside allowed time periods: {card}")
            # 构造失败响应
            display_text = GetChineseCode("{错误}不在允许的用餐时间")
            return f"{response_base},{display_text},10,0,,0,0"
            
        # 连接数据库
        logger.info("[DB] 连接数据库进行卡片验证: ic_manager.db")
        conn = sqlite3.connect('ic_manager.db', timeout=30.0)
        # 设置超时
        conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 开始事务
        conn.execute('BEGIN IMMEDIATE TRANSACTION')
        logger.info(f"[DB] 查询卡片信息: SELECT * FROM kbk_ic_manager WHERE card = {card}")
        # 查询卡片信息
        cursor.execute('SELECT * FROM kbk_ic_manager WHERE card = ?', (card,))
        card_info = cursor.fetchone()
        
        
        # 如果卡号不存在
        if not card_info:
            logger.warning(f"[DB] 卡号不存在: {card}")
            # 记录失败信息
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (failure_type, transaction_date) VALUES (?, ?)',
                (2, get_local_timestamp())  # 卡号不存在
            )
            conn.commit()
            logger.info("[DB] 已提交失败记录（卡号不存在）")
            logger.warning(f"[BUSINESS] Card not found: {card}")
            
            # 构造失败响应
            display_text = GetChineseCode("{错误}卡号不存在")
            return f"{response_base},{display_text},10,0,,0,0"
        
        # 获取卡片信息
        user = card_info['user']
        department = card_info['department']
        status = card_info['status']
        logger.info(f"[DB] 卡片信息: user={user}, department={department}, status={status}")
        
        # 如果卡片未激活
        if status != 1:
            logger.warning(f"[DB] 卡片未激活: card={card}, status={status}")
            # 记录失败信息
            cursor.execute(
                'INSERT INTO kbk_ic_failure_records (user, department, failure_type, transaction_date) VALUES (?, ?, ?, ?)',
                (user, department, 1, get_local_timestamp())  # 未激活
            )
            conn.commit()
            logger.info("[DB] 已提交失败记录（卡片未激活）")
            logger.warning(f"[BUSINESS] Card inactive: {card}, User: {user}")
            
            # 构造失败响应
            display_text = GetChineseCode("{失败}卡片未激活")
            return f"{response_base},{display_text},10,0,,0,0"
        
        # 卡片有效，更新状态
        logger.info(f"[DB] 更新卡片状态: card={card}, status=0")
        cursor.execute(
            'UPDATE kbk_ic_manager SET status = 0, last_updated = ? WHERE card = ?',
            (get_local_timestamp(), card)
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
            logger.info(f"[DB] 插入计数表: {count_table}, user={user}, department={department}")
            cursor.execute(
                f'INSERT INTO {count_table} (user, department, transaction_date) VALUES (?, ?, ?)',
                (user, department, get_local_timestamp())
            )
        
        # 提交事务
        conn.commit()
        logger.info("[DB] 刷卡业务处理成功并已提交更改")
        
        logger.info(f"[BUSINESS] Card processed successfully: {card}, User: {user}, Jihao: {jihao}")
        
        # 构造成功响应
        display_text = GetChineseCode("{成功}") + user + " " + department
        voice_text = GetChineseCode("[v8]刷卡成功")
        
        return f"{response_base},{display_text},10,2,{voice_text},0,0"
        
    except sqlite3.Error as e:
        logger.error(f"[DB] 数据库异常: {e}")
        # 发生错误时回滚事务
        if conn:
            try:
                conn.rollback()
                logger.info("[DB] 事务已回滚")
            except Exception as rollback_error:
                logger.error(f"[DB] 回滚事务失败: {rollback_error}")
        logger.error(f"[BUSINESS] Database error: {e}")
        display_text = GetChineseCode("{错误}系统异常")
        return f"{response_base},{display_text},10,0,,0,0"
        
    except Exception as e:
        logger.error(f"[BUSINESS] 处理刷卡时发生未知错误: {e}")
        if conn:
            try:
                conn.rollback()
                logger.info("[DB] 事务已回滚")
            except Exception as rollback_error:
                logger.error(f"[DB] 回滚事务失败: {rollback_error}")
        display_text = GetChineseCode("{错误}系统异常")
        return f"{response_base},{display_text},10,0,,0,0"
        
    finally:
        logger.info("[DB] 关闭数据库连接")
        # 关闭数据库连接
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.error(f"[DB] 关闭数据库连接失败: {e}")


def process_heartbeat(info, dn):
    """处理心跳包"""
    logger.debug(f"[HEARTBEAT] Heartbeat received from device: {dn}")
    return f"Response=1,{info},,0,0,,"


def parse_request(request):
    """解析HTTP请求获取参数"""
    try:
        logger.debug(f"[PARSE] 开始解析请求，请求长度: {len(request)}")
        request_header_lines = request.splitlines()
        requestlines = len(request_header_lines)
        logger.debug(f"[PARSE] 请求行数: {requestlines}")
        
        # 解析GET请求
        if request.startswith("GET"):
            logger.debug("[PARSE] 处理GET请求")
            try:
                start_idx = request_header_lines[0].find("?") + 1
                end_idx = request_header_lines[0].find("HTTP/1.1") - 1
                if start_idx > 0 and end_idx > start_idx:
                    CommitParameter = request_header_lines[0][start_idx:end_idx]
                    logger.debug(f"[PARSE] GET参数: {CommitParameter}")
                else:
                    logger.warning("[PARSE] GET请求无参数")
                    return {}
            except Exception as e:
                logger.error(f"[PARSE] 解析GET请求失败: {e}")
                return {}
                
        # 解析POST请求
        elif request.startswith("POST"):
            logger.debug("[PARSE] 处理POST请求")
            try:
                CommitParameter = request_header_lines[requestlines-1]
                logger.debug(f"[PARSE] POST原始参数: {CommitParameter}")
                # 处理JSON格式
                if "Content-Type: application/json" in request:
                    logger.debug("[PARSE] 检测到JSON格式，进行转换")
                    CommitParameter = CommitParameter.replace("{", "")
                    CommitParameter = CommitParameter.replace("\"", "")
                    CommitParameter = CommitParameter.replace(":", "=")
                    CommitParameter = CommitParameter.replace(",", "&")
                    CommitParameter = CommitParameter.replace("}", "")
                    logger.debug(f"[PARSE] JSON转换后参数: {CommitParameter}")
            except Exception as e:
                logger.error(f"[PARSE] 解析POST请求失败: {e}")
                return {}
        else:
            logger.warning(f"[PARSE] 未知请求类型: {request[:20]}")
            return {}
        
        # 解析参数
        params = {}
        FieldsList = CommitParameter.split('&')
        logger.debug(f"[PARSE] 参数字段列表: {FieldsList}")
        for field in FieldsList:
            if '=' in field:
                key, value = field.split('=', 1)
                params[key.strip()] = value.strip()
        
        logger.debug(f"[PARSE] 解析完成，参数: {params}")
        return params
        
    except Exception as e:
        logger.error(f"[PARSE] 解析请求时发生异常: {e}")
        return {}


def update_connection_count(delta):
    """更新活跃连接数"""
    global active_connections
    with connection_count_lock:
        active_connections += delta
        logger.info(f"[NET] 活跃连接数: {active_connections}")


def service_client(new_socket, client_addr):
    """处理客户端连接"""
    client_ip, client_port = client_addr
    logger.info(f"[NET] 开始处理客户端连接: {client_ip}:{client_port}")
    update_connection_count(1)
    
    try:
        # 设置套接字超时
        new_socket.settimeout(10.0)
        logger.debug(f"[NET] 已设置套接字超时: 10秒")
        
        # 接收HTTP请求
        logger.debug(f"[NET] 开始接收数据从 {client_ip}:{client_port}")
        request_data = b""
        
        try:
            # 设置较短的接收超时，避免长时间阻塞
            new_socket.settimeout(5.0)
            logger.debug(f"[NET] 调整接收超时为5秒: {client_ip}:{client_port}")
            
            # 分块接收数据，避免数据不完整
            max_recv_attempts = 3
            recv_attempts = 0
            
            while recv_attempts < max_recv_attempts:
                try:
                    chunk = new_socket.recv(1024)
                    if not chunk:
                        logger.debug(f"[NET] 接收到空数据块，连接可能已关闭: {client_ip}:{client_port}")
                        break
                        
                    request_data += chunk
                    logger.debug(f"[NET] 接收数据块，大小: {len(chunk)}, 总大小: {len(request_data)}")
                    
                    # 检查是否接收完整的HTTP请求
                    if b'\r\n\r\n' in request_data:
                        logger.debug(f"[NET] 检测到完整HTTP头: {client_ip}:{client_port}")
                        
                        # 如果是POST请求，可能还有body数据
                        if request_data.startswith(b'POST'):
                            logger.debug(f"[NET] POST请求，尝试接收body数据: {client_ip}:{client_port}")
                            try:
                                # 设置更短的超时等待body数据
                                new_socket.settimeout(1.0)
                                additional_data = new_socket.recv(1024)
                                if additional_data:
                                    request_data += additional_data
                                    logger.debug(f"[NET] 接收到额外body数据: {len(additional_data)}")
                            except socket.timeout:
                                logger.debug(f"[NET] body数据接收超时，可能没有更多数据: {client_ip}:{client_port}")
                                pass  # 超时是正常的，说明没有更多数据
                        break
                        
                    # 如果数据看起来像简单的GET请求（没有标准HTTP头结束符）
                    elif (b'GET /' in request_data or b'POST /' in request_data) and len(request_data) > 50:
                        logger.debug(f"[NET] 检测到简单HTTP请求: {client_ip}:{client_port}")
                        break
                        
                except socket.timeout:
                    recv_attempts += 1
                    logger.warning(f"[NET] 接收数据超时，尝试次数: {recv_attempts}/{max_recv_attempts}: {client_ip}:{client_port}")
                    if recv_attempts >= max_recv_attempts:
                        break
                    continue
                except Exception as recv_error:
                    logger.error(f"[NET] 接收数据时发生异常: {client_ip}:{client_port}, 错误: {recv_error}")
                    break
                    
        except socket.timeout:
            logger.warning(f"[NET] 接收数据超时: {client_ip}:{client_port}")
            return
        except Exception as e:
            logger.error(f"[NET] 接收数据失败: {client_ip}:{client_port}, 错误: {e}")
            return
            
        if not request_data:
            logger.warning(f"[NET] 未接收到数据: {client_ip}:{client_port}")
            return
            
        try:
            request = request_data.decode('utf-8')
            logger.debug(f"[NET] 成功解码请求数据，长度: {len(request)}")
        except UnicodeDecodeError:
            try:
                request = request_data.decode('gbk')
                logger.debug(f"[NET] 使用GBK编码解码请求数据，长度: {len(request)}")
            except UnicodeDecodeError as e:
                logger.error(f"[NET] 无法解码请求数据: {client_ip}:{client_port}, 错误: {e}")
                return
        
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.debug(f"[NET] 成功接收并解码请求: {client_ip}:{client_port}, 请求类型: {request[:10].strip()}")
        logger.info(f"[NET] Request received at {current_time} from {client_ip}:{client_port}")
        
        # 解析请求参数
        params = parse_request(request)
        if not params:
            logger.warning(f"[NET] 无法解析请求参数: {client_ip}:{client_port}")
            try:
                new_socket.close()
            except:
                pass
            return
        
        # 提取关键参数
        info = params.get('info', '')
        dn = params.get('dn', '')
        heartbeattype = params.get('heartbeattype', '')
        card = params.get('card', '')
        jihao = params.get('jihao', '')
        
        logger.info(f"[NET] 解析到参数: info={info}, dn={dn}, heartbeattype={heartbeattype}, card={card}, jihao={jihao}")
        
        response_str = ""
        
        # 处理心跳包
        if heartbeattype == "1" and len(dn) == 16 and len(info) > 0:
            logger.info(f"[NET] 处理心跳包: device={dn}")
            response_str = process_heartbeat(info, dn)
            
        # 处理刷卡
        elif len(dn) == 16 and len(card) > 4 and len(info) > 0:
            logger.info(f"[NET] 处理刷卡请求: card={card}, device={dn}")
            response_str = process_card(card, jihao, info, dn)
            
        else:
            logger.warning(f"[NET] 未识别的请求类型: {params}")
            try:
                new_socket.close()
            except:
                pass
            return
        
                    # 发送响应
            try:
                logger.debug(f"[NET] 准备发送响应: {response_str}")
                response_bytes = response_str.encode("gbk")
                
                # 设置发送超时
                new_socket.settimeout(5.0)
                
                # 发送数据
                bytes_sent = new_socket.send(response_bytes)
                logger.info(f"[NET] 响应已发送到 {client_ip}:{client_port}, 长度: {len(response_bytes)}, 实际发送: {bytes_sent}")
                
                # 确认所有数据都已发送
                if bytes_sent < len(response_bytes):
                    logger.warning(f"[NET] 响应数据未完全发送: {client_ip}:{client_port}, 已发送: {bytes_sent}/{len(response_bytes)}")
            except socket.timeout:
                logger.error(f"[NET] 发送响应超时: {client_ip}:{client_port}")
            except Exception as e:
                logger.error(f"[NET] 发送响应失败: {client_ip}:{client_port}, 错误: {e}")
        
        # 关闭连接
        try:
            new_socket.close()
            logger.debug(f"[NET] 连接已关闭: {client_ip}:{client_port}")
        except Exception as e:
            logger.error(f"[NET] 关闭连接失败: {client_ip}:{client_port}, 错误: {e}")
        
    except Exception as e:
        logger.error(f"[NET] 处理客户端连接时发生异常: {client_ip}:{client_port}, 错误: {e}")
        try:
            new_socket.close()
        except:
            pass
    finally:
        update_connection_count(-1)
        logger.info(f"[NET] 客户端连接处理完成: {client_ip}:{client_port}")


def update_card_status(card, new_status):
    """更新卡片状态，带并发控制"""
    # 使用锁保护数据库操作
    with card_lock:
        logger.info(f"[DB] 更新卡片状态: card={card}, new_status={new_status}")
        conn = None
        try:
            conn = sqlite3.connect('ic_manager.db', timeout=30.0)
            # 设置超时
            conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
            # 设置数据库连接以使用本地时区
            conn.execute("PRAGMA timezone='localtime'")
            # 使用事务保证原子性
            conn.execute('BEGIN IMMEDIATE TRANSACTION')  # IMMEDIATE提供写锁
            cursor = conn.cursor()
            logger.info(f"[DB] 执行SQL: UPDATE kbk_ic_manager SET status = {new_status}, last_updated = 当前时间 WHERE card = {card}")
            cursor.execute(
                'UPDATE kbk_ic_manager SET status = ?, last_updated = ? WHERE card = ?',
                (new_status, get_local_timestamp(), card)
            )
            conn.commit()
            logger.info("[DB] 卡片状态更新并已提交更改")
            return True
        except sqlite3.Error as e:
            logger.error(f"[DB] 数据库异常: {e}")
            if conn:
                try:
                    conn.rollback()
                    logger.info("[DB] 事务已回滚")
                except:
                    pass
            logger.error(f"[DB] Database error: {e}")
            return False
        except Exception as e:
            logger.error(f"[DB] 更新卡片状态时发生未知错误: {e}")
            if conn:
                try:
                    conn.rollback()
                    logger.info("[DB] 事务已回滚")
                except:
                    pass
            return False
        finally:
            logger.info("[DB] 关闭数据库连接")
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"[DB] 关闭数据库连接失败: {e}")


def create_server_socket():
    """创建并配置服务器套接字"""
    logger.info("[NET] 创建TCP服务器套接字")
    
    try:
        # 创建套接字
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        logger.info("[NET] TCP套接字创建成功")
        
        # 设置套接字选项
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        logger.info("[NET] 已设置 SO_REUSEADDR")
        
        # 在Linux/Unix系统上设置 SO_REUSEPORT（如果支持）
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            logger.info("[NET] 已设置 SO_REUSEPORT")
        except AttributeError:
            logger.info("[NET] 系统不支持 SO_REUSEPORT，跳过")
        except OSError as e:
            logger.warning(f"[NET] 设置 SO_REUSEPORT 失败: {e}")
        
        # 设置TCP_NODELAY减少延迟
        try:
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            logger.info("[NET] 已设置 TCP_NODELAY")
        except Exception as e:
            logger.warning(f"[NET] 设置 TCP_NODELAY 失败: {e}")
        
        # 设置发送和接收缓冲区大小
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            logger.info("[NET] 已设置发送和接收缓冲区大小为64KB")
        except Exception as e:
            logger.warning(f"[NET] 设置缓冲区大小失败: {e}")
        
        return server_socket
        
    except Exception as e:
        logger.error(f"[NET] 创建服务器套接字失败: {e}")
        raise


def main():
    """主函数，启动服务器"""
    global tcp_server_socket
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("[SYS] 脚本启动，准备初始化数据库")
    
    # 初始化数据库
    try:
        init_database()
        logger.info("[SYS] 数据库初始化完成")
    except Exception as e:
        logger.error(f"[SYS] 数据库初始化失败: {e}")
        return 1
    
    # 创建服务器套接字
    try:
        tcp_server_socket = create_server_socket()
    except Exception as e:
        logger.error(f"[SYS] 创建服务器套接字失败: {e}")
        return 1
    
    try:
        # 绑定端口并监听
        server_host = "0.0.0.0"
        server_port = 9024
        
        # 设置服务器套接字超时，避免accept阻塞太久
        tcp_server_socket.settimeout(60.0)
        logger.info(f"[NET] 设置服务器套接字超时: 60秒")
        
        logger.info(f"[NET] 绑定地址: {server_host}:{server_port}")
        tcp_server_socket.bind((server_host, server_port))
        logger.info(f"[NET] 端口绑定成功: {server_port}")
        
        # 开始监听，设置较大的backlog
        backlog = 256
        tcp_server_socket.listen(backlog)
        logger.info(f"[NET] 服务器启动成功，监听端口{server_port}，backlog={backlog}")
        
        # 显示网络接口信息
        try:
            import socket as sock_module
            hostname = sock_module.gethostname()
            local_ip = sock_module.gethostbyname(hostname)
            logger.info(f"[NET] 主机名: {hostname}, 本地IP: {local_ip}")
        except Exception as e:
            logger.warning(f"[NET] 无法获取本地IP信息: {e}")
        
        logger.info("[SYS] 服务器启动完成，等待连接...")
        
        # 主循环
        while True:
            try:
                logger.debug("[NET] 等待新连接...")
                # 接受新连接
                try:
                    new_socket, client_addr = tcp_server_socket.accept()
                    logger.info(f"[NET] 新连接已建立: {client_addr[0]}:{client_addr[1]}")
                except socket.timeout:
                    logger.debug("[NET] accept超时，继续监听...")
                    continue
                
                # 创建新线程处理连接
                thread_name = f"Client-{client_addr[0]}:{client_addr[1]}"
                t = threading.Thread(
                    target=service_client, 
                    args=(new_socket, client_addr),
                    name=thread_name
                )
                t.daemon = True  # 设置为守护线程
                t.start()
                logger.debug(f"[NET] 已创建处理线程: {thread_name}")
                
            except OSError as e:
                if e.errno == errno.EINTR:
                    logger.info("[NET] 接收连接被信号中断")
                    break
                elif e.errno == errno.EBADF:
                    logger.info("[NET] 套接字已关闭")
                    break
                else:
                    logger.error(f"[NET] 接收连接时发生OSError: {e}")
            except Exception as e:
                logger.error(f"[NET] 接收连接异常: {e}")
                time.sleep(1)  # 短暂延迟避免快速循环
    
    except KeyboardInterrupt:
        logger.info("[SYS] 检测到键盘中断，服务器即将停止")
    except Exception as e:
        logger.error(f"[SYS] 服务器启动或运行异常: {e}")
        return 1
    finally:
        # 关闭服务器套接字
        if tcp_server_socket:
            try:
                tcp_server_socket.close()
                logger.info("[SYS] 服务器套接字已关闭")
            except Exception as e:
                logger.error(f"[SYS] 关闭服务器套接字失败: {e}")
        
        logger.info("[SYS] 服务器已关闭")
        return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
