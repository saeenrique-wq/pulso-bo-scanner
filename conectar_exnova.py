"""Conecta Exnova al scanner automaticamente."""
import subprocess, time, sys, os

os.environ["PYTHONIOENCODING"] = "utf-8"

def pip_install(pkg):
    subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"],
                   capture_output=True)

# Instalar dependencias si faltan
for pkg in ["pyautogui", "pygetwindow", "pyperclip"]:
    try:
        __import__(pkg.replace("-","_"))
    except ImportError:
        print(f"Instalando {pkg}...")
        pip_install(pkg)

import pyautogui
import pygetwindow as gw
import pyperclip

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

print("=" * 50)
print("  PULSO BO - Conectar Exnova")
print("=" * 50)

# 1. Verificar que el scanner este corriendo
print("\n[1/4] Verificando scanner en puerto 8082...")
try:
    import urllib.request
    urllib.request.urlopen("http://localhost:8082/api/stats", timeout=4)
    print("      Scanner OK")
except Exception:
    print("\n  ERROR: El scanner no esta corriendo.")
    print("  Ejecuta INICIAR.bat primero, espera 10 segundos y vuelve a correr este archivo.\n")
    input("Presiona Enter para salir...")
    sys.exit(1)

# 2. Abrir Exnova en Chrome
print("\n[2/4] Abriendo trade.exnova.com en Chrome...")
subprocess.Popen('start chrome --new-window "https://trade.exnova.com/platform"',
                 shell=True)
print("      Esperando que cargue la pagina (12 segundos)...")
time.sleep(12)

# 3. Buscar y activar la ventana de Exnova
print("\n[3/4] Buscando ventana de Chrome con Exnova...")
exnova_win = None
for intento in range(8):
    wins = gw.getAllWindows()
    for w in wins:
        t = (w.title or "").lower()
        if ("exnova" in t or "platform" in t) and "chrome" in t:
            exnova_win = w
            break
    if exnova_win:
        break
    time.sleep(2)
    print(f"      Intento {intento+1}/8...")

if not exnova_win:
    # Tomar cualquier Chrome como fallback
    chrome_wins = [w for w in gw.getAllWindows()
                   if "chrome" in (w.title or "").lower() and w.width > 400]
    if chrome_wins:
        exnova_win = chrome_wins[0]
        print(f"      Usando Chrome: {exnova_win.title[:60]}")
    else:
        print("\n  ERROR: No se encontro Chrome abierto.")
        input("Presiona Enter para salir...")
        sys.exit(1)
else:
    print(f"      Encontrada: {exnova_win.title[:60]}")

# Activar la ventana
try:
    exnova_win.activate()
    time.sleep(1)
    exnova_win.maximize()
    time.sleep(0.8)
except Exception as e:
    print(f"      Advertencia al activar ventana: {e}")
    # Intentar con alt+tab como fallback
    pyautogui.hotkey('alt', 'tab')
    time.sleep(0.5)

# 4. Abrir consola y ejecutar snippet
print("\n[4/4] Ejecutando extraccion de SSID...")
print("      Abriendo consola de Chrome (Ctrl+Shift+J)...")
pyautogui.hotkey('ctrl', 'shift', 'j')
time.sleep(3)

SNIPPET = (
    "fetch('http://localhost:8082/api/set_ssid',{"
    "method:'POST',"
    "headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({ssid:document.cookie.split(';')"
    ".find(c=>c.trim().startsWith('ssid='))?.trim().slice(5)||''})"
    "}).then(r=>r.json()).then(d=>alert(d.ok?'CONECTADO: '+d.message:('ERROR: '+(d.error||JSON.stringify(d))))"
    ").catch(e=>alert('Scanner apagado? Error: '+e))"
)

print("      Pegando y ejecutando codigo...")
pyperclip.copy(SNIPPET)
time.sleep(0.3)

# Hacer clic en el area de consola para asegurarse que esta enfocada
# La consola DevTools suele estar en la parte inferior
screen_w, screen_h = pyautogui.size()
# Clic en parte inferior de la pantalla donde suele estar la consola
pyautogui.click(screen_w // 2, int(screen_h * 0.88))
time.sleep(0.5)

# Seleccionar todo y pegar
pyautogui.hotkey('ctrl', 'a')
time.sleep(0.2)
pyautogui.hotkey('ctrl', 'v')
time.sleep(0.4)
pyautogui.press('enter')

print("      Codigo ejecutado. Esperando respuesta...")
time.sleep(4)

# Verificar si se conecto
print("\n[OK] Revisando estado de conexion...")
try:
    import json, urllib.request
    resp = urllib.request.urlopen("http://localhost:8082/api/status", timeout=5)
    data = json.loads(resp.read())
    brokers = {b["id"]: b for b in data.get("brokers", [])}
    iq = brokers.get("iqoption", {})
    if iq.get("connected"):
        print("\n" + "="*50)
        print("  EXNOVA CONECTADO - OTC ACTIVO!")
        print("  Los 4 pares OTC ahora generan senales reales.")
        print("="*50 + "\n")
    else:
        print("\n  Estado: broker Exnova no aparece conectado todavia.")
        print("  Si aparecio un alert en Chrome con 'CONECTADO' -> funciono bien.")
        print("  Si dice 'ERROR' -> verifica que estes logueado en trade.exnova.com\n")
except Exception as e:
    print(f"\n  No se pudo verificar estado: {e}")
    print("  Revisa si aparecio un alert en Chrome con el resultado.")

input("\nPresiona Enter para cerrar...")
