@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERR] python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

set PORT=8123
set PIDFILE=temp\server.pid

if not exist temp mkdir temp >nul 2>&1

if exist "%PIDFILE%" (
    echo Server already running, opening bank...
    start "" "http://localhost:%PORT%/index.html"
    exit /b 0
)

echo Starting math bank server on port %PORT%...
start /b python scripts/server.py --port %PORT% --open "http://localhost:%PORT%/index.html"

echo.
echo ========================================
echo   Bank opened. Close this window to stop.
echo ========================================
echo.
pause >nul
python scripts/server.py --stop
exit /b 0
