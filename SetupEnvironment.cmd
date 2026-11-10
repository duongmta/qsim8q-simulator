@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "QSIM8_PYTHON=%~dp0.venv\Scripts\python.exe"
set "QSIM8_FORCE=0"
if /I "%~1"=="--force" set "QSIM8_FORCE=1"
if not exist "%QSIM8_PYTHON%" (
    echo [1/3] Tao moi truong .venv bang Python 3.12...
    if defined QSIM8_BASE_PYTHON (
        "%QSIM8_BASE_PYTHON%" -c "import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32"
        if errorlevel 1 goto :python_missing
        "%QSIM8_BASE_PYTHON%" -m venv ".venv"
        if errorlevel 1 goto :failed
    ) else (
        py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
        if errorlevel 1 goto :python_missing
        py -3.12 -m venv ".venv"
        if errorlevel 1 goto :failed
    )
) else (
    echo [1/3] Da co .venv.
)

set "PYTHONUTF8=1"
if "%QSIM8_FORCE%"=="0" (
    "%QSIM8_PYTHON%" -m qsim8_backend.launch --check-env >nul 2>&1
    if not errorlevel 1 (
        echo [2/3] Cac goi Python da san sang; bo qua cai lai.
        goto :verify
    )
)

echo [2/3] Cai/cap nhat cac goi Python cua project...
"%QSIM8_PYTHON%" -m pip install --prefer-binary -r "requirements.txt"
if errorlevel 1 goto :failed

:verify
echo [3/3] Kiem tra Qiskit BackendV2...
"%QSIM8_PYTHON%" -m qsim8_backend.launch --check-env
if errorlevel 1 goto :failed

echo.
echo SETUP_ENVIRONMENT=PASS
exit /b 0

:python_missing
echo ERROR: Can Python 3.12 64-bit. Cai Python Launcher de dung "py -3.12",
echo hoac dat QSIM8_BASE_PYTHON den python.exe 3.12 64-bit.
goto :failed

:failed
set "QSIM8_RC=%ERRORLEVEL%"
if "%QSIM8_RC%"=="0" set "QSIM8_RC=1"
echo.
echo SETUP_ENVIRONMENT=FAIL code=%QSIM8_RC%
echo Chay lai file nay trong cua so CMD/PowerShell de xem day du loi.
if not defined QSIM8_NO_PAUSE pause
exit /b %QSIM8_RC%
