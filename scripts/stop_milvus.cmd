@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "DOCKER_CONFIG=%CD%\.docker-config"
if not exist "%DOCKER_CONFIG%" mkdir "%DOCKER_CONFIG%"

for %%C in (wa7errag-milvus-standalone wa7errag-milvus-minio wa7errag-milvus-etcd) do (
  docker inspect "%%C" >nul 2>nul
  if not errorlevel 1 docker stop "%%C" >nul 2>nul
)
exit /b 0