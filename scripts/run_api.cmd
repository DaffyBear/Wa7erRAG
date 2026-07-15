@echo off
setlocal
set PYTHON_EXE=D:\Anaconda3_2022_10\envs\RAG_E\python.exe
set PYTHONPATH=%CD%\packages\rag_core\src;%CD%\apps\api
set PYTHONIOENCODING=utf-8
"%PYTHON_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps\api