@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "JOB_PYTHON=python"
if exist "..\.venv\Scripts\python.exe" set "JOB_PYTHON=..\.venv\Scripts\python.exe"
"%JOB_PYTHON%" menu.py %*
set "JOB_EXIT=%ERRORLEVEL%"
if not "%JOB_EXIT%"=="0" pause
exit /b %JOB_EXIT%
