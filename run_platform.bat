@echo off
echo ==================================================
echo STARTING QUANTITATIVE TRADING PLATFORM
echo ==================================================

echo 1. Starting FastAPI Backend (Port 8000)...
start "Alpha FastAPI Backend" cmd /k "python -m uvicorn alpha_platform.api.app:app --reload --port 8000"

echo 2. Starting React Dashboard (Port 3000)...
start "Alpha React Dashboard" cmd /k "cd alpha_platform\dashboard && npm run dev"

echo.
echo Platform successfully launched!
echo - Dashboard UI: http://localhost:3000
echo - Backend API:  http://localhost:8000
echo ==================================================
