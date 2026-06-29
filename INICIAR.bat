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

:: Matar instancias anteriores del scanner
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *pulso*" >nul 2>&1
taskkill /F /IM cloudflared.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: Iniciar el scanner en segundo plano
echo  [1/3] Iniciando scanner backend (puerto 8082)...
start "PulsoScanner" /min cmd /c "cd /d "%~dp0backend" && python main.py 2>&1 | tee "%~dp0scanner.log""
timeout /t 4 /nobreak >nul

:: Verificar que el scanner arranco
curl -s http://localhost:8082/api/stats >nul 2>&1
if errorlevel 1 (
    echo  [!] Esperando que el scanner arranque...
    timeout /t 5 /nobreak >nul
)

:: Iniciar tunel cloudflare (HTTPS publico gratis)
echo  [2/3] Iniciando tunel HTTPS publico...
start "PulsoTunel" /min cmd /c ""%~dp0cloudflared.exe" tunnel --url http://localhost:8082 --no-autoupdate 2>&1 | tee "%~dp0tunnel.log""
timeout /t 5 /nobreak >nul

:: Extraer la URL publica del tunel del log
echo  [3/3] Obteniendo URL publica...
timeout /t 3 /nobreak >nul

set TUNNEL_URL=
for /f "tokens=*" %%i in ('findstr /i "trycloudflare.com" "%~dp0tunnel.log" 2^>nul') do (
    set LINE=%%i
)

:: Abrir el scanner en el browser local
start "" "http://localhost:8082"

echo.
echo  ================================================
echo   SCANNER ACTIVO
echo.
echo   Local:   http://localhost:8082
echo.
echo   Buscando URL publica del tunel...
echo   (revisar archivo tunnel.log cuando este lista)
echo  ================================================
echo.

:: Mostrar URL publica en tiempo real del log del tunel
echo  Esperando URL del tunel (puede tardar 10-15 segundos)...
:WAIT_URL
timeout /t 2 /nobreak >nul
findstr /i "trycloudflare.com" "%~dp0tunnel.log" >nul 2>&1
if errorlevel 1 goto WAIT_URL

echo.
echo  ================================================
echo   URL PUBLICA (copia esta para abrir desde celular o internet):
findstr /i "trycloudflare.com" "%~dp0tunnel.log" | findstr /v "ERR\|WARN" | head -1
echo  ================================================
echo.
echo  Para conectar Exnova al scanner:
echo  1. Abre la URL publica en tu browser
echo  2. Ve a /get-ssid en esa URL
echo.
echo  Presiona cualquier tecla para cerrar esta ventana (el scanner sigue corriendo)
pause >nul
