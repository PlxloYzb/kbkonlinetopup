# IC卡刷卡管理系统

基于HTTP协议与读卡器通信，使用SQLite数据库存储相关数据的IC卡刷卡管理系统。

## 系统概述

本系统旨在管理IC卡刷卡器的操作记录和卡片状态。系统基于HTTP协议与读卡器通信，使用SQLite数据库存储相关数据。系统接收并处理读卡器发送的信息，并按照特定格式返回响应以控制读卡器的行为。

## 功能特点

- 卡片状态管理：添加、查询、更新卡片状态
- 多语言计数功能：支持中文、英语和其他语言的计数表
- 失败记录跟踪：记录卡片未激活或不存在的情况
- 并发控制：支持多个读卡器同时请求
- 高性能设计：使用多线程处理请求，提高并发能力

## 安装步骤

1. 克隆项目仓库：

```bash
git clone https://github.com/your-username/ICmanager.git
cd ICmanager
```

2. 安装依赖包：

```bash
pip install -r requirements.txt
```

## 使用方法

### 初始化数据库

在使用系统前，需先初始化数据库：

```bash
# 初始化数据库（不含示例数据）
python init_db.py

# 初始化数据库并包含示例数据
python init_db.py -s

# 指定数据库文件名
python init_db.py -d my_database.db -s
```

### 启动服务器

启动HTTP服务器，监听读卡器请求：

```bash
python http_reader.py
```

服务器默认在88端口启动，与读卡器默认端口一致。

### 运行测试

系统提供了完整的测试套件，包括数据库操作测试、通信协议测试、完整流程测试和并发测试：

```bash
# 运行所有测试
python run_tests.py

# 运行特定测试
python run_tests.py database  # 数据库测试
python run_tests.py protocol  # 协议测试
python run_tests.py integration  # 集成测试
python run_tests.py concurrency  # 并发测试
```

## 系统结构

- `http_reader.py` - 主服务器实现，处理HTTP请求和数据库操作
- `init_db.py` - 数据库初始化脚本
- `run_tests.py` - 测试运行脚本
- `test_units/` - 测试单元目录
  - `test_database.py` - 数据库操作测试
  - `test_protocol.py` - 通信协议测试
  - `test_integration.py` - 完整流程测试
  - `test_concurrency.py` - 并发测试

## 数据库设计

系统使用SQLite数据库，包含以下表：

1. **卡片管理表 (kbk_ic_manager)**
   - 存储卡片信息和状态

2. **计数表**
   - **中文计数表 (kbk_ic_cn_count)**
   - **英语计数表 (kbk_ic_en_count)**
   - **其他语言计数表 (kbk_ic_nm_count)**

3. **失败记录表 (kbk_ic_failure_records)**
   - 记录刷卡失败的情况

## 通信协议

系统接收的HTTP请求参数：
- `info`: 数据包序号
- `jihao`: 设备机号(1-中文, 2-英文, 3-其他)
- `card`: 卡号(16进制格式)
- `dn`: 设备序列号
- `heartbeattype`: 心跳包标识

系统返回的响应格式：
```
Response=1,info,显示文字,显示时间,蜂鸣序号,TTS语音内容,继电器1开启时间,继电器2开启时间
```

## 问题与支持

如有任何问题或需要支持，请提交issue或联系系统管理员。

## 许可证

本项目采用 MIT 许可证 - 详情请参阅 LICENSE 文件。
