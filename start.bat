@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   求职批量投递系统 —— 一键启动
echo   启动后会自动打开浏览器，按页面步骤操作
echo ============================================
python start.py
echo.
echo 启动完成。如浏览器未自动打开，请手动访问 http://localhost:8501
pause
