#!/bin/bash
# A股棱镜 价值投资分析系统 — 启动脚本 (Windows / Git Bash)
cd "$(dirname "$0")"
# 关键：去掉 safe-delete 的 sitecustomize 钩子，否则运行时删除操作会 FAIL_CLOSED 崩溃
unset PYTHONPATH
VENV=".venv"
if [ -f "$VENV/Scripts/activate" ]; then
    source "$VENV/Scripts/activate"
elif [ -f "$VENV/bin/activate" ]; then
    source "$VENV/bin/activate"
else
    echo "[错误] 未检测到 $VENV，请先运行：python -m venv $VENV && pip install -r requirements.txt"
    exit 1
fi
# RELOAD=1 开发热重载（默认）；生产部署用 RELOAD=0 ./start.sh 关闭
if [ "${RELOAD:-1}" = "1" ]; then
    exec uvicorn main:app --host 0.0.0.0 --port 8001 --reload
else
    exec uvicorn main:app --host 0.0.0.0 --port 8001
fi
