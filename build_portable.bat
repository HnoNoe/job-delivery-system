@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install -r requirements-build.txt
set PORTABLE_ONEFILE=1
"%PY%" -m PyInstaller portable.spec --noconfirm --clean
echo.
echo 生成完成：dist\JobDeliverySystem.exe
pause
