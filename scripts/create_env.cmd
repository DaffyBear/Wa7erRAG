@echo off
setlocal
where conda >nul 2>nul
if errorlevel 1 (
  echo [ERROR] conda was not found in cmd.exe PATH.
  exit /b 1
)
conda env list | findstr /B /C:"RAG_E " >nul
if errorlevel 1 (
  conda create -y -n RAG_E python=3.11
) else (
  echo [INFO] Conda environment RAG_E already exists.
)
echo [INFO] Activate with: conda activate RAG_E
