@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "DOCKER_CONFIG=%CD%\.docker-config"
if not exist "%DOCKER_CONFIG%" mkdir "%DOCKER_CONFIG%"

set "ETCD=wa7errag-milvus-etcd"
set "MINIO=wa7errag-milvus-minio"
set "MILVUS=wa7errag-milvus-standalone"

docker inspect "%ETCD%" >nul 2>nul
if errorlevel 1 goto CREATE_CONTAINERS
docker inspect "%MINIO%" >nul 2>nul
if errorlevel 1 goto CREATE_CONTAINERS
docker inspect "%MILVUS%" >nul 2>nul
if errorlevel 1 goto CREATE_CONTAINERS

echo Existing Milvus containers found. Reusing them...
docker start "%ETCD%" >nul
if errorlevel 1 exit /b 1
docker start "%MINIO%" >nul
if errorlevel 1 exit /b 1
docker start "%MILVUS%" >nul
if errorlevel 1 exit /b 1
goto WAIT_READY

:CREATE_CONTAINERS
echo Creating Milvus containers with Docker Compose...
docker compose -p wa7errag-milvus -f deploy\docker\docker-compose.milvus.yml up -d
if errorlevel 1 exit /b 1

:WAIT_READY
powershell -NoProfile -Command "$deadline=(Get-Date).AddMinutes(2); do { $state=docker inspect '%MILVUS%' --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>$null; if($state -match '^running healthy$'){ exit 0 }; Start-Sleep -Seconds 2 } while((Get-Date)-lt $deadline); exit 1"
if errorlevel 1 (
  echo [ERROR] Milvus did not become healthy within 2 minutes.
  docker ps -a --filter "name=wa7errag-milvus" --format "table {{.Names}}\t{{.Status}}"
  exit /b 1
)
docker ps --filter "name=wa7errag-milvus" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
exit /b 0
