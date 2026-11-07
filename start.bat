@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "JOB_PYTHON=python"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if not errorlevel 1 set "JOB_PYTHON=.venv\Scripts\python.exe"
)
"%JOB_PYTHON%" start.py %*
set "JOB_EXIT=%ERRORLEVEL%"
if not "%JOB_EXIT%"=="0" (
    echo Startup failed. Run: python setup_env.py
    pause
)
exit /b %JOB_EXIT%
