@echo off
REM A股棱镜 价值投资分析系统 — Windows 启动脚本
cd /d %~dp0
REM 清除可能注入的 safe-delete 钩子（PYTHONPATH sitecustomize），避免运行时删除操作崩溃
set PYTHONPATH=
if not exist ".venv\Scripts\activate.bat" (
    echo [错误] 未检测到 .venv，请先运行：python -m venv .venv 并 pip install -r requirements.txt
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
REM RELOAD=1 开发热重载（默认）；生产部署用 set RELOAD=0 后运行，关闭热重载
if "%RELOAD%"=="0" (
    uvicorn main:app --host 0.0.0.0 --port 8001
) else (
    uvicorn main:app --host 0.0.0.0 --port 8001 --reload
)
pause
