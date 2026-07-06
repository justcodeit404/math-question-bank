@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 检查 Python 是否可用
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 找不到 python 命令，请检查 Python 是否已安装并加入 PATH
    pause
    exit
)

set PORT=8123
set PIDFILE=temp\server.pid

:: 检查是否已有同端口服务器在运行
if exist %PIDFILE% (
    echo [信息] 服务器已在运行，直接打开题库...
    start "" http://localhost:%PORT%/index.html
    exit
)

echo [信息] 正在启动服务器...
start /b python scripts/server.py --port %PORT% --open http://localhost:%PORT%/index.html

echo.
echo ========================================
echo   题库已打开，关闭此窗口将停止服务器
echo ========================================
echo.
:: 保持窗口打开，关闭时只停止由本脚本启动的服务器
pause >nul
python scripts/server.py --stop
