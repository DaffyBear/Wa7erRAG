@echo off
setlocal
set DOCKER_CONFIG=%CD%\.docker-config
if not exist "%DOCKER_CONFIG%" mkdir "%DOCKER_CONFIG%"
docker compose -p wa7errag-milvus -f deploy\docker\docker-compose.milvus.yml down