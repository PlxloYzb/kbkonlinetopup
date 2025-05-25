#!/bin/bash

# 启动余额管理系统脚本

# 确保python环境正常
if ! command -v python3 &> /dev/null
then
    echo "未找到python3. 请确保已安装python3."
    exit 1
fi

# 确保所需目录存在
if [ ! -d "excel" ]; then
    echo "创建excel目录..."
    mkdir -p excel
    echo "已创建excel目录。"
fi

# 获取当前目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# 设置日志文件
LOG_FILE="$SCRIPT_DIR/balance_manager.log"

echo "===== $(date) =====" >> "$LOG_FILE"
echo "启动余额管理系统..." >> "$LOG_FILE"

# 启动余额管理系统
nohup python3 "$SCRIPT_DIR/balance_manager.py" >> "$LOG_FILE" 2>&1 &
PID=$!

echo "余额管理系统已启动，进程ID: $PID"
echo "启动进程ID: $PID" >> "$LOG_FILE"
echo "可以通过查看 $LOG_FILE 获取运行日志"
echo "使用 'kill $PID' 停止服务"

# 将PID写入文件方便后续停止服务
echo $PID > "$SCRIPT_DIR/.balance_manager.pid"
