#!/bin/bash
# 停止 OpenCompanion 服务
OC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OC_DATA="$OC_ROOT/data"
PIDFILE="$OC_DATA/server.pid"

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "已停止（pid $PID）"
  else
    echo "进程已不在运行"
  fi
  rm -f "$PIDFILE"
else
  # 兜底：按命令行匹配
  PIDS=$(pgrep -f "core/server.py" 2>/dev/null)
  if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill 2>/dev/null && echo "已停止"
  else
    echo "没有在运行的服务"
  fi
fi
