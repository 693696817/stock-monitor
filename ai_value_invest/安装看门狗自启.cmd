@echo off
chcp 65001 >nul
title Install 8015 Watchdog Autostart

set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AStockPrism-8015-Watchdog.cmd"

echo/
echo   Installing A-Stock-Prism 8015 watchdog autostart...
echo   Target: %DEST%
echo/

copy /y "%~dp0watchdog_autostart.cmd" "%DEST%" >nul 2>&1

if exist "%DEST%" (
  echo   [OK] Installed. The watchdog will guard port 8015 at every logon
  echo        and re-launch the service within 5 minutes if it dies.
  echo/
  echo   To uninstall: delete that file from the Startup folder.
) else (
  echo   [FAIL] Copy failed. Try running this file as Administrator.
)
echo/
pause
