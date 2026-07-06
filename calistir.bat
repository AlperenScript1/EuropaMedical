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

REM Kurulumun sectigi Python ile calistir
set "PY_EXE="
if exist ".python-path" (
    set /p PY_EXE=<".python-path"
)
if not defined PY_EXE if exist ".venv\Scripts\python.exe" set "PY_EXE=.venv\Scripts\python.exe"
if not defined PY_EXE if exist "python-embed\python.exe" set "PY_EXE=python-embed\python.exe"
if not defined PY_EXE (
    echo.
    echo Python bulunamadi ve otomatik kurulum basarisiz oldu.
    echo.
    pause
    exit /b 1
)

"%PY_EXE%" -u app.py
if exist calisma.pid del calisma.pid >nul 2>&1
echo.
pause
