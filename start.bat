@echo off
title Pulso BO Scanner PRO
cd /d "%~dp0"

if not exist ".env" (
    echo Creando .env desde .env.example...
    copy .env.example .env
    echo.
    echo IMPORTANTE: Edita .env con tus tokens antes de continuar.
    pause
)

echo Instalando dependencias...
pip install -r backend\requirements.txt --quiet

echo.
echo ========================================
echo   PULSO BO SCANNER PRO
echo   http://localhost:8080
echo ========================================
echo.

cd backend
python main.py
pause
