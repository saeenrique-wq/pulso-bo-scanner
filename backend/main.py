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
from ai.ollama_validator import validate as ai_validate, is_available as ollama_ok, MIN_AI_SCORE
from brokers.base        import BaseBroker, BrokerConfig
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
    if S.active_broker not in S.brokers:
        S.active_broker = next(iter(S.brokers), "demo")
    S.ollama_active = await ollama_ok(cfg.OLLAMA_MODEL)
    log.info(f"Ollama: {'activo' if S.ollama_active else 'no disponible'}")
    # Recuperar historial de señales de la BD
    S.signals = load_recent(100)
    log.info(f"Historial cargado: {len(S.signals)} señales")
    task = asyncio.create_task(scanner_loop())
    yield
    # shutdown
    S.scanning = False
    task.cancel()
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


async def _scan_market(broker, mt: str):
    """Escanea los 5 pares en un mercado (REAL u OTC)."""
    from brokers.demo import TOP5_REAL, TOP5_OTC
    try:
        all_assets = await broker.get_assets(market_type=mt)
    except Exception as e:
        log.warning(f"get_assets [{mt}]: {e}"); return

    top5    = TOP5_OTC if mt == "OTC" else TOP5_REAL
    ordered = [a for a in all_assets
               if a.symbol in top5
               and a.payout >= cfg.MIN_PAYOUT_PCT / 100]

    log.info(f"Escaneando [{mt}]: {[a.symbol for a in ordered]}")
    await asyncio.gather(*[_fetch_asset(broker, a, mt) for a in ordered])


async def scan_once():
    """Escanea REAL y OTC en paralelo — siempre los dos mercados."""
    broker = S.brokers.get(S.active_broker)
    if not broker or not broker.is_ready():
        return
    await asyncio.gather(
        _scan_market(broker, "REAL"),
        _scan_market(broker, "OTC"),
    )


async def scanner_loop():
    S.scanning = True
    while S.scanning:
        broker = S.brokers.get(S.active_broker)
        if broker and broker.is_ready():
            await broadcast({"type":"scan_start","ts":time.time(),
                             "broker":broker.name,"market":"REAL+OTC"})
            await scan_once()
            await broadcast({"type":"scan_done","ts":time.time()})
        await asyncio.sleep(cfg.SCAN_INTERVAL)


# ── Endpoints ──────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(str(FRONTEND / "index.html"))


@app.post("/api/scan")
async def api_scan():
    """Dispara un escaneo completo y espera el resultado antes de responder."""
    broker = S.brokers.get(S.active_broker)
    if not broker or not broker.is_ready():
        return JSONResponse({"error": "broker no disponible"}, status_code=503)
    before = len(S.signals)
    await broadcast({"type":"scan_start","ts":time.time(),"broker":broker.name,"market":S.market_type})
    await scan_once()
    await broadcast({"type":"scan_done","ts":time.time()})
    new_count = len(S.signals) - before
    return {"ok": True, "broker": S.active_broker, "market": S.market_type,
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


@app.post("/api/outcome")
async def api_outcome(body: dict):
    sid     = body.get("id")
    outcome = body.get("outcome","").upper()
    if sid is None or outcome not in ("WIN","LOSS"):
        return JSONResponse({"error":"Need id and outcome"},status_code=400)

    # Normalizar id para comparar correctamente (JSON envía int o string)
    try:    sid_int = int(sid)
    except: sid_int = None

    mark_sig(sid_int or sid, outcome)

    # Buscar señal en memoria y actualizar
    sig_dict = None
    for s in S.signals:
        s_id = s.get("id")
        if s_id == sid or (sid_int is not None and s_id == sid_int):
            s["outcome"] = outcome
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
