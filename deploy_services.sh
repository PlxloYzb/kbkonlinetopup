#!/bin/bash

# ========================================
# 服务管理脚本 - 支持依赖顺序启动
# ========================================
# 
# 重要说明：
# 服务之间存在依赖关系，必须按照特定顺序启动：
# 1. http_reader       - HTTP接口读取器（基础服务）
# 2. status_update_server - 状态更新服务（依赖http_reader）
# 3. dispatch_server   - 调度服务（依赖前两个服务）
# 4. manager_server    - 管理服务（依赖所有其他服务）
#
# 停止时按相反顺序进行，以避免依赖冲突
# ========================================

# 定义服务名称数组（用于通用操作）
SERVICES=("status_update_server" "manager_server" "http_reader" "dispatch_server")

# 定义服务启动顺序（重要：必须按照依赖关系启动）
START_ORDER=("http_reader" "status_update_server" "dispatch_server" "manager_server")

# 定义服务停止顺序（启动顺序的反向）
STOP_ORDER=("manager_server" "dispatch_server" "status_update_server" "http_reader")

# 定义备份目录
BACKUP_DIR="/tmp/systemd_backup_$(date +%Y%m%d_%H%M%S)"
SYSTEM_SERVICE_DIR="/etc/systemd/system"

# 检查是否以root运行
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "错误：此脚本需要root权限运行"
        exit 1
    fi
}

# 创建备份目录
create_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    echo "创建备份目录: $BACKUP_DIR"
}

# 备份现有服务文件
backup_existing_services() {
    echo "正在备份现有服务文件..."
    create_backup_dir
    
    # 备份当前已安装的服务文件
    for service in "${SERVICES[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            cp "$SYSTEM_SERVICE_DIR/${service}.service" "$BACKUP_DIR/"
            echo "  [✓] 已备份 ${service}.service"
        fi
    done
    
    # 记录当前启用的服务状态
    echo "# 服务状态备份 - $(date)" > "$BACKUP_DIR/service_status.txt"
    for service in "${SERVICES[@]}"; do
        if systemctl is-enabled "${service}.service" >/dev/null 2>&1; then
            echo "${service}=enabled" >> "$BACKUP_DIR/service_status.txt"
        else
            echo "${service}=disabled" >> "$BACKUP_DIR/service_status.txt"
        fi
        
        if systemctl is-active "${service}.service" >/dev/null 2>&1; then
            echo "${service}_active=true" >> "$BACKUP_DIR/service_status.txt"
        else
            echo "${service}_active=false" >> "$BACKUP_DIR/service_status.txt"
        fi
    done
    
    echo "备份信息已保存到: $BACKUP_DIR/service_status.txt"
}

# 部署服务文件
deploy_services() {
    echo "正在部署服务文件..."
    backup_existing_services
    
    for service in "${SERVICES[@]}"; do
        if [ -f "./${service}.service" ]; then
            cp "./${service}.service" "$SYSTEM_SERVICE_DIR/" && \
            chmod 644 "$SYSTEM_SERVICE_DIR/${service}.service"
            echo "  [✓] ${service}.service 部署成功"
        else
            echo "  [!] 警告: ${service}.service 文件不存在，跳过部署"
        fi
    done
    
    systemctl daemon-reload
    echo "系统服务配置已重载"
    echo "备份目录: $BACKUP_DIR"
}

# 启用服务
enable_services() {
    echo "正在启用服务..."
    for service in "${SERVICES[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            systemctl enable "${service}.service" >/dev/null 2>&1
            echo "  [✓] ${service} 服务已设置开机启动"
        else
            echo "  [!] ${service}.service 不存在，跳过启用"
        fi
    done
}

# 启动服务（按依赖顺序）
start_services() {
    echo "正在按顺序启动服务..."
    echo "启动顺序：${START_ORDER[*]}"
    
    for service in "${START_ORDER[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            echo "  正在启动 ${service}..."
            systemctl start "${service}.service"
            
            # 等待服务启动
            local wait_count=0
            local max_wait=30
            while [ $wait_count -lt $max_wait ]; do
                if systemctl is-active "${service}.service" >/dev/null 2>&1; then
                    echo "  [✓] ${service} 服务已启动"
                    break
                fi
                sleep 1
                wait_count=$((wait_count + 1))
            done
            
            if [ $wait_count -eq $max_wait ]; then
                echo "  [✗] ${service} 服务启动超时"
                echo "  [!] 停止后续服务启动以避免依赖问题"
                return 1
            fi
            
            # 服务启动后等待2秒再启动下一个
            sleep 2
        else
            echo "  [!] ${service}.service 不存在，跳过启动"
        fi
    done
    
    echo "所有服务已按顺序启动完成"
}

# 停止服务（按相反顺序）
stop_services() {
    echo "正在按顺序停止服务..."
    echo "停止顺序：${STOP_ORDER[*]}"
    
    for service in "${STOP_ORDER[@]}"; do
        if systemctl is-active "${service}.service" >/dev/null 2>&1; then
            echo "  正在停止 ${service}..."
            systemctl stop "${service}.service"
            
            # 等待服务停止
            local wait_count=0
            local max_wait=15
            while [ $wait_count -lt $max_wait ]; do
                if ! systemctl is-active "${service}.service" >/dev/null 2>&1; then
                    echo "  [✓] ${service} 服务已停止"
                    break
                fi
                sleep 1
                wait_count=$((wait_count + 1))
            done
            
            if [ $wait_count -eq $max_wait ]; then
                echo "  [!] ${service} 服务停止超时，强制终止"
                systemctl kill "${service}.service"
                sleep 1
            fi
        else
            echo "  [!] ${service} 服务未运行"
        fi
    done
    
    echo "所有服务已按顺序停止完成"
}

# 重启服务（先停止所有服务，再按顺序启动）
restart_services() {
    echo "正在重启服务..."
    
    # 先按顺序停止所有服务
    stop_services
    
    echo "等待3秒后开始启动服务..."
    sleep 3
    
    # 再按顺序启动所有服务
    start_services
}

# 查看状态
status_services() {
    echo "正在查看服务状态..."
    for service in "${SERVICES[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            echo -e "\n====== ${service} 状态 ======"
            systemctl status "${service}.service" --no-pager -l
        else
            echo -e "\n====== ${service} ======"
            echo "服务文件不存在"
        fi
    done
}

# 查看日志
show_logs() {
    echo "正在查看最近日志..."
    local log_units=""
    for service in "${SERVICES[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            log_units="$log_units -u ${service}.service"
        fi
    done
    
    if [ -n "$log_units" ]; then
        journalctl $log_units -n 50 --no-pager -o cat
    else
        echo "没有找到已部署的服务"
    fi
}

# 回退服务
rollback_services() {
    echo "请输入备份目录路径 (例如: /tmp/systemd_backup_20231201_143022):"
    read -p "备份目录: " backup_path
    
    if [ ! -d "$backup_path" ]; then
        echo "错误：备份目录不存在: $backup_path"
        return 1
    fi
    
    if [ ! -f "$backup_path/service_status.txt" ]; then
        echo "错误：备份目录中没有找到service_status.txt文件"
        return 1
    fi
    
    echo "正在回退服务..."
    
    # 停止当前服务
    stop_services
    
    # 禁用当前服务
    for service in "${SERVICES[@]}"; do
        if systemctl is-enabled "${service}.service" >/dev/null 2>&1; then
            systemctl disable "${service}.service" >/dev/null 2>&1
            echo "  [✓] 已禁用 ${service} 服务"
        fi
    done
    
    # 删除当前服务文件
    for service in "${SERVICES[@]}"; do
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            rm -f "$SYSTEM_SERVICE_DIR/${service}.service"
            echo "  [✓] 已删除 ${service}.service"
        fi
    done
    
    # 恢复备份的服务文件
    for service_file in "$backup_path"/*.service; do
        if [ -f "$service_file" ]; then
            cp "$service_file" "$SYSTEM_SERVICE_DIR/"
            chmod 644 "$SYSTEM_SERVICE_DIR/$(basename "$service_file")"
            echo "  [✓] 已恢复 $(basename "$service_file")"
        fi
    done
    
    systemctl daemon-reload
    echo "系统服务配置已重载"
    
    # 恢复服务状态
    while IFS='=' read -r service_key service_value; do
        if [[ "$service_key" =~ ^([^_]+)$ ]]; then
            service_name="${BASH_REMATCH[1]}"
            if [ "$service_value" = "enabled" ] && [ -f "$SYSTEM_SERVICE_DIR/${service_name}.service" ]; then
                systemctl enable "${service_name}.service" >/dev/null 2>&1
                echo "  [✓] 已启用 ${service_name} 服务"
            fi
        elif [[ "$service_key" =~ ^([^_]+)_active$ ]]; then
            service_name="${BASH_REMATCH[1]}"
            if [ "$service_value" = "true" ] && [ -f "$SYSTEM_SERVICE_DIR/${service_name}.service" ]; then
                systemctl start "${service_name}.service"
                echo "  [✓] 已启动 ${service_name} 服务"
            fi
        fi
    done < "$backup_path/service_status.txt"
    
    echo "服务回退完成"
}

# 列出备份目录
list_backups() {
    echo "可用的备份目录："
    ls -la /tmp/systemd_backup_* 2>/dev/null | grep "^d" || echo "没有找到备份目录"
}

# 完整的部署流程（推荐）
full_deploy() {
    echo "===== 开始完整部署流程 ====="
    check_root
    
    # 1. 验证服务文件存在
    echo "1. 验证服务文件..."
    missing_files=()
    for service in "${SERVICES[@]}"; do
        if [ ! -f "./${service}.service" ]; then
            missing_files+=("${service}.service")
        fi
    done
    
    if [ ${#missing_files[@]} -gt 0 ]; then
        echo "警告：以下服务文件不存在："
        for file in "${missing_files[@]}"; do
            echo "  - $file"
        done
        read -p "是否继续？(y/n): " continue_deploy
        if [ "$continue_deploy" != "y" ]; then
            echo "部署已取消"
            return 1
        fi
    fi
    
    # 2. 部署服务文件（包含备份）
    echo "2. 部署服务文件..."
    deploy_services
    
    # 3. 启用服务
    echo "3. 启用服务..."
    enable_services
    
    # 4. 启动服务
    echo "4. 启动服务..."
    start_services
    
    # 5. 检查状态
    echo "5. 检查服务状态..."
    status_services
    
    echo "===== 完整部署流程完成 ====="
}

# 查看服务启动顺序
show_startup_order() {
    echo "===== 服务启动和停止顺序 ====="
    echo "启动顺序（必须按此顺序启动以满足依赖关系）："
    for i in "${!START_ORDER[@]}"; do
        echo "  $((i+1)). ${START_ORDER[$i]}"
    done
    
    echo ""
    echo "停止顺序（启动顺序的反向）："
    for i in "${!STOP_ORDER[@]}"; do
        echo "  $((i+1)). ${STOP_ORDER[$i]}"
    done
    
    echo ""
    echo "说明："
    echo "- http_reader: HTTP接口读取器服务（基础服务）"
    echo "- status_update_server: 状态更新服务（依赖http_reader）"
    echo "- dispatch_server: 调度服务（依赖前两个服务）"
    echo "- manager_server: 管理服务（依赖所有其他服务）"
}

# 单独启动某个服务
start_single_service() {
    echo "可用的服务："
    for i in "${!SERVICES[@]}"; do
        echo "  $((i+1)). ${SERVICES[$i]}"
    done
    
    read -p "请选择要启动的服务编号 (1-${#SERVICES[@]}): " choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#SERVICES[@]} ]; then
        local service="${SERVICES[$((choice-1))]}"
        echo "正在启动 $service 服务..."
        
        if [ -f "$SYSTEM_SERVICE_DIR/${service}.service" ]; then
            systemctl start "${service}.service"
            sleep 2
            if systemctl is-active "${service}.service" >/dev/null 2>&1; then
                echo "  [✓] $service 服务启动成功"
            else
                echo "  [✗] $service 服务启动失败"
                echo "查看错误日志："
                journalctl -u "${service}.service" -n 10 --no-pager
            fi
        else
            echo "  [!] ${service}.service 文件不存在"
        fi
    else
        echo "无效选择"
    fi
}

# 单独停止某个服务
stop_single_service() {
    echo "当前运行的服务："
    local running_services=()
    for service in "${SERVICES[@]}"; do
        if systemctl is-active "${service}.service" >/dev/null 2>&1; then
            running_services+=("$service")
            echo "  ${#running_services[@]}. $service (运行中)"
        fi
    done
    
    if [ ${#running_services[@]} -eq 0 ]; then
        echo "没有正在运行的服务"
        return
    fi
    
    read -p "请选择要停止的服务编号 (1-${#running_services[@]}): " choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#running_services[@]} ]; then
        local service="${running_services[$((choice-1))]}"
        echo "正在停止 $service 服务..."
        
        systemctl stop "${service}.service"
        sleep 2
        if ! systemctl is-active "${service}.service" >/dev/null 2>&1; then
            echo "  [✓] $service 服务已停止"
        else
            echo "  [!] $service 服务停止失败，尝试强制终止"
            systemctl kill "${service}.service"
        fi
    else
        echo "无效选择"
    fi
}

# 运行前测试
pre_deploy_test() {
    echo "===== 部署前测试 ====="
    
    echo "1. 检查服务文件语法..."
    for service in "${SERVICES[@]}"; do
        if [ -f "./${service}.service" ]; then
            systemd-analyze verify "./${service}.service" 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "  [✓] ${service}.service 语法正确"
            else
                echo "  [✗] ${service}.service 语法错误"
                systemd-analyze verify "./${service}.service"
            fi
        else
            echo "  [!] ${service}.service 文件不存在"
        fi
    done
    
    echo "2. 检查Python脚本是否存在..."
    for service in "${SERVICES[@]}"; do
        if [ -f "./${service}.py" ]; then
            echo "  [✓] ${service}.py 存在"
        else
            echo "  [!] ${service}.py 不存在"
        fi
    done
    
    echo "3. 检查conda环境..."
    if [ -f "/home/bruceplxl/miniconda3/bin/activate" ]; then
        echo "  [✓] Conda环境可用"
    else
        echo "  [✗] Conda环境不可用"
    fi
}

# 主菜单
main_menu() {
    echo -e "\n===== 服务管理脚本（支持依赖顺序启动）====="
    echo "基本操作："
    echo "1. 完整部署流程（推荐）"
    echo "2. 仅部署服务文件"
    echo "3. 按顺序启动所有服务"
    echo "4. 按顺序停止所有服务"
    echo "5. 按顺序重启所有服务"
    echo "6. 查看服务状态"
    echo "7. 查看最近日志"
    echo "8. 设置开机启动"
    echo ""
    echo "单独操作："
    echo "9. 启动单个服务"
    echo "10. 停止单个服务"
    echo "11. 查看启动顺序说明"
    echo ""
    echo "高级操作："
    echo "12. 回退服务"
    echo "13. 列出备份目录"
    echo "14. 部署前测试"
    echo "15. 退出"
    read -p "请选择操作 (1-15): " choice

    case $choice in
        1) full_deploy ;;
        2) check_root; deploy_services ;;
        3) check_root; start_services ;;
        4) check_root; stop_services ;;
        5) check_root; restart_services ;;
        6) status_services ;;
        7) show_logs ;;
        8) check_root; enable_services ;;
        9) check_root; start_single_service ;;
        10) check_root; stop_single_service ;;
        11) show_startup_order ;;
        12) check_root; rollback_services ;;
        13) list_backups ;;
        14) pre_deploy_test ;;
        15) exit 0 ;;
        *) echo "无效输入"; main_menu ;;
    esac
}

# 创建服务文件模板（如果不存在）
create_template_files() {
    for service in "${SERVICES[@]}"; do
        if [ ! -f "./${service}.service" ]; then
            echo "检测到缺少 ${service}.service 文件"
            read -p "是否创建模板文件？(y/n): " create
            if [ "$create" = "y" ]; then
                cat > "./${service}.service" <<EOF
[Unit]
Description=${service}服务
After=network.target

[Service]
Type=simple
User=bruceplxl
WorkingDirectory=/home/bruceplxl/deploy/kbkonlinetopup
ExecStart=/bin/bash -c 'source /home/bruceplxl/miniconda3/bin/activate kbkonlinetopup && python ${service}.py'
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=${service}
Environment=PYTHONUNBUFFERED=1
ProtectSystem=full
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
                echo "已创建 ${service}.service 模板文件"
            fi
        fi
    done
}

# 初始检查
create_template_files
main_menu