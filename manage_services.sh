#!/bin/bash

# 服务列表
SERVICES="status_update_server manager_server http_reader"

# 显示用法信息
function show_usage() {
  echo "用法: $0 {start|stop|restart|status|logs}"
  echo "  start   - 启动所有服务"
  echo "  stop    - 停止所有服务"
  echo "  restart - 重启所有服务"
  echo "  status  - 显示所有服务状态"
  echo "  logs    - 查看所有服务的日志"
  exit 1
}

# 检查是否提供了参数
if [ $# -eq 0 ]; then
  show_usage
fi

# 根据命令执行操作
case "$1" in
  start)
    for SERVICE in $SERVICES; do
      echo "启动 $SERVICE..."
      sudo systemctl start $SERVICE.service
    done
    echo "所有服务已启动"
    ;;
  stop)
    for SERVICE in $SERVICES; do
      echo "停止 $SERVICE..."
      sudo systemctl stop $SERVICE.service
    done
    echo "所有服务已停止"
    ;;
  restart)
    for SERVICE in $SERVICES; do
      echo "重启 $SERVICE..."
      sudo systemctl restart $SERVICE.service
    done
    echo "所有服务已重启"
    ;;
  status)
    for SERVICE in $SERVICES; do
      echo "===== $SERVICE 状态 ====="
      sudo systemctl status $SERVICE.service
      echo ""
    done
    ;;
  logs)
    echo "查看哪个服务的日志？"
    select SERVICE in $SERVICES "所有服务" "退出"; do
      case $SERVICE in
        "所有服务")
          for S in $SERVICES; do
            echo "===== $S 的最近日志 ====="
            sudo journalctl -u $S.service -n 20 --no-pager
            echo ""
          done
          break
          ;;
        "退出")
          exit 0
          ;;
        *)
          if [ -n "$SERVICE" ]; then
            echo "按Ctrl+C退出日志查看"
            sudo journalctl -u $SERVICE.service -f
            break
          fi
          ;;
      esac
    done
    ;;
  *)
    show_usage
    ;;
esac 