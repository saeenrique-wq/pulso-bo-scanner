"""Filtro de calidad — última línea de defensa antes de emitir señal."""
from __future__ import annotations
import time
from collections import defaultdict
from datetime import datetime, timezone

MIN_SCORE    = 78
MIN_PAYOUT   = 0.80
COOLDOWN_S   = 300   # 5 min mismo activo+dirección
MAX_DAY_ASSET = 8    # máx señales/activo/día
ACTIVE_HOURS = set(range(6, 23))   # UTC 06:00-22:59


class SignalReviewer:
    def __init__(self):
        self._last: dict[tuple, float] = {}
        self._daily: dict[tuple, int] = defaultdict(int)

    def review(self, sig) -> tuple[bool, str]:
        if sig.score < MIN_SCORE:
            return False, f"Score {sig.score} < {MIN_SCORE}"
        if sig.payout < MIN_PAYOUT:
            return False, f"Payout {sig.payout*100:.0f}% < {MIN_PAYOUT*100:.0f}%"

        h = datetime.now(tz=timezone.utc).hour
        if h not in ACTIVE_HOURS:
            return False, f"Fuera de horario activo (UTC {h}:00)"

        key = (sig.symbol, sig.direction)
        now = time.time()
        if now - self._last.get(key, 0) < COOLDOWN_S:
            rem = int(COOLDOWN_S - (now - self._last[key]))
            return False, f"Cooldown {rem}s"

        date = datetime.utcnow().strftime("%Y-%m-%d")
        dkey = (sig.symbol, date)
        if self._daily[dkey] >= MAX_DAY_ASSET:
            return False, f"Cap diario {MAX_DAY_ASSET} señales para {sig.symbol}"

        self._last[key] = now
        self._daily[dkey] += 1
        return True, "OK"
