@echo off
chcp 65001 >nul
title Europa_medical_ihaleler
cd /d "%~dp0"
python app.py
echo.
pause
