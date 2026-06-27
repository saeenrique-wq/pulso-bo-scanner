"""Filtro de calidad — última línea de defensa antes de emitir señal."""
from __future__ import annotations
import time
from collections import defaultdict
from datetime import datetime, timezone

MIN_SCORE     = 22
MIN_PAYOUT    = 0.80
COOLDOWN_S    = 90
MAX_DAY_ASSET = 20

# Horario REAL forex (UTC): Lun 00:00 – Vie 21:00
# Fuera de ese horario, los pares REAL no tienen liquidez — solo OTC opera 24/7
FOREX_REAL_OPEN_UTC = set(range(0, 22))   # 00:00–21:59 UTC (lun-vie)


def _market_open(market_type: str) -> tuple[bool, str]:
    """OTC siempre abierto. REAL solo Lun–Vie en horario forex."""
    mt = market_type.upper()
    if "OTC" in mt:
        return True, "OTC 24/7"
    now_utc = datetime.now(tz=timezone.utc)
    weekday = now_utc.weekday()   # 0=lunes … 5=sab, 6=dom
    hour    = now_utc.hour
    if weekday >= 5:
        return False, f"Mercado Real cerrado — fin de semana ({['Lun','Mar','Mie','Jue','Vie','Sab','Dom'][weekday]})"
    if hour not in FOREX_REAL_OPEN_UTC:
        return False, f"Mercado Real cerrado — fuera de horario (UTC {hour:02d}:00)"
    return True, "OK"


class SignalReviewer:
    def __init__(self):
        self._last:  dict[tuple, float] = {}
        self._daily: dict[tuple, int]   = defaultdict(int)

    def review(self, sig) -> tuple[bool, str]:
        if sig.score < MIN_SCORE:
            return False, f"Score {sig.score} < {MIN_SCORE}"
        if sig.payout < MIN_PAYOUT:
            return False, f"Payout {sig.payout*100:.0f}% < {MIN_PAYOUT*100:.0f}%"

        ok, reason = _market_open(sig.market_type)
        if not ok:
            return False, reason

        key = (sig.symbol, sig.direction)
        now = time.time()
        if now - self._last.get(key, 0) < COOLDOWN_S:
            rem = int(COOLDOWN_S - (now - self._last[key]))
            return False, f"Cooldown {rem}s"

        date = datetime.utcnow().strftime("%Y-%m-%d")
        dkey = (sig.symbol, date)
        if self._daily[dkey] >= MAX_DAY_ASSET:
            return False, f"Cap diario {MAX_DAY_ASSET} para {sig.symbol}"

        self._last[key] = now
        self._daily[dkey] += 1
        return True, "OK"
