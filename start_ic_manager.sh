#!/bin/bash

# IC Manager Streamlit服务启动脚本

echo "启动IC Manager管理界面..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3命令"
    exit 1
fi

# 检查streamlit是否安装
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "正在安装依赖..."
    pip3 install -r requirements.txt
fi

# 设置环境变量
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 启动Streamlit服务
echo "启动Streamlit服务，访问地址: http://localhost:8501"
streamlit run ic_manager_server.py --server.port=8501 --server.address=0.0.0.0