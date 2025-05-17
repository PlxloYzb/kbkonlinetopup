# 状态更新服务测试套件

这个测试套件用于测试状态更新服务器(`status_update_server.py`)的功能。

## 测试脚本说明

测试套件包含以下脚本：

1. `init_db.py` - 创建SQLite数据库并添加示例数据
2. `test_server.py` - 测试服务器的各项功能
3. `run_tests.py` - 集成测试脚本，用于运行完整的测试流程

## 依赖项

测试需要以下Python依赖：

```
pandas
schedule
aiohttp
prometheus_client
aiosqlite
watchdog
```

## 测试方法

### 方法一：运行所有测试

```bash
python run_tests.py
```

这将执行以下步骤：
1. 检查并安装所需依赖
2. 创建测试数据库和示例数据
3. 运行服务器功能测试

### 方法二：只创建测试数据库

```bash
python run_tests.py --init-only
```

这将只执行初始化数据库和创建示例数据的步骤。

### 方法三：只运行服务器测试

```bash
python run_tests.py --test-only
```

这将跳过初始化步骤，直接运行服务器功能测试。

### 方法四：运行集成测试

```bash
python run_tests.py --integration
```

这将创建测试数据并运行一个简化的集成测试，测试服务器的核心更新功能。

## 单独使用初始化脚本

如果只需要创建一个包含示例数据的数据库和Excel文件，可以直接运行：

```bash
python init_db.py
```

这将创建：
1. SQLite数据库文件: `test_database.db`
2. 示例Excel排班文件: `test_excel/YYYY-MM-DD.xlsx`

## 测试内容

测试套件测试以下功能：

1. **数据库操作**
   - 创建和连接数据库
   - 批量更新用户状态
   
2. **文件处理**
   - 检测新的Excel文件
   - 读取并解析Excel数据
   - 文件变化监控
   
3. **服务核心功能**
   - 服务初始化和配置
   - 根据时间点触发更新
   - 按部门处理数据
   - 状态更新逻辑
   
4. **HTTP API**
   - 健康状态API
   
5. **异常处理**
   - 检测和报告错误
   - 健康状态监控

## 注意事项

1. 测试套件会创建临时文件和数据库，测试完成后会自动清理
2. 如果您已经有了自己的数据库或Excel文件，可以修改脚本中的路径配置
3. 服务器的监控端口默认为8000，HTTP端口默认为8080，请确保这些端口未被占用 