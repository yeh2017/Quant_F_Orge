@echo off
chcp 65001 >nul 2>&1
title Quant Platform - Launcher

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV_PYTHON=%BACKEND%\.venv\Scripts\python.exe"
set "VENV_PIP=%BACKEND%\.venv\Scripts\pip.exe"
set "PIP_MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"

echo ==========================================
echo      Quant Platform - Launcher v2
echo ==========================================
echo.
echo   ROOT: %ROOT%
echo.

:: 1. Python
echo [1/5] Checking Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Python not found in PATH!
    goto fail
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo   [OK] Python %PYVER%

:: 2. Node.js
echo [2/5] Checking Node.js...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Node.js not found in PATH!
    goto fail
)
for /f "tokens=1 delims= " %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
echo   [OK] Node.js %NODEVER%

:: 3. Backend venv
echo [3/5] Checking backend virtual environment...
if not exist "%VENV_PYTHON%" goto create_venv

"%VENV_PYTHON%" -c "import sys; print(sys.version)" >nul 2>&1
if %errorlevel% neq 0 goto rebuild_venv

:: Check all critical runtime packages
"%VENV_PYTHON%" -c "import uvicorn, fastapi, pandas, sqlalchemy, jinja2, structlog" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] Missing packages, installing...
    "%VENV_PIP%" install -r "%BACKEND%\requirements.txt" %PIP_MIRROR%
    if %errorlevel% neq 0 goto fail
)
echo   [OK] .venv ready
goto venv_ok

:create_venv
echo   [INFO] .venv not found, creating...
python -m venv "%BACKEND%\.venv"
if %errorlevel% neq 0 (
    echo   [FAIL] Failed to create .venv
    goto fail
)
echo   [INFO] Installing dependencies (this may take 5-10 minutes)...
"%VENV_PIP%" install -r "%BACKEND%\requirements.txt" %PIP_MIRROR%
if %errorlevel% neq 0 (
    echo   [FAIL] pip install failed
    goto fail
)
echo   [OK] .venv created
goto venv_ok

:rebuild_venv
echo   [INFO] .venv broken, rebuilding...
rmdir /s /q "%BACKEND%\.venv" 2>nul
python -m venv "%BACKEND%\.venv"
if %errorlevel% neq 0 (
    echo   [FAIL] Failed to create .venv
    goto fail
)
echo   [INFO] Installing dependencies (this may take 5-10 minutes)...
"%VENV_PIP%" install -r "%BACKEND%\requirements.txt" %PIP_MIRROR%
if %errorlevel% neq 0 (
    echo   [FAIL] pip install failed
    goto fail
)
echo   [OK] .venv rebuilt

:venv_ok
echo   [OK] Backend ready

:: 4. Frontend check
echo [4/5] Checking frontend...
if not exist "%FRONTEND%\package.json" (
    echo   [FAIL] frontend\package.json not found!
    goto fail
)
if not exist "%FRONTEND%\node_modules" (
    echo   [INFO] node_modules not found, installing...
    pushd "%FRONTEND%"
    call npm install
    popd
) else (
    :: Verify node_modules is compatible (vite must be runnable)
    pushd "%FRONTEND%"
    call npx vite --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo   [WARN] node_modules broken, reinstalling...
        rmdir /s /q node_modules 2>nul
        call npm install
    )
    popd
)
echo   [OK] Frontend ready

:: 5. .env check
if not exist "%BACKEND%\.env" (
    if exist "%BACKEND%\.env.example" (
        echo   [INFO] .env not found, creating from .env.example...
        copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
    ) else (
        echo   [INFO] .env not found, generating default config...
        (
            echo # Data Source
            echo TUSHARE_TOKEN=
            echo TUSHARE_POINTS=2000
            echo TAVILY_API_KEY=
            echo.
            echo # Service
            echo API_HOST=0.0.0.0
            echo API_PORT=8000
            echo TQDM_DISABLE=1
            echo NEWS_AUTO_FETCH_HOURS=0
            echo.
            echo # LLM Providers
            echo LLM_CHANNELS=siliconflow,anspire
            echo LLM_SILICONFLOW_URL=https://api.siliconflow.cn/v1/chat/completions
            echo LLM_SILICONFLOW_KEY=
            echo LLM_SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V4-Flash
            echo LLM_ANSPIRE_URL=https://open-gateway.anspire.cn/v6/chat/completions
            echo LLM_ANSPIRE_KEY=
            echo LLM_ANSPIRE_MODEL=deepseek-v4-flash
            echo ERNIE_BATCH_SIZE=10
            echo LLM_MONTHLY_BUDGET=15
        ) > "%BACKEND%\.env"
    )
    echo   [OK] .env created
    echo.
    echo   ==========================================
    echo     First Run - Configuration Required
    echo   ==========================================
    echo     Browser will open shortly.
    echo     Click [Manage] to configure:
    echo       1. Tushare Token   [required]
    echo       2. AI Model Keys   [optional]
    echo       3. Tavily API Key  [optional]
    echo.
    echo     Fill once, saved permanently.
    echo   ==========================================
    echo.
) else (
    echo   [OK] .env exists
)

echo.
echo [5/5] Starting services...
echo.

:: Check if backend already running
powershell -Command "try{$null=Invoke-WebRequest 'http://localhost:8000/api/data_center/status' -TimeoutSec 2 -UseBasicParsing;exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Backend already running, skipping startup
    goto start_fe
)

:: Start backend
start "Backend" cmd /k "cd /d %BACKEND% && .venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend (initial 5s + max 30s polling)
echo   Waiting for backend to initialize...
timeout /t 5 /nobreak >nul
set TRIES=0

:wait_loop
set /a TRIES+=1
if %TRIES% gtr 10 (
    echo   [WARN] Backend not ready after 35s, starting frontend anyway...
    goto start_fe
)
powershell -Command "try{$null=Invoke-WebRequest 'http://localhost:8000/api/data_center/status' -TimeoutSec 2 -UseBasicParsing;exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [%TRIES%/10] waiting...
    timeout /t 3 /nobreak >nul
    goto wait_loop
)
echo   [OK] Backend is ready!

:start_fe
start "Frontend" cmd /k "cd /d %FRONTEND% && npx vite --port 3000"

echo.
echo ==========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo ==========================================

timeout /t 5 /nobreak >nul
start http://localhost:3000

echo.
echo All services started. Press any key to close this window...
pause >nul
goto :eof

:fail
echo.
echo ==========================================
echo   STARTUP FAILED - see errors above
echo ==========================================
echo.
pause
