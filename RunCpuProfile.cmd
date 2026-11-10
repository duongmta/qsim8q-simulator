@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Khong tim thay .venv\Scripts\python.exe
  echo Hay chay SetupEnvironment.cmd truoc.
  goto :failed
)

".venv\Scripts\python.exe" "cpu_profile\run_cpu_profile.py" %*
if errorlevel 1 goto :failed
exit /b 0

:failed
set "QSIM8_RC=%ERRORLEVEL%"
if "%QSIM8_RC%"=="0" set "QSIM8_RC=1"
echo.
echo RUN_CPU_PROFILE=FAIL code=%QSIM8_RC%
if not defined QSIM8_NO_PAUSE pause
exit /b %QSIM8_RC%
