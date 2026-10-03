@echo off
chcp 65001 >nul
title A-Stock-Prism 8015 One-Click Setup

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DEST=%STARTUP%\AStockPrism-8015-Watchdog.cmd"
set "PYW=C:\Users\Admin\AppData\Local\Programs\Python\Python312\pythonw.exe"
set "WD=C:\Users\Admin\.workbuddy\a-stock-prism\watchdog_8015.py"

echo/
echo  ============================================================
echo    A-Stock-Prism 8015  Service Guard  -  One-Click Setup
echo  ============================================================
echo/
echo   [1/2] Installing logon autostart ...
> "%DEST%" echo @echo off
>>"%DEST%" echo rem Auto-start guard for A-Stock-Prism port 8015. Delete to disable.
>>"%DEST%" echo start "" /b "%PYW%" "%WD%"

if exist "%DEST%" (
  echo         OK  -^> %DEST%
) else (
  echo         FAILED - try running as Administrator
  echo/
  pause
  exit /b 1
)

echo/
echo   [2/2] Starting the guard right now ...
start "" /b "%PYW%" "%WD%"

echo/
echo  ============================================================
echo    DONE.
echo/
echo    - The guard now runs at every logon.
echo    - It probes port 8015 every 5 minutes and relaunches
echo      the service automatically if it is down.
echo    - Log:  ai_value_invest\_watchdog.log
echo    - To uninstall: delete the file
echo        %DEST%
echo  ============================================================
echo/
pause
