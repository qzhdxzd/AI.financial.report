#!/bin/bash
# ============================================================
# Claw 数字员工 - 启动脚本
# 用法:
#   bash start.sh              # 前台启动 Gradio Web UI
#   bash start.sh --daemon      # 后台启动（nohup）
#   bash start.sh --daily       # 立即执行一次每日分析
#   bash start.sh --status      # 查看服务状态
#   bash start.sh --stop        # 停止后台服务
# ============================================================

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
PID_FILE="$PROJECT_DIR/.server.pid"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

start_web_ui() {
    echo "🌐 启动 Gradio Web UI..."
    nohup python app.py > "$LOG_DIR/server.log" 2>&1 &
    echo $! > "$PID_FILE"
    echo "✅ 服务已启动，PID: $(cat $PID_FILE)"
    echo "   日志: $LOG_DIR/server.log"
    echo "   访问: http://localhost:7860"
}

start_daemon() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "⚠️ 服务已在运行中，PID: $(cat $PID_FILE)"
        return 1
    fi
    start_web_ui
}

run_daily() {
    echo "📊 执行每日分析..."
    python run_daily.py "$@"
    echo "✅ 每日分析完成"
}

show_status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "✅ 服务运行中，PID: $(cat $PID_FILE)"
    else
        echo "❌ 服务未运行"
    fi
    echo ""
    echo "最近的日志:"
    tail -5 "$LOG_DIR/daily.log" 2>/dev/null || echo "  (暂无每日分析日志)"
}

stop_service() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        kill "$(cat $PID_FILE)"
        rm -f "$PID_FILE"
        echo "🛑 服务已停止"
    else
        echo "⚠️ 服务未在运行"
    fi
}

case "${1:-}" in
    --daemon|-d)
        start_daemon
        ;;
    --daily)
        shift
        run_daily "$@"
        ;;
    --status|-s)
        show_status
        ;;
    --stop)
        stop_service
        ;;
    *)
        # 默认：前台启动
        echo "🚀 前台启动 Claw 数字员工 Web UI..."
        echo "   按 Ctrl+C 停止"
        python app.py
        ;;
esac
