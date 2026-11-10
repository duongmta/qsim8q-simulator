@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "KIT=experiments\cd3_python_core"
if not defined CXX set "CXX=g++"
where "%CXX%" >nul 2>nul
if errorlevel 1 if not exist "%CXX%" (
  echo Khong tim thay trinh bien dich C++. Cai g++ va them vao PATH,
  echo hoac dat bien CXX den duong dan g++.exe truoc khi chay.
  exit /b 1
)
if not exist "%KIT%\build" mkdir "%KIT%\build"
echo [1/2] Bien dich loi C/C++ thanh thu vien q8core.dll ...
"%CXX%" --version > "%KIT%\build\compiler.txt" 2>&1
"%CXX%" -std=c++17 -O2 -DNDEBUG -shared -static -static-libgcc -static-libstdc++ -I "%KIT%\ap_types" -I hls "%KIT%\core_service.cpp" -o "%KIT%\build\q8core.dll" > "%KIT%\build\build.log" 2>&1
if errorlevel 1 (
  echo BUILD_FAIL > "%KIT%\build\STATUS.txt"
  exit /b 1
)
echo [2/2] Chay thuc nghiem Qiskit BackendV2 - loi C/C++ ...
".venv\Scripts\python.exe" "%KIT%\run_cd3.py" > "%KIT%\build\console.log" 2>&1
if errorlevel 1 (
  echo RUN_FAIL > "%KIT%\build\STATUS.txt"
  exit /b 1
)
echo PASS > "%KIT%\build\STATUS.txt"
exit /b 0
