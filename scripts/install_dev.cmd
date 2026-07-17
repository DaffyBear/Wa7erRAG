@echo off
setlocal
set PYTHON_EXE=python
where %PYTHON_EXE% >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found. Activate the project environment first.
  exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -e ".[dev]"
