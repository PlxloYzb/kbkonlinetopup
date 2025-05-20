#!/bin/bash
# 服务脚本：一键启动、停止、重启三个Python服务
# 用法: ./manage_services.sh {start|stop|restart|status}

# 项目根目录
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=python3

# 各服务脚本
STATUS_UPDATE_SERVER="$WORKDIR/status_update_server.py"
MANAGER_SERVER="$WORKDIR/manager_server.py"
HTTP_READER="$WORKDIR/http_reader.py"

# 日志目录
LOGDIR="$WORKDIR/logs"
mkdir -p "$LOGDIR"

# PID文件
PIDDIR="$WORKDIR/pids"
mkdir -p "$PIDDIR"

start_service() {
    script=$1
    name=$2
    logfile="$LOGDIR/${name}.log"
    pidfile="$PIDDIR/${name}.pid"
    if [ -f "$pidfile" ] && kill -0 $(cat "$pidfile") 2>/dev/null; then
        echo "$name 已在运行 (PID: $(cat $pidfile))"
    else
        nohup $PYTHON "$script" > "$logfile" 2>&1 &
        echo $! > "$pidfile"
        echo "$name 启动完成 (PID: $(cat $pidfile))"
    fi
}

stop_service() {
    name=$1
    pidfile="$PIDDIR/${name}.pid"
    if [ -f "$pidfile" ] && kill -0 $(cat "$pidfile") 2>/dev/null; then
        kill $(cat "$pidfile")
        rm -f "$pidfile"
        echo "$name 已停止"
    else
        echo "$name 未运行"
    fi
}

status_service() {
    name=$1
    pidfile="$PIDDIR/${name}.pid"
    if [ -f "$pidfile" ] && kill -0 $(cat "$pidfile") 2>/dev/null; then
        echo "$name 正在运行 (PID: $(cat $pidfile))"
    else
        echo "$name 未运行"
    fi
}

case "$1" in
    start)
        start_service "$STATUS_UPDATE_SERVER" "status_update_server"
        start_service "$MANAGER_SERVER" "manager_server"
        start_service "$HTTP_READER" "http_reader"
        ;;
    stop)
        stop_service "status_update_server"
        stop_service "manager_server"
        stop_service "http_reader"
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        status_service "status_update_server"
        status_service "manager_server"
        status_service "http_reader"
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
exit 0