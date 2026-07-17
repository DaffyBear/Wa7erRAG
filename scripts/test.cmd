@echo off
setlocal
set PYTHON_EXE=python
set PYTHONPATH=%CD%\packages\rag_core\src;%CD%\apps\api
set PYTHONIOENCODING=utf-8
"%PYTHON_EXE%" -m ruff check packages apps\api pipelines evaluation tests
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m pytest -q