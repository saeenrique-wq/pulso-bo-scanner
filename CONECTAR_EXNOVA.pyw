"""
CONECTAR_EXNOVA.pyw
Abre Exnova en Chrome, extrae el SSID automaticamente y lo envia al scanner.
Doble clic para ejecutar — NO abre ventana de consola (.pyw).
"""
import subprocess, time, sys, os
import tkinter as tk
from tkinter import messagebox

def run():
    root = tk.Tk()
    root.withdraw()  # ocultar ventana principal

    try:
        import pyautogui
        import pygetwindow as gw
        import pyperclip
    except ImportError:
        subprocess.run([sys.executable, '-m', 'pip', 'install',
                        'pyautogui', 'pygetwindow', 'pyperclip', '-q'],
                       capture_output=True)
        import pyautogui, pygetwindow as gw, pyperclip

    pyautogui.FAILSAFE = True

    msg_win = tk.Toplevel(root)
    msg_win.title("Pulso BO — Conectando Exnova")
    msg_win.geometry("380x160")
    msg_win.configure(bg="#060912")
    msg_win.resizable(False, False)
    # Centrar
    msg_win.update_idletasks()
    x = (msg_win.winfo_screenwidth() - 380) // 2
    y = (msg_win.winfo_screenheight() - 160) // 2
    msg_win.geometry(f"380x160+{x}+{y}")
    msg_win.attributes('-topmost', True)

    lbl = tk.Label(msg_win, text="Abriendo Exnova en Chrome...",
                   bg="#060912", fg="#e8edf5", font=("Segoe UI", 11))
    lbl.pack(pady=20)
    sub = tk.Label(msg_win, text="No toques el mouse por 15 segundos",
                   bg="#060912", fg="#94a3b8", font=("Segoe UI", 9))
    sub.pack()
    msg_win.update()

    def update(text, sub_text=""):
        lbl.config(text=text)
        sub.config(text=sub_text)
        msg_win.update()

    # 1. Verificar que el scanner este corriendo
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8082/api/stats", timeout=3)
    except Exception:
        update("❌ El scanner no está corriendo",
               "Ejecuta INICIAR.bat primero, luego vuelve a intentarlo")
        time.sleep(4)
        msg_win.destroy(); root.destroy(); return

    # 2. Abrir trade.exnova.com en Chrome
    update("Abriendo trade.exnova.com...")
    subprocess.Popen('start chrome "https://trade.exnova.com/platform"',
                     shell=True)
    time.sleep(8)  # esperar carga de página

    # 3. Buscar la ventana de Chrome con Exnova
    update("Buscando ventana de Exnova...")
    exnova_win = None
    for attempt in range(6):
        all_wins = gw.getAllWindows()
        for w in all_wins:
            t = (w.title or "").lower()
            if ('exnova' in t or 'trade' in t) and 'chrome' in t:
                exnova_win = w
                break
        if exnova_win:
            break
        time.sleep(2)

    if not exnova_win:
        # Tomar el Chrome más reciente
        chrome_wins = [w for w in gw.getAllWindows()
                       if 'chrome' in (w.title or "").lower() and w.width > 400]
        exnova_win = chrome_wins[0] if chrome_wins else None

    if exnova_win:
        try:
            exnova_win.activate()
            exnova_win.maximize()
            time.sleep(1)
        except Exception:
            pass

    # 4. Abrir consola del navegador (Ctrl+Shift+J)
    update("Abriendo consola de Chrome...")
    pyautogui.hotkey('ctrl', 'shift', 'j')
    time.sleep(2.5)

    # 5. Snippet para extraer SSID y enviarlo al scanner
    SNIPPET = (
        "fetch('http://localhost:8082/api/set_ssid',{"
        "method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({ssid:document.cookie.split(';')"
        ".find(c=>c.trim().startsWith('ssid='))?.trim().slice(5)||''})"
        "}).then(r=>r.json()).then(d=>{"
        "document.title='[SSID '+(d.ok?'OK':'ERR')+'] '+document.title;"
        "alert(d.message||d.error);"
        "}).catch(e=>alert('Error: '+e))"
    )

    # 6. Copiar al portapapeles y pegar en la consola
    update("Enviando SSID al scanner...", "Casi listo...")
    try:
        pyperclip.copy(SNIPPET)
    except Exception:
        # Fallback: usar pyautogui write
        pass

    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'a')   # seleccionar todo (limpiar input anterior)
    time.sleep(0.2)
    try:
        pyautogui.hotkey('ctrl', 'v')   # pegar snippet
    except Exception:
        pyautogui.write(SNIPPET, interval=0.01)
    time.sleep(0.5)
    pyautogui.press('enter')         # ejecutar

    # 7. Esperar resultado y verificar
    time.sleep(3)
    update("Verificando conexion...")

    try:
        import json, urllib.request
        resp = urllib.request.urlopen("http://localhost:8082/api/status", timeout=5)
        data = json.loads(resp.read())
        brokers = {b['id']: b for b in data.get('brokers', [])}
        iq = brokers.get('iqoption', {})
        if iq.get('connected'):
            update("Exnova conectado exitosamente!")
            msg_win.destroy()
            root.destroy()
            messagebox.showinfo("Pulso BO",
                "Exnova conectado!\n\nOTC activo los 7 dias.\nEl scanner ahora da senales de los 4 pares OTC.")
            return
    except Exception:
        pass

    # Verificar por titulo de ventana
    for w in gw.getAllWindows():
        if 'ssid ok' in (w.title or "").lower():
            update("Exnova conectado exitosamente!")
            msg_win.destroy(); root.destroy()
            messagebox.showinfo("Pulso BO",
                "Exnova conectado!\n\nOTC activo. El scanner ahora analiza\nlos 4 pares OTC en tiempo real.")
            return

    # Si no se pudo verificar automaticamente, mostrar instruccion simple
    update("Revisa si aparecio un mensaje de confirmacion",
           "Si aparecio 'Exnova conectado' -> todo listo!")
    time.sleep(4)
    msg_win.destroy()
    root.destroy()


if __name__ == "__main__":
    run()
