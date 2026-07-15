@echo off
setlocal
set PYTHON_EXE=D:\Anaconda3_2022_10\envs\RAG_E\python.exe
set PYTHONPATH=%CD%\packages\rag_core\src;%CD%\apps\api
set PYTHONIOENCODING=utf-8
"%PYTHON_EXE%" evaluation\evaluate.py %*