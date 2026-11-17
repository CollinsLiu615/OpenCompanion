@echo off
chcp 65001 >nul 2>&1
setlocal

REM 停止 OpenCompanion 服务（Windows）
REM 找到监听 8800 端口的进程并结束它

if "%OC_PORT%"=="" set "OC_PORT=8800"

echo.
echo   正在查找占用 %OC_PORT% 端口的 OpenCompanion 服务...

set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%OC_PORT%" ^| findstr "LISTENING"') do (
    if not defined FOUND (
        set "PID=%%p"
        set "FOUND=1"
        echo   找到进程 PID: %%p
        taskkill /PID %%p /F >nul 2>&1
        if errorlevel 1 (
            echo   X 结束失败，可能需要管理员权限
        ) else (
            echo   OK 服务已停止
        )
    )
)

if not defined FOUND (
    echo   没有发现正在运行的服务
)

echo.
timeout /t 3 >nul
endlocal
