@echo off
chcp 65001 >nul
title Europa_medical_ihaleler - Durdur
cd /d "%~dp0"

if not exist calisma.pid (
    echo Calisan program bulunamadi.
    goto bitir
)

set /p PID=<calisma.pid
echo Program durduruluyor (PID: %PID%)...
taskkill /PID %PID% /T /F >nul 2>&1
del calisma.pid >nul 2>&1
echo Program ve Chrome durduruldu.

:bitir
echo.
pause
