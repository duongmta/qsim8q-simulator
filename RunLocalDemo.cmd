@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua cai moi truong. Hay chay SetupEnvironment.cmd truoc.
  exit /b 1
)
".venv\Scripts\python.exe" -m examples.local_core_demo %*
exit /b %ERRORLEVEL%
