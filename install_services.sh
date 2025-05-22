#!/bin/bash

# 安装服务脚本
# 用于安装systemd服务单元文件并启用服务

# 确保以root权限运行
if [ "$EUID" -ne 0 ]; then
  echo "请使用sudo运行此脚本"
  exit 1
fi

# 变量设置
CURRENT_USER=$(whoami)
WORK_DIR=$(pwd)
echo "当前用户: $CURRENT_USER"
echo "工作目录: $WORK_DIR"

# 创建日志目录
mkdir -p $WORK_DIR/logs
echo "创建日志目录完成"

# 替换服务文件中的用户名和工作目录路径
for SERVICE in status_update_server manager_server http_reader; do
  # 替换用户名
  sed -i.bak "s|\${USER}|$CURRENT_USER|g" ${SERVICE}.service
  
  # 替换工作目录变量
  sed -i.bak "s|\${WORK_DIR}|$WORK_DIR|g" ${SERVICE}.service
  
  echo "更新 ${SERVICE}.service 中的路径和用户名"
done

# 将服务文件复制到systemd目录
for SERVICE in status_update_server manager_server http_reader; do
  cp ${SERVICE}.service /etc/systemd/system/
  echo "已复制 ${SERVICE}.service 到systemd目录"
done

# 重新加载systemd配置
systemctl daemon-reload
echo "systemd配置已重新加载"

# 启用服务（开机自启）
for SERVICE in status_update_server manager_server http_reader; do
  systemctl enable ${SERVICE}.service
  echo "已启用 ${SERVICE} 服务开机自启"
done

echo ""
echo "是否现在启动所有服务? (y/n)"
read -r ANSWER
if [ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ]; then
  for SERVICE in status_update_server manager_server http_reader; do
    systemctl start ${SERVICE}.service
    echo "已启动 ${SERVICE} 服务"
  done
fi

echo ""
echo "服务安装完成!"
echo "可用命令:"
echo "  启动: sudo systemctl start [服务名].service"
echo "  停止: sudo systemctl stop [服务名].service"
echo "  重启: sudo systemctl restart [服务名].service"
echo "  状态: sudo systemctl status [服务名].service"
echo "  查看日志: sudo journalctl -u [服务名].service"
echo ""
echo "例如: sudo systemctl status status_update_server.service" 