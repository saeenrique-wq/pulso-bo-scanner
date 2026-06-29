@echo off
title Conectando Exnova al Scanner...
cd /d "%~dp0"
"C:\Users\saems\AppData\Local\Programs\Python\Python312\python.exe" "%~dp0conectar_exnova.py"
if errorlevel 1 (
    echo.
    echo ERROR - Presiona cualquier tecla para ver el detalle
    pause >nul
)
