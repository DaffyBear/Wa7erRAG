@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "ROOT=%CD%"
set "RUNTIME=%ROOT%\tmp\runtime"
set "LOG_DIR=%RUNTIME%\logs"
set "PYTHON_EXE=D:\Anaconda3_2022_10\envs\RAG_E\python.exe"
set "REDIS_EXE=D:\redis\redis-server.exe"
set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"

if /I "%~1"=="--check" goto check_only

if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [1/6] Checking PostgreSQL...
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)){ $service=Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'postgresql*' } | Select-Object -First 1; if($service){ Start-Service $service.Name -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 } }; if(-not (Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)){ exit 1 }"
if errorlevel 1 (
  echo [ERROR] PostgreSQL is not listening on port 5432.
  exit /b 1
)

echo [2/6] Starting Redis...
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue)){ if(-not (Test-Path -LiteralPath '%REDIS_EXE%')){ exit 2 }; $p=Start-Process -FilePath '%REDIS_EXE%' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath '%RUNTIME%\redis.pid' -Value $p.Id -Encoding ascii; $deadline=(Get-Date).AddSeconds(20); do { Start-Sleep -Seconds 1 } while(-not (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue) -and (Get-Date)-lt $deadline) }; if(-not (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue)){ exit 1 }"
if errorlevel 1 (
  echo [ERROR] Redis could not be started from %REDIS_EXE%.
  exit /b 1
)

echo [3/6] Starting Docker and Milvus...
docker info >nul 2>nul
if errorlevel 1 (
  if not exist "%DOCKER_DESKTOP%" (
    echo [ERROR] Docker Desktop is not running and was not found.
    exit /b 1
  )
  start "" /min "%DOCKER_DESKTOP%"
  powershell -NoProfile -Command "$deadline=(Get-Date).AddMinutes(3); do { Start-Sleep -Seconds 5; docker info *> $null } while($LASTEXITCODE -ne 0 -and (Get-Date)-lt $deadline); if($LASTEXITCODE -ne 0){ exit 1 }"
  if errorlevel 1 (
    echo [ERROR] Docker Desktop did not become ready.
    exit /b 1
  )
)
call scripts\start_milvus.cmd
if errorlevel 1 exit /b 1

echo [4/6] Starting Attu...
docker inspect wa7errag-attu >nul 2>nul
if errorlevel 1 (
  docker run -d --name wa7errag-attu --network wa7errag-milvus -p 8001:3000 -e MILVUS_URL=wa7errag-milvus-standalone:19530 zilliz/attu:latest >nul
) else (
  docker start wa7errag-attu >nul
)
if errorlevel 1 echo [WARN] Attu did not start. Core RAG services can still run.

echo [5/6] Starting API...
if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python environment not found: %PYTHON_EXE%
  exit /b 1
)
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)){ $env:PYTHONPATH='%ROOT%\packages\rag_core\src;%ROOT%\apps\api'; $env:PYTHONIOENCODING='utf-8'; $p=Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000','--app-dir','apps\api' -WorkingDirectory '%ROOT%' -WindowStyle Hidden -RedirectStandardOutput '%LOG_DIR%\api.log' -RedirectStandardError '%LOG_DIR%\api.error.log' -PassThru; Set-Content -LiteralPath '%RUNTIME%\api.pid' -Value $p.Id -Encoding ascii; $deadline=(Get-Date).AddSeconds(60); do { Start-Sleep -Seconds 1 } while(-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) -and (Get-Date)-lt $deadline) }; if(-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)){ exit 1 }"
if errorlevel 1 (
  echo [ERROR] API failed to start. See tmp\runtime\logs\api.error.log
  exit /b 1
)

echo [6/6] Starting Web...
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found in PATH.
  exit /b 1
)
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)){ $p=Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c','npm run dev -- --port 3000' -WorkingDirectory '%ROOT%\apps\web' -WindowStyle Hidden -RedirectStandardOutput '%LOG_DIR%\web.log' -RedirectStandardError '%LOG_DIR%\web.error.log' -PassThru; Set-Content -LiteralPath '%RUNTIME%\web.pid' -Value $p.Id -Encoding ascii; $deadline=(Get-Date).AddSeconds(60); do { Start-Sleep -Seconds 1 } while(-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue) -and (Get-Date)-lt $deadline) }; if(-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)){ exit 1 }"
if errorlevel 1 (
  echo [ERROR] Web failed to start. See tmp\runtime\logs\web.error.log
  exit /b 1
)

echo.
echo [OK] All services are running.
echo Web:    http://localhost:3000
echo API:    http://127.0.0.1:8000/docs
echo Attu:   http://127.0.0.1:8001
echo Milvus: 127.0.0.1:19530
echo Logs:   %LOG_DIR%
exit /b 0

:check_only
set "FAILED=0"
if exist "%PYTHON_EXE%" (echo [OK] Python: %PYTHON_EXE%) else (echo [MISSING] %PYTHON_EXE% & set "FAILED=1")
if exist "%REDIS_EXE%" (echo [OK] Redis: %REDIS_EXE%) else (echo [MISSING] %REDIS_EXE% & set "FAILED=1")
where npm >nul 2>nul && (echo [OK] npm) || (echo [MISSING] npm & set "FAILED=1")
where docker >nul 2>nul && (echo [OK] docker) || (echo [MISSING] docker & set "FAILED=1")
if exist "scripts\start_milvus.cmd" (echo [OK] Milvus script) else (echo [MISSING] scripts\start_milvus.cmd & set "FAILED=1")
if "%FAILED%"=="1" exit /b 1
echo [OK] Startup prerequisites are present.
exit /b 0
