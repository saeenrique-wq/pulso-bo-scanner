"""Filtro de calidad — última línea de defensa antes de emitir señal."""
from __future__ import annotations
import time
from collections import defaultdict
from datetime import datetime, timezone

MIN_SCORE     = 42    # score mínimo para emitir señal
MIN_PAYOUT    = 0.80
COOLDOWN_S    = 60    # 1 min — permite señales M1 frecuentes
MAX_DAY_ASSET = 20    # suficientes señales por par por día

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
        self._last:      dict[tuple, float] = {}   # (sym, dir) → timestamp
        self._last_hash: dict[tuple, str]   = {}   # (sym, dir) → hash de razones
        self._daily:     dict[tuple, int]   = defaultdict(int)

    def _reason_hash(self, sig) -> str:
        """Huella del patrón — mismas razones = misma vela analizada."""
        reasons = sorted(r for r in (sig.reasons or []) if 'Patron' in r or 'Pullback' in r)
        return '|'.join(reasons) if reasons else ''

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

        # ── Cooldown temporal ──────────────────────────────────
        elapsed = now - self._last.get(key, 0)
        if elapsed < COOLDOWN_S:
            rem = int(COOLDOWN_S - elapsed)
            return False, f"Cooldown {rem}s"

        # ── Dedup por contenido: mismo patrón = misma vela ────
        new_hash = self._reason_hash(sig)
        if new_hash and new_hash == self._last_hash.get(key, ''):
            # Extiende el cooldown 5 min más para evitar loops en datos estáticos
            self._last[key] = now
            return False, "Patron identico a senial anterior — datos sin cambios"

        # ── Cap diario ─────────────────────────────────────────
        date = datetime.utcnow().strftime("%Y-%m-%d")
        dkey = (sig.symbol, date)
        if self._daily[dkey] >= MAX_DAY_ASSET:
            return False, f"Cap diario {MAX_DAY_ASSET} para {sig.symbol}"

        self._last[key]      = now
        self._last_hash[key] = new_hash
        self._daily[dkey]   += 1
        return True, "OK"
