@echo off
title AWS Report Generator
echo ============================================
echo   AWS Utilization Report Generator
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan. Install Python 3.10+ dulu.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt -q
echo.

:: Check .env
if not exist .env (
    echo [ERROR] File .env tidak ditemukan!
    echo        Copy .env.example ke .env dan isi credentials.
    pause
    exit /b 1
)

:: Start server
echo [2/3] Starting server...
echo.
echo ============================================
echo   Buka browser: http://localhost:8000
echo   Tekan Ctrl+C untuk stop
echo ============================================
echo.

:: Open browser
start http://localhost:8000

:: Run
python app.py
pause
