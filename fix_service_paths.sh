#!/bin/bash

# 服务文件路径修复脚本
# 用于修复服务文件中的路径配置问题

echo "===== 服务文件路径修复脚本 ====="

# 获取当前目录
CURRENT_DIR=$(pwd)
echo "当前工作目录: $CURRENT_DIR"

# 获取用户名
CURRENT_USER=$(whoami)
echo "当前用户: $CURRENT_USER"

# 检测conda环境路径
CONDA_PATHS=(
    "/home/$CURRENT_USER/miniconda3/bin/activate"
    "/home/$CURRENT_USER/anaconda3/bin/activate"
    "/opt/miniconda3/bin/activate"
    "/opt/anaconda3/bin/activate"
    "$HOME/miniconda3/bin/activate"
    "$HOME/anaconda3/bin/activate"
)

CONDA_PATH=""
for path in "${CONDA_PATHS[@]}"; do
    if [ -f "$path" ]; then
        CONDA_PATH="$path"
        echo "找到conda环境: $CONDA_PATH"
        break
    fi
done

if [ -z "$CONDA_PATH" ]; then
    echo "警告：未找到conda环境，请手动指定路径"
    read -p "请输入conda activate脚本的完整路径: " CONDA_PATH
fi

# 获取conda环境名称
read -p "请输入conda环境名称 [默认: kbkonlinetopup]: " ENV_NAME
ENV_NAME=${ENV_NAME:-kbkonlinetopup}

# 定义服务文件
SERVICES=("status_update_server" "manager_server" "http_reader" "dispatch_server")

echo -e "\n===== 开始修复服务文件 ====="

# 备份原始文件
echo "1. 备份原始服务文件..."
for service in "${SERVICES[@]}"; do
    if [ -f "${service}.service" ]; then
        cp "${service}.service" "${service}.service.backup.$(date +%Y%m%d_%H%M%S)"
        echo "  [✓] 已备份 ${service}.service"
    fi
done

# 修复路径
echo "2. 修复服务文件路径..."

# 修复通用服务文件
for service in "status_update_server" "manager_server" "http_reader"; do
    if [ -f "${service}.service" ]; then
        echo "  正在修复 ${service}.service..."
        
        # 替换WorkingDirectory
        sed -i "s|WorkingDirectory=.*|WorkingDirectory=$CURRENT_DIR|g" "${service}.service"
        
        # 替换ExecStart中的conda路径
        sed -i "s|source .*/activate|source $CONDA_PATH|g" "${service}.service"
        
        # 替换用户名（如果需要）
        if [ "$service" != "http_reader" ]; then
            sed -i "s|User=.*|User=$CURRENT_USER|g" "${service}.service"
        fi
        
        echo "    [✓] ${service}.service 修复完成"
    else
        echo "    [!] ${service}.service 不存在"
    fi
done

# 特殊处理 dispatch_server（使用streamlit）
if [ -f "dispatch_server.service" ]; then
    echo "  正在修复 dispatch_server.service..."
    
    # 替换WorkingDirectory
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=$CURRENT_DIR|g" "dispatch_server.service"
    
    # 替换ExecStart中的conda路径
    sed -i "s|source .*/activate|source $CONDA_PATH|g" "dispatch_server.service"
    
    # 替换用户名
    sed -i "s|User=.*|User=$CURRENT_USER|g" "dispatch_server.service"
    
    echo "    [✓] dispatch_server.service 修复完成"
else
    echo "    [!] dispatch_server.service 不存在"
fi



echo -e "\n3. 验证修复结果..."

# 验证文件内容
for service in "${SERVICES[@]}"; do
    if [ -f "${service}.service" ]; then
        echo -e "\n====== ${service}.service ======"
        echo "WorkingDirectory: $(grep "WorkingDirectory" "${service}.service")"
        echo "User: $(grep "User=" "${service}.service")"
        echo "ExecStart: $(grep "ExecStart" "${service}.service")"
    fi
done

echo -e "\n===== 修复完成 ====="
echo "请检查上述输出，确认路径是否正确"
echo "如果需要恢复原始文件，可以使用备份文件（*.backup.*）"

# 询问是否运行语法检查
read -p "是否运行systemd语法检查？(y/n): " run_check
if [ "$run_check" = "y" ]; then
    echo -e "\n===== systemd 语法检查 ====="
    for service in "${SERVICES[@]}"; do
        if [ -f "${service}.service" ]; then
            echo "检查 ${service}.service..."
            systemd-analyze verify "${service}.service" 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "  [✓] 语法正确"
            else
                echo "  [✗] 语法错误:"
                systemd-analyze verify "${service}.service"
            fi
        fi
    done
fi

echo -e "\n完成！现在可以运行 deploy_services.sh 进行部署。" 