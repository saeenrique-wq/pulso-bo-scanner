"""Estrategia opciones binarias — Acción del Precio Pura + Pullbacks.

Señal VÁLIDA requiere:
  1. Filtro de ruido rápido (chop, cuerpo mínimo, inside-bar)
  2. Patrón de vela PRESENTE (hammer, engulfing, pin bar, morning/evening star)
  3. Contexto técnico alineado (S/R, EMA, oscilador de confirmación)
  4. ≥2 TF concordando (o 1 TF con score ≥ 65)

M1  — Reversión en extremos: patrón + BB extremo + Stoch girado
M5  — Pullback a EMA21: patrón al tocar EMA + MACD confirmación
M15 — Tendencia + S/R: EMA triple + ADX + patrón de vela
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from .indicators import adx, atr, bollinger, chop_index, ema, macd, rsi, stoch

Direction = Literal["CALL", "PUT"]

# ── Umbrales ───────────────────────────────────────────────
MIN_COMPOSITE = 32    # score mínimo para emitir señal
MIN_TF_AGREE  = 2     # TF deben coincidir (salvo score ≥ 65)
MAX_CHOP      = 60.0  # mercado lateral — descartar
MIN_PAYOUT    = 0.80

TIMEFRAMES = [60, 300, 900]
TF_NAMES   = {60: "M1", 300: "M5", 900: "M15"}
EXPIRATION = {60: 1, 300: 5, 900: 15}
WEIGHTS    = {60: 0.25, 300: 0.35, 900: 0.40}


# ── Dataclasses ────────────────────────────────────────────
@dataclass
class TFResult:
    tf: int
    direction: Direction | None
    score: int
    reasons: list[str] = field(default_factory=list)
    chop: float = 50.0
    volatility: float = 50.0


@dataclass
class Signal:
    symbol: str
    broker: str
    direction: Direction
    score: int
    payout: float
    expiration: int
    market_type: str   = "REAL"
    category: str      = "Forex"
    timestamp: float   = field(default_factory=time.time)
    reasons: list[str] = field(default_factory=list)
    tf_results: list[TFResult] = field(default_factory=list)
    win_rate_hist: float = 0.0
    ai_score: float  = 0.0
    kelly_pct: float = 0.0
    volatility: float = 50.0

    def to_dict(self) -> dict:
        return {
            "symbol":        self.symbol,
            "broker":        self.broker,
            "direction":     self.direction,
            "score":         self.score,
            "payout":        round(self.payout * 100, 1),
            "expiration":    self.expiration,
            "market_type":   self.market_type,
            "category":      self.category,
            "timestamp":     self.timestamp,
            "reasons":       self.reasons,
            "win_rate_hist": round(self.win_rate_hist * 100, 1),
            "ai_score":      round(self.ai_score * 100, 1),
            "kelly_pct":     round(self.kelly_pct * 100, 1),
            "volatility":    round(self.volatility, 1),
            "tf_results": [
                {"tf": TF_NAMES[t.tf], "dir": t.direction,
                 "score": t.score, "chop": round(t.chop, 1),
                 "vol": round(t.volatility, 1),
                 "reasons": t.reasons}
                for t in self.tf_results
            ],
        }


# ── Utilidades ─────────────────────────────────────────────
def _to_df(candles) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(
        [(c.time, c.open, c.high, c.low, c.close, c.volume)
         for c in candles],
        columns=["time", "open", "high", "low", "close", "volume"],
    ).sort_values("time").reset_index(drop=True)
    while len(df) > 30 and df["close"].iloc[-1] == df["close"].iloc[-2]:
        df = df.iloc[:-1]
    return df


def _vol_score(close: pd.Series, high: pd.Series, low: pd.Series) -> float:
    if len(close) < 10:
        return 50.0
    price = close.iloc[-1]
    if price == 0:
        return 50.0
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    av = tr.rolling(10).mean().iloc[-1]
    return round(min(100.0, (av / price) * 100 / 0.008 * 100), 1)


# ── Patrones de velas — núcleo de la estrategia ────────────
def _patterns(df: pd.DataFrame) -> tuple[Direction | None, int, list[str]]:
    """
    Detecta patrones PA. Devuelve (dirección, score_aporte, nombres).
    Prioridad: 3-velas (morning/evening star) > 2-velas (engulfing) > 1-vela (hammer/pin/marubozu).
    """
    if len(df) < 4:
        return None, 0, []

    c  = df.iloc[-1]   # vela actual
    p  = df.iloc[-2]   # vela previa
    p2 = df.iloc[-3]   # vela hace 2

    o, h, l, cl = float(c.open), float(c.high), float(c.low), float(c.close)
    po, ph, pl, pc = float(p.open), float(p.high), float(p.low), float(p.close)
    po2, ph2, pl2, pc2 = float(p2.open), float(p2.high), float(p2.low), float(p2.close)

    total = h - l or 1e-10
    body  = abs(cl - o)
    uw    = h - max(o, cl)   # mecha superior
    lw    = min(o, cl) - l   # mecha inferior
    body_ratio = body / total

    bull = cl > o   # vela actual alcista
    p_bull = pc > po
    p2_bull = pc2 > po2

    pats: list[str] = []
    direction: Direction | None = None
    score = 0

    # ── Morning Star (3 velas) — reversal bajista → alcista ──
    # Vela 3: gran bajista | Vela 2: pequeño cuerpo (estrella) | Vela 1: gran alcista
    p2_body = abs(pc2 - po2)
    p_body  = abs(pc - po)
    c_body  = body
    if (not p2_bull and p2_body > (ph2 - pl2) * 0.5 and    # gran vela bajista
            p_body < (ph - pl) * 0.3 and                   # estrella pequeña
            bull and c_body > (h - l) * 0.5 and            # gran vela alcista
            cl > (po2 + pc2) / 2):                         # cierra por encima del punto medio bajista
        direction = "CALL"; score = 42; pats.append("Morning Star")
        return direction, score, pats

    # ── Evening Star (3 velas) — reversal alcista → bajista ──
    if (p2_bull and p2_body > (ph2 - pl2) * 0.5 and
            p_body < (ph - pl) * 0.3 and
            not bull and c_body > (h - l) * 0.5 and
            cl < (po2 + pc2) / 2):
        direction = "PUT"; score = 42; pats.append("Evening Star")
        return direction, score, pats

    # ── Tres velas blancas / Tres cuervos negros ─────────────
    if (bull and p_bull and p2_bull and
            pc > pc2 and cl > pc and body_ratio > 0.5):
        direction = "CALL"; score = 35; pats.append("3 Soldados Blancos")
        return direction, score, pats

    if (not bull and not p_bull and not p2_bull and
            pc < pc2 and cl < pc and body_ratio > 0.5):
        direction = "PUT"; score = 35; pats.append("3 Cuervos Negros")
        return direction, score, pats

    # ── Engulfing alcista ────────────────────────────────────
    if (not p_bull and bull and o <= pc and cl >= po and
            body > abs(pc - po) * 0.9):
        direction = "CALL"; score = 38; pats.append("Engulfing Alcista")
        return direction, score, pats

    # ── Engulfing bajista ────────────────────────────────────
    if (p_bull and not bull and o >= pc and cl <= po and
            body > abs(pc - po) * 0.9):
        direction = "PUT"; score = 38; pats.append("Engulfing Bajista")
        return direction, score, pats

    # ── Hammer (mecha larga abajo, cuerpo pequeño arriba) ────
    if bull and lw > 2.2 * body and uw < body * 0.5 and body_ratio < 0.40:
        direction = "CALL"; score = 30; pats.append("Hammer")
        return direction, score, pats

    # ── Shooting Star (mecha larga arriba) ───────────────────
    if not bull and uw > 2.2 * body and lw < body * 0.5 and body_ratio < 0.40:
        direction = "PUT"; score = 30; pats.append("Shooting Star")
        return direction, score, pats

    # ── Pin Bar — cuerpo pequeño, mecha larga ────────────────
    if body_ratio < 0.30:
        if lw > 2.5 * uw and lw > total * 0.55:
            direction = "CALL"; score = 28; pats.append("Pin Bar Alcista")
            return direction, score, pats
        if uw > 2.5 * lw and uw > total * 0.55:
            direction = "PUT"; score = 28; pats.append("Pin Bar Bajista")
            return direction, score, pats

    # ── Marubozu — vela de fuerza pura (sin mechas) ──────────
    if body_ratio > 0.82 and total > 0:
        if bull:
            direction = "CALL"; score = 25; pats.append("Marubozu Alcista")
        else:
            direction = "PUT"; score = 25; pats.append("Marubozu Bajista")
        return direction, score, pats

    # ── Doji de reversal (cuerpo muy pequeño + mecha notable) ─
    if body_ratio < 0.10 and total > 0:
        # Doji después de tendencia bajista → posible reversal al alza
        prior_trend = cl < df["close"].iloc[-6] if len(df) >= 6 else False
        if prior_trend:
            direction = "CALL"; score = 20; pats.append("Doji Reversal Alcista")
        else:
            direction = "PUT"; score = 20; pats.append("Doji Reversal Bajista")
        return direction, score, pats

    return None, 0, []


def _is_inside_bar(df: pd.DataFrame) -> bool:
    """Vela actual completamente dentro de la previa = indecisión, NO operar."""
    if len(df) < 2:
        return False
    c, p = df.iloc[-1], df.iloc[-2]
    return float(c.high) <= float(p.high) and float(c.low) >= float(p.low)


def _noise_filter(df: pd.DataFrame, min_body_atr_ratio: float = 0.20) -> bool:
    """True = hay ruido, descartar. Fast path antes del análisis completo."""
    if len(df) < 15:
        return True
    c = df.iloc[-1]
    body = abs(float(c.close) - float(c.open))
    # Cuerpo mínimo relativo a ATR(5): evita microruido de 1-2 pips
    av = atr(df["high"], df["low"], df["close"], 5).iloc[-1]
    if av > 0 and body < av * min_body_atr_ratio:
        return True
    # Inside bar = indecisión, no operar
    if _is_inside_bar(df):
        return True
    # Mercado completamente plano (últimas 8 velas con rango mínimo)
    span = df["close"].tail(8)
    if (span.max() - span.min()) / (span.mean() or 1) < 0.0002:
        return True
    return False


def _sr_proximity(price: float, high_s: pd.Series, low_s: pd.Series,
                  pct: float = 0.0015) -> tuple[str | None, float]:
    """Devuelve ('support'/'resistance'/None, distancia%). Umbral 0.15% del precio."""
    sup = float(low_s.tail(20).min())
    res = float(high_s.tail(20).max())
    d_sup = (price - sup) / (price or 1)
    d_res = (res - price) / (price or 1)
    if d_sup < pct:
        return "support", d_sup
    if d_res < pct:
        return "resistance", d_res
    return None, 1.0


def _pullback_to_ema(close: pd.Series, ema_s: pd.Series,
                     direction: Direction, pct: float = 0.003) -> bool:
    """
    True si en las últimas 4 velas el precio tocó la EMA y está rebotando.
    direction CALL = tendencia alcista, precio bajo hacia EMA y rebota arriba.
    direction PUT  = tendencia bajista, precio subió hacia EMA y rechaza abajo.
    """
    if len(close) < 5 or len(ema_s) < 5:
        return False
    for i in range(1, 5):
        price_i  = float(close.iloc[-i])
        ema_i    = float(ema_s.iloc[-i])
        distance = abs(price_i - ema_i) / (ema_i or 1)
        if distance < pct:
            # Verificar que la vela actual rebota en la dirección correcta
            current = float(close.iloc[-1])
            if direction == "CALL" and current > price_i:
                return True
            if direction == "PUT" and current < price_i:
                return True
    return False


# ── M1: Reversión en extremos con PA ───────────────────────
def _analyze_m1(df: pd.DataFrame) -> TFResult:
    """
    M1 = señales de reversión rápida para expiración 1 min.
    Requiere patrón de vela + confirmación de BB o Stoch en extremo.
    """
    res = TFResult(tf=60, direction=None, score=0)
    if len(df) < 25:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = float(chop_index(high, low, close).iloc[-1])
    res.volatility = _vol_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    # Filtro de ruido rápido (cuerpo mínimo 15% ATR en M1 — más permisivo)
    if _noise_filter(df, min_body_atr_ratio=0.15):
        res.reasons = ["Ruido M1: cuerpo insignificante / inside bar"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # ── Patrón de vela ─── requerido para señal M1 ──────────
    pat_dir, pat_score, pat_names = _patterns(df)
    has_pattern = pat_dir is not None and pat_score > 0
    if has_pattern:
        score += pat_score
        if pat_dir == "CALL":
            calls += 2
        else:
            puts += 2
        reasons.append(f"Patron: {', '.join(pat_names)}")

    # ── Bollinger Bands — nivel extremo ─────────────────────
    bb  = bollinger(close, 10, 2.0)
    pb  = float(bb["pct_b"].iloc[-1])
    bw  = float(bb["bw"].iloc[-1])
    if bw > 0.002:   # banda con amplitud suficiente
        if pb <= 0.03:
            calls += 1; score += 22; reasons.append(f"BB banda baja %B={pb:.2f}")
        elif pb >= 0.97:
            puts  += 1; score += 22; reasons.append(f"BB banda alta %B={pb:.2f}")
        elif pb <= 0.12:
            calls += 1; score += 12; reasons.append(f"BB zona baja %B={pb:.2f}")
        elif pb >= 0.88:
            puts  += 1; score += 12; reasons.append(f"BB zona alta %B={pb:.2f}")

    # ── Stochastic(5,3) — señal de giro en extremo ──────────
    st   = stoch(high, low, close, 5, 3)
    k    = float(st["k"].iloc[-1])
    k_p  = float(st["k"].iloc[-2])
    if k <= 20:
        if k > k_p:   # girando al alza
            calls += 1; score += 20; reasons.append(f"Stoch giro alcista K={k:.0f}")
        else:
            calls += 1; score += 10; reasons.append(f"Stoch sobreventa K={k:.0f}")
    elif k >= 80:
        if k < k_p:   # girando a la baja
            puts  += 1; score += 20; reasons.append(f"Stoch giro bajista K={k:.0f}")
        else:
            puts  += 1; score += 10; reasons.append(f"Stoch sobrecompra K={k:.0f}")

    # ── RSI(7) rápido — solo extremos fuertes ───────────────
    r = float(rsi(close, 7).iloc[-1])
    if r <= 22:
        calls += 1; score += 18; reasons.append(f"RSI(7) sobreventa extrema {r:.0f}")
    elif r >= 78:
        puts  += 1; score += 18; reasons.append(f"RSI(7) sobrecompra extrema {r:.0f}")
    elif r <= 32:
        calls += 1; score += 8;  reasons.append(f"RSI(7) bajo {r:.0f}")
    elif r >= 68:
        puts  += 1; score += 8;  reasons.append(f"RSI(7) alto {r:.0f}")

    # ── EMA micro-tendencia 5/13 ─────────────────────────────
    e5  = float(ema(close, 5).iloc[-1])
    e13 = float(ema(close, 13).iloc[-1])
    price = float(close.iloc[-1])
    if e5 > e13:
        calls += 1; score += 8; reasons.append("EMA5>EMA13 alcista M1")
    elif e5 < e13:
        puts  += 1; score += 8; reasons.append("EMA5<EMA13 bajista M1")

    # ── S/R en M1 ───────────────────────────────────────────
    sr_loc, sr_dist = _sr_proximity(price, high, low, pct=0.0015)
    if sr_loc == "support":
        calls += 1; score += 10; reasons.append(f"Cerca soporte M1 ({sr_dist*100:.2f}%)")
    elif sr_loc == "resistance":
        puts  += 1; score += 10; reasons.append(f"Cerca resistencia M1 ({sr_dist*100:.2f}%)")

    # ── Decisión ─────────────────────────────────────────────
    # En M1 REQUERIMOS patrón de vela para emitir señal
    if not has_pattern:
        res.reasons = reasons or ["Sin patron de vela M1"]
        return res

    if calls > puts:
        res.direction = "CALL" if pat_dir == "CALL" or calls - puts > 1 else None
    elif puts > calls:
        res.direction = "PUT" if pat_dir == "PUT" or puts - calls > 1 else None
    else:
        # Empate: el patrón desempata
        res.direction = pat_dir

    res.score   = min(score, 100)
    res.reasons = reasons
    return res


# ── M5: Pullback a EMA21 con PA ────────────────────────────
def _analyze_m5(df: pd.DataFrame) -> TFResult:
    """
    M5 = pullback a EMA21 + patrón de vela en ese nivel.
    El setup de pullback es la base; el patrón es la entrada.
    """
    res = TFResult(tf=300, direction=None, score=0)
    if len(df) < 35:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = float(chop_index(high, low, close).iloc[-1])
    res.volatility = _vol_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    if _noise_filter(df, min_body_atr_ratio=0.18):
        res.reasons = ["Ruido M5: cuerpo/inside bar"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # ── EMA 8 / 21 — dirección de tendencia ─────────────────
    e8_s  = ema(close, 8)
    e21_s = ema(close, 21)
    e8    = float(e8_s.iloc[-1])
    e21   = float(e21_s.iloc[-1])
    price = float(close.iloc[-1])

    trend_up   = e8 > e21 * 1.0003   # margen 0.03% para evitar ruido de EMA
    trend_down = e8 < e21 * 0.9997

    if trend_up:
        calls += 1; score += 15; reasons.append("EMA8>EMA21 tendencia alcista M5")
    elif trend_down:
        puts  += 1; score += 15; reasons.append("EMA8<EMA21 tendencia bajista M5")

    # ── Pullback a EMA21 — el setup clave ───────────────────
    if trend_up:
        pb_call = _pullback_to_ema(close, e21_s, "CALL", pct=0.004)
        if pb_call:
            calls += 2; score += 28; reasons.append("Pullback EMA21 + rebote alcista M5")
    if trend_down:
        pb_put = _pullback_to_ema(close, e21_s, "PUT", pct=0.004)
        if pb_put:
            puts  += 2; score += 28; reasons.append("Pullback EMA21 + rechazo bajista M5")

    # ── Patrón de vela ──────────────────────────────────────
    pat_dir, pat_score, pat_names = _patterns(df)
    has_pattern = pat_dir is not None and pat_score > 0
    if has_pattern:
        score += pat_score
        if pat_dir == "CALL": calls += 2
        else:                  puts  += 2
        reasons.append(f"Patron: {', '.join(pat_names)}")

    # ── MACD(8,17,9) — confirmación ─────────────────────────
    m    = macd(close, 8, 17, 9)
    hist = m["hist"]
    line = m["line"]
    if len(hist) >= 3:
        min_mag = abs(price) * 0.00008   # filtro: ignorar señales < 0.008% del precio
        if abs(float(hist.iloc[-1])) > min_mag:
            if float(hist.iloc[-2]) <= 0 < float(hist.iloc[-1]):
                calls += 1; score += 25; reasons.append("MACD cruce alcista M5")
            elif float(hist.iloc[-2]) >= 0 > float(hist.iloc[-1]):
                puts  += 1; score += 25; reasons.append("MACD cruce bajista M5")
            elif float(hist.iloc[-1]) > 0 and float(hist.iloc[-1]) > float(hist.iloc[-2]):
                calls += 1; score += 14; reasons.append("MACD momentum alcista M5")
            elif float(hist.iloc[-1]) < 0 and float(hist.iloc[-1]) < float(hist.iloc[-2]):
                puts  += 1; score += 14; reasons.append("MACD momentum bajista M5")

    # ── RSI(14) — no contra-tendencia ───────────────────────
    r = float(rsi(close, 14).iloc[-1])
    if calls > puts and r < 45:
        score += 10; reasons.append(f"RSI confirma alcista {r:.0f}")
    elif puts > calls and r > 55:
        score += 10; reasons.append(f"RSI confirma bajista {r:.0f}")
    # Señal contraria si RSI extremo opuesto
    if calls > puts and r > 75:
        score -= 15; reasons.append(f"RSI sobrecompra — penalizacion {r:.0f}")
    elif puts > calls and r < 25:
        score -= 15; reasons.append(f"RSI sobreventa — penalizacion {r:.0f}")

    # ── S/R en M5 ───────────────────────────────────────────
    sr_loc, sr_dist = _sr_proximity(price, high, low, pct=0.002)
    if sr_loc == "support":
        calls += 1; score += 12; reasons.append(f"Soporte M5 ({sr_dist*100:.2f}%)")
    elif sr_loc == "resistance":
        puts  += 1; score += 12; reasons.append(f"Resistencia M5 ({sr_dist*100:.2f}%)")

    # ── Decisión ─────────────────────────────────────────────
    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score   = max(0, min(score, 100))
    res.reasons = reasons
    return res


# ── M15: Tendencia con PA en S/R ───────────────────────────
def _analyze_m15(df: pd.DataFrame) -> TFResult:
    """
    M15 = tendencia clara (EMA triple + ADX) + patrón vela en S/R.
    No operar en mercado lateral — ADX < 18 descarta directamente.
    """
    res = TFResult(tf=900, direction=None, score=0)
    if len(df) < 40:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = float(chop_index(high, low, close).iloc[-1])
    res.volatility = _vol_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    if _noise_filter(df, min_body_atr_ratio=0.22):
        res.reasons = ["Ruido M15: cuerpo/inside bar"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # ── ADX — filtro de tendencia fuerte (REQUERIDO en M15) ─
    adx_d = adx(high, low, close, 14)
    adx_v = float(adx_d["adx"].iloc[-1])
    dip   = float(adx_d["dip"].iloc[-1])
    dim   = float(adx_d["dim"].iloc[-1])

    if adx_v < 18:
        res.reasons = [f"ADX={adx_v:.0f} demasiado bajo — sin tendencia M15"]
        return res

    trending_up   = dip > dim
    trending_down = dim > dip
    adx_bonus = 30 if adx_v >= 30 else 20 if adx_v >= 22 else 12
    score += adx_bonus
    if trending_up:
        calls += 1; reasons.append(f"ADX={adx_v:.0f} DI+ domina")
    else:
        puts  += 1; reasons.append(f"ADX={adx_v:.0f} DI- domina")

    # ── EMA triple 8/21/55 — alineación ─────────────────────
    e8_s  = ema(close, 8)
    e21_s = ema(close, 21)
    e55_s = ema(close, 55)
    e8    = float(e8_s.iloc[-1])
    e21   = float(e21_s.iloc[-1])
    e55   = float(e55_s.iloc[-1])
    price = float(close.iloc[-1])

    if e8 > e21 > e55:
        calls += 1
        if price > e8:
            score += 35; reasons.append("EMA 8>21>55 + precio arriba — alcista perfecto M15")
        else:
            score += 20; reasons.append("EMA 8>21>55 alcista M15")
    elif e8 < e21 < e55:
        puts += 1
        if price < e8:
            score += 35; reasons.append("EMA 8<21<55 + precio abajo — bajista perfecto M15")
        else:
            score += 20; reasons.append("EMA 8<21<55 bajista M15")
    elif e8 > e21:
        calls += 1; score += 10; reasons.append("EMA8>EMA21 M15")
    elif e8 < e21:
        puts  += 1; score += 10; reasons.append("EMA8<EMA21 M15")

    # ── Pullback a EMA21 en M15 ──────────────────────────────
    if calls >= puts:
        if _pullback_to_ema(close, e21_s, "CALL", pct=0.005):
            calls += 1; score += 20; reasons.append("Pullback EMA21 M15 alcista")
    else:
        if _pullback_to_ema(close, e21_s, "PUT", pct=0.005):
            puts  += 1; score += 20; reasons.append("Pullback EMA21 M15 bajista")

    # ── Patrón de vela ──────────────────────────────────────
    pat_dir, pat_score, pat_names = _patterns(df)
    if pat_dir is not None and pat_score > 0:
        score += pat_score
        if pat_dir == "CALL": calls += 2
        else:                  puts  += 2
        reasons.append(f"Patron: {', '.join(pat_names)}")

    # ── MACD(12,26,9) — dirección macro ─────────────────────
    m    = macd(close, 12, 26, 9)
    hist = m["hist"]
    min_mag = abs(price) * 0.00010
    if len(hist) >= 2 and abs(float(hist.iloc[-1])) > min_mag:
        if float(hist.iloc[-1]) > 0:
            calls += 1
            if float(hist.iloc[-1]) >= float(hist.iloc[-2]):
                score += 15; reasons.append("MACD M15 positivo y creciendo")
            else:
                score += 8;  reasons.append("MACD M15 positivo")
        elif float(hist.iloc[-1]) < 0:
            puts += 1
            if float(hist.iloc[-1]) <= float(hist.iloc[-2]):
                score += 15; reasons.append("MACD M15 negativo y cayendo")
            else:
                score += 8;  reasons.append("MACD M15 negativo")

    # ── RSI(14) — solo extremos en M15 ──────────────────────
    r = float(rsi(close, 14).iloc[-1])
    if r < 30:
        calls += 1; score += 15; reasons.append(f"RSI M15 sobreventa {r:.0f}")
    elif r > 70:
        puts  += 1; score += 15; reasons.append(f"RSI M15 sobrecompra {r:.0f}")
    elif r < 42:
        calls += 1; score += 8;  reasons.append(f"RSI M15 bajo {r:.0f}")
    elif r > 58:
        puts  += 1; score += 8;  reasons.append(f"RSI M15 alto {r:.0f}")

    # ── S/R en M15 ───────────────────────────────────────────
    sr_loc, sr_dist = _sr_proximity(price, high, low, pct=0.002)
    if sr_loc == "support":
        calls += 1; score += 15; reasons.append(f"Soporte M15 ({sr_dist*100:.2f}%)")
    elif sr_loc == "resistance":
        puts  += 1; score += 15; reasons.append(f"Resistencia M15 ({sr_dist*100:.2f}%)")

    # ── Decisión ─────────────────────────────────────────────
    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score   = max(0, min(score, 100))
    res.reasons = reasons
    return res


# ── Dispatcher y kelly ─────────────────────────────────────
def _analyze_tf(df: pd.DataFrame, tf: int) -> TFResult:
    if tf == 60:  return _analyze_m1(df)
    if tf == 300: return _analyze_m5(df)
    if tf == 900: return _analyze_m15(df)
    return TFResult(tf=tf, direction=None, score=0)


def kelly_criterion(win_rate: float, payout: float) -> float:
    if win_rate <= 0 or payout <= 0:
        return 0.0
    q = 1.0 - win_rate
    kelly = (win_rate * payout - q) / payout
    return max(0.0, min(kelly * 0.5, 0.15))


# ── Análisis principal ─────────────────────────────────────
def analyze(
    candles_by_tf: dict[int, list],
    symbol: str,
    broker: str,
    payout: float,
    market_type: str = "REAL",
    category: str   = "Forex",
    win_rate_hist: float = 0.0,
) -> Signal | None:

    if payout < MIN_PAYOUT:
        return None

    tf_results: list[TFResult] = []
    for tf in TIMEFRAMES:
        df = _to_df(candles_by_tf.get(tf, []))
        tf_results.append(_analyze_tf(df, tf))

    dirs   = [r.direction for r in tf_results if r.direction is not None]
    calls  = dirs.count("CALL")
    puts   = dirs.count("PUT")
    max_dir = max(calls, puts)

    best_score = max((r.score for r in tf_results), default=0)
    need = 1 if best_score >= 65 else MIN_TF_AGREE

    if max_dir < need:
        return None

    direction: Direction = "CALL" if calls >= puts else "PUT"

    matching = [r for r in tf_results if r.direction == direction]
    if not matching:
        return None

    w_sum = sum(WEIGHTS[r.tf] for r in matching)
    composite = int(min(
        sum(r.score * WEIGHTS[r.tf] for r in matching) / w_sum, 100
    ))

    if composite < MIN_COMPOSITE:
        return None

    avg_vol = sum(r.volatility for r in tf_results) / len(tf_results)

    all_reasons: list[str] = []
    for r in matching:
        for reason in r.reasons:
            tag = f"[{TF_NAMES[r.tf]}] {reason}"
            if tag not in all_reasons:
                all_reasons.append(tag)

    exp_tf = min(r.tf for r in matching)
    kelly  = kelly_criterion(win_rate_hist, payout)

    return Signal(
        symbol=symbol, broker=broker, direction=direction,
        score=composite, payout=payout,
        expiration=EXPIRATION[exp_tf],
        market_type=market_type, category=category,
        reasons=all_reasons, tf_results=tf_results,
        win_rate_hist=win_rate_hist, kelly_pct=kelly,
        volatility=avg_vol,
    )
