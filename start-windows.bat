@echo off
REM Start the platform locally on Windows. Double-click this file.
REM   start-windows.bat reset   -> recreate the demo data from scratch
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.12 or 3.13 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing requirements (first run takes a few minutes)...
python -m pip install --disable-pip-version-check -q -r backend\requirements.txt
if errorlevel 1 (
  echo Installing requirements failed. Check your internet connection and try again.
  pause
  exit /b 1
)

cd backend
if /i "%1"=="reset" (
  python -m app.seed --reset
) else (
  python -m app.seed
)

echo.
echo ============================================================
echo  Open in your browser:  http://localhost:8000
echo  Demo password for all accounts:  Demo@12345
echo  Press Ctrl+C in this window to stop the server.
echo ============================================================
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
