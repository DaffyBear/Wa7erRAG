@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "ROOT=%CD%"
set "RUNTIME=%ROOT%\tmp\runtime"
set "REDIS_CLI=D:\redis\redis-cli.exe"

if /I "%~1"=="--check" (
  echo [OK] Stop script is ready.
  exit /b 0
)

echo [1/5] Stopping Web...
call :stop_port 3000
call :stop_pid_file "%RUNTIME%\web.pid"

echo [2/5] Stopping API...
call :stop_port 8000
call :stop_pid_file "%RUNTIME%\api.pid"

echo [3/5] Stopping Attu...
docker stop wa7errag-attu >nul 2>nul

echo [4/5] Stopping Milvus...
call scripts\stop_milvus.cmd >nul 2>nul

echo [5/5] Stopping Redis...
if exist "%REDIS_CLI%" (
  "%REDIS_CLI%" -h 127.0.0.1 -p 6379 shutdown >nul 2>nul
) else (
  call :stop_port 6379
  call :stop_pid_file "%RUNTIME%\redis.pid"
)

del /q "%RUNTIME%\api.pid" "%RUNTIME%\web.pid" "%RUNTIME%\redis.pid" >nul 2>nul
echo.
echo [OK] Project services have been stopped.
echo PostgreSQL was left running intentionally.
exit /b 0

:stop_port
set "TARGET_PORT=%~1"
for /f %%P in ('powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort %TARGET_PORT% -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$c.OwningProcess}"') do taskkill /PID %%P /T /F >nul 2>nul
exit /b 0

:stop_pid_file
set "PID_FILE=%~1"
if not exist "%PID_FILE%" exit /b 0
set /p SERVICE_PID=<"%PID_FILE%"
if defined SERVICE_PID taskkill /PID %SERVICE_PID% /T /F >nul 2>nul
exit /b 0
