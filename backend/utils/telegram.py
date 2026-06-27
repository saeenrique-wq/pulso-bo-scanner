from __future__ import annotations
import httpx
from datetime import datetime, timezone
from utils.config import cfg

def _token():   return cfg.TELEGRAM_TOKEN
def _chat_id(): return cfg.TELEGRAM_CHAT_ID

# Nivel martingale en curso por activo: {symbol: nivel_actual}
_mg_state: dict[str, int] = {}
MAX_MG = 3          # máximo 3 pasos martingale
MIN_WR_MG = 0.40    # cancelar martingale si win rate baja de 40%


async def send(signal, mg_level: int = 0) -> bool:
    """Envía señal al grupo Telegram.
    mg_level=0 = señal normal, 1/2/3 = paso martingale.
    """
    if not _token() or not _chat_id():
        return False

    d = signal.direction
    entrada = datetime.now(timezone.utc).strftime("%H:%M:%S")
    flecha  = "🟢" if d == "CALL" else "🔴"
    dir_txt = "CALL ▲" if d == "CALL" else "PUTT ▼"

    if mg_level == 0:
        header = "🔰 ¡HA LLEGADO UNA SEÑAL!"
    else:
        header = f"⚠️ MARTINGALE M{mg_level} — {'DUPLICA TU ENTRADA' if mg_level==1 else 'TRIPLICA' if mg_level==2 else '4X'}"

    ai_line = f"🤖 AI Score: {signal.ai_score*100:.0f}%\n" if signal.ai_score > 0 else ""
    score_line = f"📊 Confluencia: {signal.score}/100\n"

    text = (
        f"{header}\n\n"
        f"🔰 ACTIVO: *{signal.symbol}*\n"
        f"⏰ TIEMPO: *{signal.expiration} MINUTO{'S' if signal.expiration>1 else ''}*\n\n"
        f"HORA DE ENTRADA\n"
        f"🕒 {entrada}\n\n"
        f"{flecha} DIRECCIÓN: *{dir_txt}*\n\n"
        f"{ai_line}{score_line}"
        f"💰 Payout: *{signal.payout*100:.0f}%*\n\n"
        f"🔥 ¡BUENA SUERTE A TODOS! 🔥\n"
        f"🚫 _Sin Martingale base — Kelly sizing: {signal.kelly_pct*100:.1f}%_"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{_token()}/sendMessage",
                json={"chat_id": _chat_id(), "text": text, "parse_mode": "Markdown"},
            )
        return r.status_code == 200
    except Exception:
        return False


async def send_martingale(signal, level: int) -> bool:
    """Envía alerta de martingale para señal perdida."""
    if not _token() or not _chat_id() or level > MAX_MG:
        return False
    if signal.win_rate_hist > 0 and signal.win_rate_hist < MIN_WR_MG:
        await _send_msg(
            f"⛔ *MARTINGALE CANCELADO*\n"
            f"Win rate de {signal.symbol} es {signal.win_rate_hist*100:.0f}% — por debajo del mínimo ({MIN_WR_MG*100:.0f}%)"
        )
        return False
    mult = ["", "2x", "3x", "4x"][level]
    entrada = datetime.now(timezone.utc).strftime("%H:%M:%S")
    d = signal.direction
    flecha = "🟢" if d == "CALL" else "🔴"
    text = (
        f"⚠️ *MARTINGALE M{level}* — ENTRADA *{mult}*\n\n"
        f"🔰 ACTIVO: *{signal.symbol}*\n"
        f"⏰ TIEMPO: *{signal.expiration} MIN*\n"
        f"🕒 ENTRADA: {entrada}\n"
        f"{flecha} DIRECCIÓN: *{d}*\n\n"
        f"🔥 Último Martingale permitido: M{MAX_MG}"
    )
    return await _send_msg(text)


async def _send_msg(text: str) -> bool:
    if not _token() or not _chat_id():
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{_token()}/sendMessage",
                json={"chat_id": _chat_id(), "text": text, "parse_mode": "Markdown"},
            )
        return r.status_code == 200
    except Exception:
        return False
