@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  OpenCompanion 电脑端启动器（Windows）
REM
REM  双击本文件即可。它负责：
REM    找 Python -> 装缺的依赖 -> 后台起服务 -> 等就绪 -> 打开浏览器
REM ============================================================

title OpenCompanion

REM 项目根目录（本脚本在 desktop\scripts\ 下，往上两级）
set "OC_ROOT=%~dp0..\.."
for %%i in ("%OC_ROOT%") do set "OC_ROOT=%%~fi"

if "%OC_PORT%"=="" set "OC_PORT=8800"
set "OC_URL=http://127.0.0.1:%OC_PORT%"
set "OC_DATA=%OC_ROOT%\data"
if not exist "%OC_DATA%" mkdir "%OC_DATA%"
set "OC_LOG=%OC_DATA%\server.log"

echo.
echo   OpenCompanion
echo   Benzene AI Studio
echo   ----------------------------
echo.

REM ---- 1. 找 Python -------------------------------------------------
set "PY="
for %%c in (python py python3) do (
    if not defined PY (
        %%c -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY=%%c"
        )
    )
)

if not defined PY (
    echo   X 没有找到 Python 3.8 以上版本
    echo.
    echo     请先安装 Python：https://www.python.org/downloads/
    echo     安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo   Python: %PYVER%

REM ---- 2. 依赖检查 -------------------------------------------------
%PY% -c "import flask, openai, PIL" >nul 2>&1
if errorlevel 1 (
    echo   正在安装依赖（首次运行需要一点时间）...
    %PY% -m pip install --quiet -r "%OC_ROOT%\requirements.txt"
    if errorlevel 1 (
        echo   X 依赖安装失败
        echo.
        echo     可手动执行：%PY% -m pip install -r "%OC_ROOT%\requirements.txt"
        echo     如果提示网络错误，可换国内源：
        echo       %PY% -m pip install -r "%OC_ROOT%\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
    echo   OK 依赖已装好
)

REM ---- 3. 已经在跑就直接开浏览器 --------------------------------------
curl -s -m 2 "%OC_URL%/healthz" 2>nul | findstr /c:"\"ok\":true" >nul 2>&1
if not errorlevel 1 (
    echo   服务已在运行 -^> %OC_URL%
    start "" "%OC_URL%"
    exit /b 0
)

REM ---- 4. 启动服务（后台窗口）----------------------------------------
echo   正在启动服务...
cd /d "%OC_ROOT%"

REM 用 start 开一个最小化的独立窗口跑服务，关掉本窗口服务也不停
start "OpenCompanion 服务（关闭此窗口即停止服务）" /min cmd /c ^
  "set OC_PORT=%OC_PORT%&& set OC_HOST=0.0.0.0&& %PY% core\server.py >> "%OC_LOG%" 2>&1"

REM ---- 5. 等就绪（最多 30 秒）---------------------------------------
set /a COUNT=0
:WAITLOOP
timeout /t 1 /nobreak >nul
curl -s -m 2 "%OC_URL%/healthz" 2>nul | findstr /c:"\"ok\":true" >nul 2>&1
if not errorlevel 1 goto READY
set /a COUNT+=1
if %COUNT% lss 30 goto WAITLOOP

echo.
echo   X 启动超时
echo.
echo     请查看日志：%OC_LOG%
echo.
pause
exit /b 1

:READY
echo   OK 已就绪
echo.

REM ---- 6. 取局域网 IP 并提示 ----------------------------------------
set "LANIP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined LANIP (
        set "TMPIP=%%a"
        set "TMPIP=!TMPIP: =!"
        echo !TMPIP! | findstr /r "^192\.168\. ^10\. ^172\." >nul && set "LANIP=!TMPIP!"
    )
)

echo   电脑上打开:  %OC_URL%
if defined LANIP (
    echo   手机上打开:  http://!LANIP!:%OC_PORT%   （手机需与电脑连同一个 WiFi）
)
echo.

start "" "%OC_URL%"

echo   提示：服务在一个最小化的窗口里运行，关闭那个窗口即停止服务。
echo.
timeout /t 5 >nul
endlocal
