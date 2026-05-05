@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo    Starting Neurognome MQTT Simulator
echo ==========================================
echo.
echo Open http://localhost:8090/
echo.

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo venv not found, using python from PATH.
)

python -m uvicorn simulator_service.main:app --reload --host 0.0.0.0 --port 8090
