@echo off
chcp 65001 >nul 2>&1
title Quant Platform Launcher

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

echo ========================================
echo    Quant Platform - Quick Start
echo ========================================
echo.
echo   ROOT: %ROOT%
echo.

echo [1/2] Starting backend (port 8000)...
start "Backend" cmd /k "cd /d %BACKEND% && .venv\Scripts\python.exe main.py"

timeout /t 3 /nobreak >nul

echo [2/2] Starting frontend (port 3000)...
start "Frontend" cmd /k "cd /d %FRONTEND% && npx vite --port 3000"

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo ========================================
echo.

timeout /t 5 /nobreak >nul
start http://localhost:3000

echo Press any key to close...
pause >nul
