@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
title Workflow Studio

if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto check_environment
)
where python >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto check_environment
)
echo Python 3.11 or later is required. Please install it from python.org and run this file again.
pause
exit /b 1

:check_environment
if not exist ".venv\Scripts\python.exe" (
    echo Could not create the Python environment.
    pause
    exit /b 1
)

:dependencies
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or later is required'" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 or later is required. Please update Python and recreate .venv.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,httpx,dotenv" >nul 2>&1
if not errorlevel 1 goto launch
echo Preparing dependencies for the first launch. An internet connection is required...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Check your connection and try again.
    pause
    exit /b 1
)

:launch
".venv\Scripts\python.exe" start.py %*
if errorlevel 1 pause
