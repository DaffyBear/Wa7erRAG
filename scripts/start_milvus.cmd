@echo off
setlocal
set DOCKER_CONFIG=%CD%\.docker-config
if not exist "%DOCKER_CONFIG%" mkdir "%DOCKER_CONFIG%"
docker compose -p wa7errag-milvus -f deploy\docker\docker-compose.milvus.yml up -d
if errorlevel 1 exit /b 1
docker compose -p wa7errag-milvus -f deploy\docker\docker-compose.milvus.yml ps