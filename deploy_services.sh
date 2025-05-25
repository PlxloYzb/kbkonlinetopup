#!/bin/bash

# 定义服务名称数组
SERVICES=("status_update_server" "manager_server" "http_reader")

# 检查是否以root运行
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "错误：此脚本需要root权限运行"
        exit 1
    fi
}

# 部署服务文件
deploy_services() {
    echo "正在部署服务文件..."
    for service in "${SERVICES[@]}"; do
        cp "./${service}.service" "/etc/systemd/system/" && \
        chmod 644 "/etc/systemd/system/${service}.service"
        echo "  [✓] ${service}.service 部署成功"
    done
    
    systemctl daemon-reload
    echo "系统服务配置已重载"
}

# 启用服务
enable_services() {
    for service in "${SERVICES[@]}"; do
        systemctl enable "${service}.service" >/dev/null 2>&1
        echo "  [✓] ${service} 服务已设置开机启动"
    done
}

# 启动服务
start_services() {
    for service in "${SERVICES[@]}"; do
        systemctl start "${service}.service"
        echo "  [✓] ${service} 服务已启动"
    done
}

# 停止服务
stop_services() {
    for service in "${SERVICES[@]}"; do
        systemctl stop "${service}.service"
        echo "  [✓] ${service} 服务已停止"
    done
}

# 重启服务
restart_services() {
    for service in "${SERVICES[@]}"; do
        systemctl restart "${service}.service"
        echo "  [✓] ${service} 服务已重启"
    done
}

# 查看状态
status_services() {
    for service in "${SERVICES[@]}"; do
        echo -e "\n====== ${service} 状态 ======"
        systemctl status "${service}.service" --no-pager -l
    done
}

# 查看日志
show_logs() {
    journalctl -u ${SERVICES[0]}.service -u ${SERVICES[1]}.service -u ${SERVICES[2]}.service -n 50 --no-pager -o cat
}

# 主菜单
main_menu() {
    echo -e "\n===== 服务管理脚本 ====="
    echo "1. 部署所有服务"
    echo "2. 启动所有服务"
    echo "3. 停止所有服务"
    echo "4. 重启所有服务"
    echo "5. 查看服务状态"
    echo "6. 查看最近日志"
    echo "7. 设置开机启动"
    echo "8. 退出"
    read -p "请选择操作 (1-8): " choice

    case $choice in
        1) check_root; deploy_services ;;
        2) check_root; start_services ;;
        3) check_root; stop_services ;;
        4) check_root; restart_services ;;
        5) status_services ;;
        6) show_logs ;;
        7) check_root; enable_services ;;
        8) exit 0 ;;
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