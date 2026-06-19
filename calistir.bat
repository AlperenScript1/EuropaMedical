@echo off
chcp 65001 >nul
title Europa_medical_ihaleler
cd /d "%~dp0"
python -u app.py
if exist calisma.pid del calisma.pid >nul 2>&1
echo.
pause
