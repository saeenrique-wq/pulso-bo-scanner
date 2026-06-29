"""Pulso BO Scanner PRO — Backend FastAPI + WebSocket + Ollama AI."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from analysis.strategy  import analyze
from analysis.reviewer  import SignalReviewer
from analysis.tracker   import save as save_sig, mark as mark_sig, win_rate, stats, load_recent
from analysis.memory    import memory as sig_memory
from ai.ollama_validator import validate as ai_validate, is_available as ollama_ok
from brokers.base        import BaseBroker, BrokerConfig
from brokers.connector   import BrokerConnector
from brokers.demo        import DemoBroker, QuotexBroker, PocketBroker, IQBroker
from utils.config        import cfg

# Telegram desactivado — señales solo por web
async def tg_send(*a, **k):        return False
async def tg_martingale(*a, **k):  return False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    S.brokers = _build_brokers()
    for bid, b in S.brokers.items():
        ok = await b.connect()
        log.info(f"[{bid}] {'OK' if ok else 'FAIL'}")
        S.connector.register(bid, b)
    if S.active_broker not in S.brokers:
        S.active_broker = next(iter(S.brokers), "demo")
    S.ollama_active = await ollama_ok(cfg.OLLAMA_MODEL)
    log.info(f"Ollama: {'activo' if S.ollama_active else 'no disponible'}")
    S.signals = load_recent(100)
    # Señales sin outcome que ya expiraron no deben bloquear el dedup
    _now = time.time()
    for _s in S.signals:
        if _s.get("outcome") is None and _now - _s.get("timestamp", 0) > 300:
            _s["outcome"] = "NO_TOMADA"
    log.info(f"Historial cargado: {len(S.signals)} señales")
    task = asyncio.create_task(scanner_loop())
    watchdog = asyncio.create_task(S.connector.start_watchdog(60))
    yield
    # shutdown
    S.scanning = False
    task.cancel()
    watchdog.cancel()
    for b in S.brokers.values():
        await b.disconnect()


app = FastAPI(title="Pulso BO Scanner PRO", version="1.0.0", lifespan=lifespan)
FRONTEND = Path(__file__).parent.parent / "frontend"

BROKER_META = {
    "demo":         {"label": "Demo",        "color": "#64748b"},
    "quotex":       {"label": "Quotex",       "color": "#00c2ff"},
    "pocketoption": {"label": "PocketOption", "color": "#ff6b00"},
    "iqoption":     {"label": "Exnova/IQ",   "color": "#8b5cf6"},
}


def _build_brokers() -> dict[str, BaseBroker]:
    out: dict[str, BaseBroker] = {}
    enabled = cfg.ENABLED_BROKERS
    if "demo" in enabled:
        out["demo"] = DemoBroker()
    if "quotex" in enabled and cfg.QUOTEX_EMAIL:
        out["quotex"] = QuotexBroker(BrokerConfig(cfg.QUOTEX_EMAIL, cfg.QUOTEX_PASSWORD, cfg.QUOTEX_DEMO))
    if "pocketoption" in enabled and cfg.POCKET_SSID:
        out["pocketoption"] = PocketBroker(BrokerConfig(demo=cfg.POCKET_DEMO, extra={"ssid": cfg.POCKET_SSID}))
    if "iqoption" in enabled and cfg.IQOPTION_EMAIL:
        out["iqoption"] = IQBroker(BrokerConfig(cfg.IQOPTION_EMAIL, cfg.IQOPTION_PASSWORD, cfg.IQOPTION_DEMO))
    return out


# ── App state ──────────────────────────────────────────────
class State:
    brokers: dict[str, BaseBroker] = {}
    active_broker: str = "demo"
    market_type: str = "REAL"
    reviewer = SignalReviewer()
    connector = BrokerConnector()
    clients: list[WebSocket] = []
    signals: list[dict] = []
    scanning: bool = False
    ollama_active: bool = False

S = State()


async def broadcast(msg: dict):
    dead = []
    for ws in S.clients:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in S.clients:
            S.clients.remove(ws)


# ── Scanner loop ───────────────────────────────────────────
async def _fetch_asset(broker, asset, mt: str) -> None:
    """Analiza un activo individual — descarga los 3 TF en PARALELO."""
    try:
        # Descargar M1, M5, M15 simultáneamente
        results = await asyncio.gather(
            broker.get_candles(asset.symbol, 60,  150),
            broker.get_candles(asset.symbol, 300, 150),
            broker.get_candles(asset.symbol, 900, 150),
            return_exceptions=True,
        )
        candles_by_tf = {
            60:  results[0] if not isinstance(results[0], Exception) else [],
            300: results[1] if not isinstance(results[1], Exception) else [],
            900: results[2] if not isinstance(results[2], Exception) else [],
        }

        wr  = win_rate(asset.symbol, None)
        sig = analyze(candles_by_tf, asset.symbol, broker.name,
                      asset.payout, mt, asset.category, wr)
        if sig is None:
            return

        # Ajustar score con historial aprendido
        sig.score = sig_memory.adjusted_score(sig.symbol, sig.score, sig.reasons)

        ok, reason = S.reviewer.review(sig)
        if not ok:
            log.debug(f"Rejected {asset.symbol}: {reason}"); return

        # ── Ollama AI validation ────────────────────────
        if cfg.OLLAMA_ENABLED and S.ollama_active:
            ai_prob = await ai_validate(sig, cfg.OLLAMA_MODEL)
            sig.ai_score = ai_prob
            if ai_prob < cfg.OLLAMA_MIN_SCORE:
                log.info(f"[AI] {asset.symbol} rechazado AI={ai_prob:.0%}"); return
        else:
            sig.ai_score = 0.0

        # Dedup final: no emitir si ya hay señal pendiente reciente del mismo par+dirección
        # Ventana de 3 min — señales antiguas sin outcome no deben bloquear para siempre
        _now_ts = time.time()
        already = any(
            x.get("symbol") == sig.symbol and
            x.get("direction") == sig.direction and
            x.get("outcome") is None and
            _now_ts - x.get("timestamp", 0) < 180
            for x in S.signals
        )
        if already:
            log.debug(f"Dedup en memoria: {sig.symbol} {sig.direction} ya pendiente"); return

        sig.win_rate_hist = wr
        sid = save_sig(sig)
        d   = sig.to_dict(); d["id"] = sid
        S.signals.insert(0, d); S.signals = S.signals[:100]

        log.info(f"✅ {sig.direction} {asset.symbol} [{mt}] "
                 f"score={sig.score} AI={sig.ai_score:.0%} vol={sig.volatility:.0f}%")

        await broadcast({"type": "signal", "data": d})
        await tg_send(sig)

    except Exception as e:
        log.warning(f"{asset.symbol}: {e}")


def _broker_for(mt: str):
    """
    OTC → solo broker real (Exnova/IQ, Pocket Option, Quotex).
         NUNCA yfinance/demo para OTC — datos falsos = señales falsas.
    REAL → demo (yfinance) cuando no hay otro broker.
    """
    if mt.upper() == "OTC":
        # Prioridad: iqoption → pocketoption → quotex
        for bid in ("iqoption", "pocketoption", "quotex"):
            b = S.brokers.get(bid)
            if b and b.is_ready():
                return b
        return None   # sin broker OTC real → no escanear
    return S.brokers.get(S.active_broker)


async def _scan_market(mt: str):
    """
    Escanea un mercado completo en paralelo.
    OTC: REQUIERE broker real (Exnova/IQ/Pocket/Quotex) — NUNCA yfinance.
    REAL: usa yfinance via DemoBroker.
    """
    from brokers.demo import TOP5_REAL

    broker = _broker_for(mt)

    if mt.upper() == "OTC":
        if not broker:
            # Informar a la UI: OTC no disponible sin broker real
            await broadcast({
                "type": "otc_status",
                "status": "no_broker",
                "message": "OTC requiere conexión al broker. Instala la extensión Chrome o abre http://localhost:8082/get-ssid"
            })
            log.info("[OTC] Sin broker real — scan OTC omitido (no se emiten señales falsas)")
            return
        # Auto-descubrimiento de activos OTC disponibles
        try:
            all_assets = await broker.get_assets(market_type="OTC")
        except Exception as e:
            log.warning(f"[OTC] get_assets error: {e}"); return
        ordered = [a for a in all_assets
                   if a.payout >= cfg.MIN_PAYOUT_PCT / 100]
        if not ordered:
            log.info("[OTC] Sin activos OTC disponibles en el broker")
            return
    else:
        if not broker or not broker.is_ready():
            log.debug("[REAL] sin broker disponible"); return
        try:
            all_assets = await broker.get_assets(market_type="REAL")
        except Exception as e:
            log.warning(f"[REAL] get_assets error: {e}"); return
        ordered = [a for a in all_assets
                   if a.symbol in TOP5_REAL
                   and a.payout >= cfg.MIN_PAYOUT_PCT / 100]

    log.info(f"Escaneando [{mt}] via {broker.name}: {[a.symbol for a in ordered]}")
    # Análisis paralelo — todos los activos simultáneamente
    await asyncio.gather(*[_fetch_asset(broker, a, mt) for a in ordered])


async def scan_once():
    """Escanea REAL y OTC en paralelo — siempre los dos mercados."""
    await asyncio.gather(
        _scan_market("REAL"),
        _scan_market("OTC"),
    )


async def scanner_loop():
    S.scanning = True
    while S.scanning:
        any_ready = any(b.is_ready() for b in S.brokers.values())
        if any_ready:
            await broadcast({"type":"scan_start","ts":time.time(),
                             "broker":S.active_broker,"market":"REAL+OTC"})
            await scan_once()
            await broadcast({"type":"scan_done","ts":time.time()})
        await asyncio.sleep(cfg.SCAN_INTERVAL)


# ── Endpoints ──────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(str(FRONTEND / "index.html"))


@app.get("/get-ssid")
async def get_ssid_page():
    """Página de extracción de SSID — sirve desde localhost para evitar CORS."""
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Conectar Exnova</title>
<style>
  body{margin:0;background:#060912;color:#e8edf5;font-family:-apple-system,sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;}
  .box{background:#0c1120;border:1px solid rgba(255,255,255,.1);border-radius:16px;
       padding:32px;max-width:500px;width:90%;text-align:center;}
  h2{color:#ffd700;margin:0 0 8px;}
  p{color:#94a3b8;font-size:.85rem;margin:0 0 20px;line-height:1.5;}
  .steps{text-align:left;background:#060912;border-radius:10px;padding:16px;margin-bottom:20px;}
  .step{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;font-size:.85rem;}
  .n{background:#ffd700;color:#060912;border-radius:50%;width:22px;height:22px;
     display:flex;align-items:center;justify-content:center;font-weight:900;flex-shrink:0;font-size:.75rem;}
  code{background:#1a2035;border:1px solid rgba(255,255,255,.1);border-radius:6px;
       padding:10px;display:block;font-size:.72rem;color:#00ff87;word-break:break-all;
       text-align:left;margin:12px 0;cursor:pointer;line-height:1.6;}
  .btn{background:linear-gradient(135deg,#00ff87,#00c96b);color:#060912;border:none;
       border-radius:8px;padding:12px 28px;font-size:.95rem;font-weight:800;
       cursor:pointer;width:100%;}
  .status{margin-top:14px;font-size:.85rem;padding:10px;border-radius:8px;display:none;}
  .ok{background:rgba(0,255,135,.1);color:#00ff87;border:1px solid rgba(0,255,135,.2);}
  .err{background:rgba(255,45,85,.1);color:#ff2d55;border:1px solid rgba(255,45,85,.2);}
</style></head>
<body>
<div class="box">
  <h2>🔑 Conectar Exnova al Scanner</h2>
  <p>Tu sesión de Exnova ya está abierta en el browser.<br>
     Sigue estos pasos para conectarla al scanner:</p>

  <div class="steps">
    <div class="step">
      <div class="n">1</div>
      <div>Ve a <b>trade.exnova.com</b> en otra pestaña (ya debes estar logueado)</div>
    </div>
    <div class="step">
      <div class="n">2</div>
      <div>Presiona <b>F12</b> → pestaña <b>Console</b></div>
    </div>
    <div class="step">
      <div class="n">3</div>
      <div>Copia y pega este código en la consola y presiona Enter:</div>
    </div>
  </div>

  <code id="snippet" onclick="copySnippet()">fetch('http://localhost:8082/api/set_ssid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:document.cookie.split(';').find(c=>c.trim().startsWith('ssid='))?.trim().slice(5)||''})}).then(r=>r.json()).then(d=>{alert(d.message||d.error)}).catch(e=>alert('Error: '+e))</code>

  <p style="color:#ffd700;font-size:.75rem;margin-top:0">👆 Haz clic aquí para copiar automáticamente</p>

  <div class="status ok" id="status-ok">✅ Exnova conectado — OTC activo los 7 días</div>
  <div class="status err" id="status-err">❌ Error al conectar</div>
</div>

<script>
function copySnippet(){
  const txt = document.getElementById('snippet').textContent;
  navigator.clipboard.writeText(txt).then(()=>{
    document.getElementById('snippet').style.borderColor='#ffd700';
    setTimeout(()=>document.getElementById('snippet').style.borderColor='',1500);
  });
}

// Escuchar si el scanner ya recibió el SSID
const ws = new WebSocket('ws://localhost:8082/ws');
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if(m.type === 'broker_connected' && m.broker === 'iqoption'){
    document.getElementById('status-ok').style.display = 'block';
  }
};
</script>
</body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.post("/api/scan")
async def api_scan():
    """Dispara un escaneo completo y espera el resultado antes de responder."""
    any_ready = any(b.is_ready() for b in S.brokers.values())
    if not any_ready:
        return JSONResponse({"error": "ningún broker disponible"}, status_code=503)
    before = len(S.signals)
    await broadcast({"type":"scan_start","ts":time.time(),"broker":S.active_broker,"market":"REAL+OTC"})
    await scan_once()
    await broadcast({"type":"scan_done","ts":time.time()})
    new_count = len(S.signals) - before
    return {"ok": True, "broker": S.active_broker, "market": "REAL+OTC",
            "new_signals": max(0, new_count)}


@app.get("/api/status")
async def api_status():
    # Siempre muestra TODOS los brokers conocidos, conectados o no
    all_brokers = []
    for bid, meta in BROKER_META.items():
        b = S.brokers.get(bid)
        all_brokers.append({
            "id":        bid,
            "label":     meta["label"],
            "color":     meta["color"],
            "connected": b.connected if b else False,
            "active":    bid == S.active_broker,
            "configured": b is not None,
        })
    return {
        "brokers": all_brokers,
        "active_broker": S.active_broker,
        "market_type":   S.market_type,
        "scanning":      S.scanning,
        "scan_interval": cfg.SCAN_INTERVAL,
        "min_payout":    cfg.MIN_PAYOUT_PCT,
        "ollama":        S.ollama_active,
        "ollama_model":  cfg.OLLAMA_MODEL,
        "telegram_configured": bool(cfg.TELEGRAM_TOKEN and "tu_token" not in cfg.TELEGRAM_TOKEN),
    }


@app.get("/api/signals")
async def api_signals(broker:str="", market:str="", cat:str="", direction:str=""):
    sigs = S.signals
    if broker:    sigs = [s for s in sigs if s.get("broker","").lower()==broker.lower()]
    if market:    sigs = [s for s in sigs if s.get("market_type","").upper()==market.upper()]
    if cat and cat!="all": sigs = [s for s in sigs if s.get("category","")==cat]
    if direction: sigs = [s for s in sigs if s.get("direction","")==direction.upper()]
    return sigs[:50]


@app.post("/api/signals/reset")
async def api_reset_signals():
    """Borra todo el historial de señales (en memoria y BD)."""
    from analysis.tracker import reset as reset_tracker
    S.signals.clear()
    try:
        reset_tracker()
    except Exception:
        pass
    await broadcast({"type": "reset"})
    log.info("Historial de senales borrado")
    return {"ok": True, "msg": "Historial borrado"}


@app.get("/api/stats")
async def api_stats():
    return stats()


@app.get("/api/assets")
async def api_assets(market_type:str="REAL"):
    broker = S.brokers.get(S.active_broker)
    if not broker or not broker.is_ready(): return []
    try:
        assets = await broker.get_assets(market_type=market_type)
        return [{"symbol":a.symbol,"payout":round(a.payout*100,1),
                 "category":a.category,"market_type":a.market_type}
                for a in assets if a.is_open]
    except Exception: return []


@app.post("/api/config")
async def api_config(body: dict):
    bid = body.get("broker_id","").lower()
    mt  = body.get("market_type","").upper()
    if bid and bid in S.brokers: S.active_broker = bid
    if mt in ("REAL","OTC"):      S.market_type  = mt
    await broadcast({"type":"config_changed","broker":S.active_broker,"market_type":S.market_type})
    return {"ok":True,"broker":S.active_broker,"market_type":S.market_type}


@app.post("/api/set_ssid")
async def api_set_ssid(body: dict):
    """Recibe SSID desde el navegador y conecta Exnova en caliente."""
    ssid = (body.get("ssid") or "").strip()
    if not ssid or len(ssid) < 20:
        return JSONResponse({"error": "SSID inválido"}, status_code=400)

    from brokers.demo import IQBroker
    from brokers.base import BrokerConfig

    # Conectar usando el SSID directo via WebSocket (sin login HTTP)
    try:
        from iqoptionapi.api import IQOptionAPI
        api = IQOptionAPI("exnova.org", "", "")
        api.set_session_cookies()

        import threading, time as _t
        from iqoptionapi.ws.client import WebsocketClient

        api.websocket_client = WebsocketClient(api)
        ws_thread = threading.Thread(target=api.websocket.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        _t.sleep(3)
        api.ssid(ssid)
        _t.sleep(2)

        iq = IQBroker.__new__(IQBroker)
        iq.connected = True
        iq._api = api
        iq.config = BrokerConfig("", "", True)
        S.brokers["iqoption"] = iq
        S.connector.register("iqoption", iq)
        S.connector._otc_cache_ts = 0   # invalidar caché de activos
        log.info(f"[Exnova] SSID recibido via /api/set_ssid — OTC activo")
        await broadcast({"type":"broker_connected","broker":"iqoption",
                         "message":"Exnova conectado — OTC activo los 7 días"})
        return {"ok": True, "message": "Exnova conectado — OTC activo 24/7"}
    except Exception as e:
        log.warning(f"[Exnova] set_ssid error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/outcome")
async def api_outcome(body: dict):
    sid     = body.get("id")
    outcome = body.get("outcome","").upper()
    if sid is None or outcome not in ("WIN","LOSS","NO_TOMADA"):
        return JSONResponse({"error":"Need id and outcome"},status_code=400)

    # Normalizar id para comparar correctamente (JSON envía int o string)
    try:    sid_int = int(sid)
    except: sid_int = None

    mark_sig(sid_int or sid, outcome)

    # Buscar señal en memoria y actualizar + registrar en memoria de aprendizaje
    sig_dict = None
    for s in S.signals:
        s_id = s.get("id")
        if s_id == sid or (sid_int is not None and s_id == sid_int):
            s["outcome"] = outcome
            # Aprendizaje: ajustar pesos del par según resultado
            if outcome in ("WIN", "LOSS"):
                sig_memory.record_result(
                    s.get("symbol", ""), outcome, s.get("reasons", []))
                log.info(f"[Memory] {s.get('symbol')} → {outcome} registrado. "
                         f"WR histórico: {sig_memory.win_rate(s.get('symbol','')):.0%}")
            if outcome == "LOSS":
                prev_mg = s.get("mg_level", 0)
                if prev_mg < 3:
                    s["mg_level"] = prev_mg + 1
                    sig_dict = dict(s)   # copia para no mutar en el broadcast
            break

    await broadcast({"type":"outcome","id":sid_int or sid,"outcome":outcome})

    # Emitir señal martingale a la UI si aplica
    if sig_dict:
        mg_sig = dict(sig_dict)
        mg_sig["id"] = f"mg_{int(time.time())}"
        mg_sig["outcome"] = None
        # Generar entrada para la siguiente vela del mismo TF
        exp_tf   = (sig_dict.get("expiration",1) or 1) * 60
        now      = time.time()
        entry_t  = int(now // exp_tf) * exp_tf + exp_tf
        mg_sig["entry_time"]  = entry_t
        mg_sig["expiry_time"] = entry_t + exp_tf
        await broadcast({"type":"martingale","data":mg_sig,"level":sig_dict["mg_level"]})

    return {"ok":True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    S.clients.append(ws)
    await ws.send_text(json.dumps({
        "type":"init","signals":S.signals[:50],
        "broker":S.active_broker,"market_type":S.market_type,
        "ollama":S.ollama_active,
    }))
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: pass
    finally:
        if ws in S.clients: S.clients.remove(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=cfg.HOST, port=cfg.PORT, reload=False)
