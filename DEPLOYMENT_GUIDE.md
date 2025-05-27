# 服务部署指南

## 概述

该部署脚本已经过改进，支持以下功能：
- **自动备份与回退**：每次部署前自动备份现有服务状态
- **多服务支持**：支持 `status_update_server`、`manager_server`、`http_reader`、`dispatch_server`
- **状态检查**：部署前后的状态验证
- **错误处理**：完善的错误处理和日志记录

## 🔍 发现的服务文件问题

根据检查，发现以下需要注意的问题：

### 1. WorkingDirectory 路径不一致
```bash
# 大部分服务使用：
WorkingDirectory=/home/bruceplxl/deploy/kbkonlinetopup

# 但实际项目在：
/Users/bruceplxl/Dev/ICmanager
```

### 2. User 配置不统一
- `http_reader.service`: `User=root`
- 其他服务: `User=bruceplxl`



## 📋 部署前准备清单

### 1. 更新服务文件路径
所有 `.service` 文件中的路径需要更新为：
```bash
WorkingDirectory=/Users/bruceplxl/Dev/ICmanager
```

### 2. 检查Python环境
确认conda环境路径：
```bash
# 检查conda是否在此路径
ls -la /home/bruceplxl/miniconda3/bin/activate
```

### 3. 验证Python脚本存在
```bash
# 检查所有Python脚本是否存在
ls -la *.py | grep -E "(status_update_server|manager_server|http_reader|dispatch_server).py"
```

## 🚀 部署流程

### 方式一：完整部署（推荐）
```bash
sudo ./deploy_services.sh
# 选择选项 1: 完整部署流程（推荐）
```

完整部署会执行：
1. ✅ 验证服务文件存在性
2. 🔄 自动备份现有服务状态
3. 📁 部署新的服务文件
4. ⚡ 启用服务（开机自启）
5. ▶️ 启动服务
6. 📊 检查服务状态

### 方式二：分步部署
```bash
sudo ./deploy_services.sh
# 选择选项 11: 部署前测试
# 选择选项 2: 仅部署服务文件
# 选择选项 8: 设置开机启动
# 选择选项 3: 启动所有服务
```

## 🔧 测试验证

### 1. 部署前测试
```bash
sudo ./deploy_services.sh
# 选择选项 11: 部署前测试
```

测试内容：
- ✅ systemd 服务文件语法检查
- 📄 Python脚本文件存在性检查
- 🐍 Conda环境可用性检查

### 2. 状态检查
```bash
sudo ./deploy_services.sh
# 选择选项 6: 查看服务状态
```

### 3. 日志检查
```bash
sudo ./deploy_services.sh
# 选择选项 7: 查看最近日志
```

### 4. 手动验证
```bash
# 检查服务状态
sudo systemctl status status_update_server.service
sudo systemctl status manager_server.service
sudo systemctl status http_reader.service
sudo systemctl status dispatch_server.service

# 检查端口占用（如果服务有网络端口）
netstat -tlnp | grep python
netstat -tlnp | grep streamlit  # dispatch_server 使用 streamlit
```

## 🔄 回退操作

### 查看备份目录
```bash
sudo ./deploy_services.sh
# 选择选项 10: 列出备份目录
```

### 执行回退
```bash
sudo ./deploy_services.sh
# 选择选项 9: 回退服务
# 输入备份目录路径，例如：/tmp/systemd_backup_20231201_143022
```

回退过程：
1. 🛑 停止当前所有服务
2. ❌ 禁用当前所有服务
3. 🗑️ 删除当前服务文件
4. 📂 恢复备份的服务文件
5. ⚡ 恢复服务启用状态
6. ▶️ 恢复服务运行状态

## 📝 常见问题和解决方案

### 1. 权限错误
```bash
# 确保以root身份运行
sudo ./deploy_services.sh
```

### 2. 服务启动失败
```bash
# 查看详细错误信息
sudo journalctl -u <service_name>.service -f

# 检查Python环境
sudo -u bruceplxl bash -c 'source /home/bruceplxl/miniconda3/bin/activate kbkonlinetopup && python --version'
```

### 3. 端口冲突
```bash
# 检查端口占用
netstat -tlnp | grep <port_number>

# 停止占用端口的进程
sudo kill -9 <pid>
```

### 4. 路径错误
检查并更新 `.service` 文件中的：
- `WorkingDirectory`
- `ExecStart` 中的路径
- conda环境路径

## 🔐 安全注意事项

1. **备份重要性**：每次部署都会自动备份，但建议额外手动备份重要配置
2. **权限最小化**：除了需要root权限的http_reader，其他服务都以普通用户运行
3. **目录权限**：确保服务用户对工作目录有适当权限
4. **网络安全**：检查服务是否只监听必要的端口和地址

## 📊 监控和维护

### 定期检查
```bash
# 每日状态检查
sudo systemctl status status_update_server manager_server http_reader dispatch_server

# 每周日志清理
sudo journalctl --vacuum-time=7d

# 备份清理（保留最近30天）
find /tmp/systemd_backup_* -type d -mtime +30 -exec rm -rf {} \;
```

### 性能监控
```bash
# 检查内存使用
ps aux | grep python | grep -E "(status_update|manager_server|http_reader|dispatch_server)"

# 检查CPU使用
top -p $(pgrep -f "status_update_server|manager_server|http_reader|dispatch_server" | tr '\n' ',' | sed 's/,$//')
```

## 📞 故障排除快速参考

| 问题 | 命令 | 说明 |
|------|------|------|
| 服务无法启动 | `sudo journalctl -u <service>.service -f` | 查看实时日志 |
| 权限错误 | `sudo chown -R bruceplxl:bruceplxl /path/to/workdir` | 修复目录权限 |
| 端口占用 | `sudo netstat -tlnp \| grep <port>` | 检查端口使用 |
| 环境变量问题 | `sudo -u bruceplxl env` | 检查用户环境 |
| 服务依赖 | `sudo systemctl list-dependencies <service>` | 查看服务依赖 |

---

**重要提醒**：在生产环境部署前，请务必在测试环境验证所有功能！ 