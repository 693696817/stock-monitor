@echo off
chcp 65001 >nul
title A-Stock-Prism 8015 Watchdog

echo/
echo   A-Stock-Prism 8015 watchdog
echo   - probes 127.0.0.1:8015 every 5 minutes
echo   - re-launches the service automatically if it is down
echo   - keep this window open to stay protected; close it to stop
echo/
echo   Log file: ai_value_invest\_watchdog.log
echo/

"C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\Admin\.workbuddy\a-stock-prism\watchdog_8015.py"

echo/
echo   Watchdog stopped.
pause
