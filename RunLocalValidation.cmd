@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua cai moi truong. Hay chay SetupEnvironment.cmd truoc.
  exit /b 1
)
".venv\Scripts\python.exe" "experiments\cd3_python_core\run_cd3.py"
exit /b %ERRORLEVEL%
