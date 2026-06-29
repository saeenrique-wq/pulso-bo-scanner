"""Memoria de señales — almacena resultados y recalibra pesos de indicadores."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

MEMORY_FILE = Path(__file__).parent.parent.parent / "data" / "signal_memory.json"
LEARNING_RATE = 0.1  # cuánto mueve cada WIN/LOSS los pesos

# Pesos iniciales por indicador (nombre parcial → peso)
DEFAULT_WEIGHTS: dict[str, float] = {
    "Patron":       1.40,
    "Engulfing":    1.40,
    "Morning Star": 1.50,
    "Evening Star": 1.50,
    "Pullback":     1.30,
    "EMA":          1.20,
    "MACD cruce":   1.30,
    "MACD momentum":1.10,
    "BB banda":     1.25,
    "Stoch giro":   1.25,
    "RSI":          1.10,
    "ADX":          1.20,
    "Soporte":      1.15,
    "Resistencia":  1.15,
    "3 Soldados":   1.35,
    "3 Cuervos":    1.35,
    "Hammer":       1.25,
    "Shooting Star":1.25,
    "Pin Bar":      1.20,
    "Marubozu":     1.15,
}


class SignalMemory:
    def __init__(self):
        self._data: dict = {}   # asset → {wins, losses, weights, last_result}
        self._load()

    def _load(self):
        try:
            if MEMORY_FILE.exists():
                self._data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def _save(self):
        try:
            MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            MEMORY_FILE.write_text(json.dumps(self._data, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        except Exception:
            pass

    def _asset_data(self, symbol: str) -> dict:
        if symbol not in self._data:
            self._data[symbol] = {
                "wins": 0, "losses": 0,
                "weights": dict(DEFAULT_WEIGHTS),
                "last_updated": 0,
            }
        return self._data[symbol]

    # ── Consultas ──────────────────────────────────────────
    def win_rate(self, symbol: str) -> float:
        d = self._data.get(symbol, {})
        w, l = d.get("wins", 0), d.get("losses", 0)
        total = w + l
        return w / total if total >= 5 else 0.55  # prior si < 5 muestras

    def get_weights(self, symbol: str) -> dict[str, float]:
        return dict(self._asset_data(symbol)["weights"])

    def total_trades(self, symbol: str) -> int:
        d = self._data.get(symbol, {})
        return d.get("wins", 0) + d.get("losses", 0)

    # ── Actualización ──────────────────────────────────────
    def record_result(self, symbol: str, outcome: str, reasons: list[str]):
        """
        outcome: "WIN" o "LOSS"
        reasons: lista de strings con los indicadores que generaron la señal
        """
        if outcome not in ("WIN", "LOSS"):
            return
        d = self._asset_data(symbol)
        is_win = outcome == "WIN"

        if is_win:
            d["wins"] += 1
        else:
            d["losses"] += 1

        d["last_updated"] = time.time()

        # Recalibrar pesos según resultado
        for reason in (reasons or []):
            for key in DEFAULT_WEIGHTS:
                if key.lower() in reason.lower():
                    current = d["weights"].get(key, 1.0)
                    if is_win:
                        d["weights"][key] = min(2.0, current + LEARNING_RATE * 0.1)
                    else:
                        d["weights"][key] = max(0.5, current - LEARNING_RATE * 0.1)

        self._save()

    # ── Score ajustado por historial ───────────────────────
    def adjusted_score(self, symbol: str, raw_score: int, reasons: list[str]) -> int:
        """
        Multiplica el score crudo por los pesos aprendidos de los indicadores.
        Retorna score ajustado 0-100.
        """
        if not reasons:
            return raw_score

        weights = self.get_weights(symbol)
        total_weight = 0.0
        weighted_score = 0.0
        n = 0

        for reason in reasons:
            matched = 1.0
            for key, w in weights.items():
                if key.lower() in reason.lower():
                    matched = w
                    break
            weighted_score += raw_score * matched
            total_weight += matched
            n += 1

        if n == 0 or total_weight == 0:
            return raw_score

        adjusted = int((weighted_score / total_weight))

        # Bonus por historial bueno (>60% win rate con >= 10 trades)
        wr = self.win_rate(symbol)
        total = self.total_trades(symbol)
        if total >= 10:
            if wr >= 0.65:
                adjusted = min(100, int(adjusted * 1.08))
            elif wr < 0.40:
                adjusted = max(0, int(adjusted * 0.90))

        return min(100, max(0, adjusted))


# Singleton global
memory = SignalMemory()
