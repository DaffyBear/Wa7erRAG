@echo off
setlocal
set PYTHON_EXE=D:\Anaconda3_2022_10\envs\RAG_E\python.exe
if not exist "%PYTHON_EXE%" (
  echo [ERROR] RAG_E Python was not found: %PYTHON_EXE%
  exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -e ".[dev]"