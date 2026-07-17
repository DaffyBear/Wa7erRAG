@echo off
setlocal
set PYTHON_EXE=python
set PYTHONPATH=%CD%\packages\rag_core\src;%CD%\apps\api
set PYTHONIOENCODING=utf-8
"%PYTHON_EXE%" pipelines\governance.py %*