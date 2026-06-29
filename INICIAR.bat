@echo off
title Pulso BO Scanner PRO
color 0A
cls

echo.
echo  ================================================
echo   PULSO BO SCANNER PRO - Iniciando...
echo  ================================================
echo.

cd /d "%~dp0"

:: Matar instancias anteriores
taskkill /F /IM cloudflared.exe >nul 2>&1

echo  [1/3] Iniciando scanner (puerto 8082)...
start "PulsoScanner" /min cmd /c "cd /d "%~dp0backend" && python main.py > "%~dp0scanner.log" 2>&1"
timeout /t 6 /nobreak >nul

echo  [2/3] Iniciando tunel HTTPS publico...
start "PulsoTunel" /min cmd /c ""%~dp0cloudflared.exe" tunnel --url http://localhost:8082 --no-autoupdate > "%~dp0tunnel.log" 2>&1"
timeout /t 5 /nobreak >nul

echo  [3/3] Abriendo scanner en el browser...
start "" "http://localhost:8082"

echo.
echo  ================================================
echo   SCANNER ACTIVO en http://localhost:8082
echo.
echo   Para conectar Exnova al OTC:
echo   -> Doble clic en CONECTAR_EXNOVA.bat
echo.
echo   Para ver URL publica del tunel:
echo   -> Abre el archivo tunnel.log
echo  ================================================
echo.
echo  Presiona cualquier tecla para cerrar (el scanner sigue corriendo)
pause >nul
