@echo off
setlocal
chcp 65001 >nul
title Meterbot demo
cd /d "%~dp0"

rem ---- find Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [!] Python not found. Install Python 3.11+ from python.org and tick "Add Python to PATH".
  pause & exit /b 1
)

rem ---- first run: private environment + packages (takes a few minutes, only once) ----
if not exist ".venv\Scripts\python.exe" (
  echo Setting up for the first time, please wait...
  %PY% -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r cloud\requirements.txt -r robot\requirements.txt pillow opencv-python-headless || (pause & exit /b 1)
)

rem ---- demo settings (local only, not the real dorm) ----
set "ADMIN_PASSWORD=admin1234"
set "SECRET_KEY=local-demo"
set "DEVICE_KEY=devkey"
set "SECURE_COOKIES=0"
set "DORM_NAME=Demo Dorm"
set "DATABASE_URL=sqlite:///./data/dorm.db"
set "ROBOT_FAKE_HARDWARE=1"
set "CLOUD_URL=http://localhost:8000"

if not exist "cloud\data\dorm.db" (
  pushd cloud
  "..\.venv\Scripts\python.exe" seed_demo.py
  popd
)

start "Meterbot - dorm web" /min cmd /c "cd /d "%~dp0cloud" && "%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app_from_env --factory --port 8000"
start "Meterbot - robot" /min cmd /c "cd /d "%~dp0robot" && "%~dp0.venv\Scripts\python.exe" server.py"

echo Starting... the browser will open in a few seconds.
timeout /t 8 /nobreak >nul
start "" "http://localhost:5000/"
start "" "http://localhost:8000/admin"
echo.
echo  Robot control : http://localhost:5000
echo  Dorm admin    : http://localhost:8000/admin   (password: admin1234)
echo  To stop everything, double-click stop_demo.bat
timeout /t 10 >nul
