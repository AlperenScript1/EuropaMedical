@echo off
chcp 65001 >nul
title Europa_medical_ihaleler
cd /d "%~dp0"

REM Python ve bagimliliklari kontrol et / otomatik kur
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Kurulum tamamlanamadi. Yukaridaki hata mesajlarini kontrol edin.
    echo.
    pause
    exit /b 1
)

REM Sanal ortamdan calistir
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python bulunamadi ve otomatik kurulum basarisiz oldu.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -u app.py
if exist calisma.pid del calisma.pid >nul 2>&1
echo.
pause
