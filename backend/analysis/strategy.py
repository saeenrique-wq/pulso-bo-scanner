"""Estrategias optimizadas por timeframe para opciones binarias.

M1  — Reversión rápida: RSI extremo + BB toque + patrón vela + Stoch
M5  — Momentum: MACD cross + EMA alineación + ADX + RSI
M15 — Tendencia: EMA triple + ADX fuerte + MACD + soporte/resistencia

Volatility score (0-100):
  < 20 = mercado dormido — señal arriesgada para M1
  20-70 = condición ideal para operar
  > 70 = alta volatilidad — arriesgado para M5/M15
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from .indicators import (adx, atr, bollinger, candle_patterns, chop_index,
                          ema, macd, rsi, sr_levels, stoch, trend_streak)

Direction = Literal["CALL", "PUT"]

# ── Umbrales globales ──────────────────────────────────────
MIN_COMPOSITE = 25   # score compuesto mínimo — Ollama filtra el resto
MIN_TF_AGREE  = 2    # mayoría de TF (2 de 3) deben coincidir
MAX_CHOP      = 65.0 # rechazar mercado lateral muy pronunciado
MIN_PAYOUT    = 0.80

TIMEFRAMES = [60, 300, 900]
TF_NAMES   = {60: "M1", 300: "M5", 900: "M15"}
EXPIRATION = {60: 1,  300: 5,  900: 15}
WEIGHTS    = {60: 0.25, 300: 0.35, 900: 0.40}


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
    market_type: str  = "REAL"
    category: str     = "Forex"
    timestamp: float  = field(default_factory=time.time)
    reasons: list[str]        = field(default_factory=list)
    tf_results: list[TFResult]= field(default_factory=list)
    win_rate_hist: float = 0.0
    ai_score: float  = 0.0
    kelly_pct: float = 0.0
    volatility: float= 50.0   # 0-100

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
        columns=["time","open","high","low","close","volume"],
    ).sort_values("time").reset_index(drop=True)
    # Quitar velas planas del final (yfinance a veces repite el último precio)
    while len(df) > 40 and df["close"].iloc[-1] == df["close"].iloc[-2]:
        df = df.iloc[:-1]
    return df


def _volatility_score(close: pd.Series, high: pd.Series, low: pd.Series) -> float:
    """0=dormido, 50=ideal, 100=muy volátil. Basado en ATR% del precio."""
    if len(close) < 14:
        return 50.0
    price = close.iloc[-1]
    if price == 0:
        return 50.0
    pc  = close.shift(1)
    tr  = pd.concat([high-low, (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    atr_val = tr.rolling(14).mean().iloc[-1]
    atr_pct = (atr_val / price) * 100
    # Mapear a 0-100: 0%=0, 0.05%=25, 0.15%=50, 0.4%=75, ≥0.8%=100
    score = min(100.0, atr_pct / 0.8 * 100)
    return round(score, 1)


# ── M1: Estrategia de reversión rápida ────────────────────
def _analyze_m1(df: pd.DataFrame) -> TFResult:
    """
    Para 1 minuto: señales de reversión en zonas extremas.
    RSI < 25 / > 75, BB toque, patrón vela, Stoch cross en extremos.
    """
    res = TFResult(tf=60, direction=None, score=0)
    if len(df) < 30:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = chop_index(high, low, close).iloc[-1]
    res.volatility = _volatility_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # RSI — zona extrema pesa más en M1
    r = rsi(close, 7).iloc[-1]   # RSI rápido para M1
    if r <= 20:
        calls += 1; score += 30; reasons.append(f"RSI M1 sobreventa {r:.0f}")
    elif r >= 80:
        puts  += 1; score += 30; reasons.append(f"RSI M1 sobrecompra {r:.0f}")
    elif r <= 30:
        calls += 1; score += 18; reasons.append(f"RSI M1 bajo {r:.0f}")
    elif r >= 70:
        puts  += 1; score += 18; reasons.append(f"RSI M1 alto {r:.0f}")
    elif r <= 40:
        calls += 1; score += 8;  reasons.append(f"RSI M1 neutral-bajo {r:.0f}")
    elif r >= 60:
        puts  += 1; score += 8;  reasons.append(f"RSI M1 neutral-alto {r:.0f}")

    # BB toque — clave en M1 para reversión
    bb = bollinger(close, 10)   # BB rápido
    pb = bb["pct_b"].iloc[-1]
    bw = bb["bw"].iloc[-1]
    if bw > 0.003:
        if pb <= 0.02:
            calls += 1; score += 28; reasons.append(f"BB M1 toque banda baja %B={pb:.2f}")
        elif pb >= 0.98:
            puts  += 1; score += 28; reasons.append(f"BB M1 toque banda alta %B={pb:.2f}")
        elif pb <= 0.10:
            calls += 1; score += 14; reasons.append(f"BB M1 zona baja %B={pb:.2f}")
        elif pb >= 0.90:
            puts  += 1; score += 14; reasons.append(f"BB M1 zona alta %B={pb:.2f}")

    # Stochastic — crossover en zona extrema
    st = stoch(high, low, close, 5, 3)
    k, d_ = st["k"].iloc[-1], st["d"].iloc[-1]
    k_prev = st["k"].iloc[-2]
    if k <= 20:
        if k > k_prev:
            calls += 1; score += 22; reasons.append(f"Stoch M1 rebote sobreventa K={k:.0f}")
        else:
            calls += 1; score += 12; reasons.append(f"Stoch M1 sobreventa K={k:.0f}")
    elif k >= 80:
        if k < k_prev:
            puts  += 1; score += 22; reasons.append(f"Stoch M1 caída sobrecompra K={k:.0f}")
        else:
            puts  += 1; score += 12; reasons.append(f"Stoch M1 sobrecompra K={k:.0f}")

    # Patrón de vela — muy relevante en M1
    pats = candle_patterns(df)
    if pats.get("pin_bull") or pats.get("hammer"):
        calls += 1; score += 20; reasons.append("Vela: Pin Bull/Hammer M1")
    elif pats.get("pin_bear") or pats.get("shooting_star"):
        puts  += 1; score += 20; reasons.append("Vela: Pin Bear/Shooting Star M1")
    elif pats.get("bull_engulf"):
        calls += 1; score += 15; reasons.append("Vela: Engulfing alcista M1")
    elif pats.get("bear_engulf"):
        puts  += 1; score += 15; reasons.append("Vela: Engulfing bajista M1")

    # EMA rápida 5/13
    e5  = ema(close, 5).iloc[-1]
    e13 = ema(close, 13).iloc[-1]
    price = close.iloc[-1]
    if e5 > e13 and price > e5:
        calls += 1; score += 10; reasons.append("EMA5>EMA13 alcista")
    elif e5 < e13 and price < e5:
        puts  += 1; score += 10; reasons.append("EMA5<EMA13 bajista")

    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score   = min(score, 100)
    res.reasons = reasons
    return res


# ── M5: Estrategia de momentum ────────────────────────────
def _analyze_m5(df: pd.DataFrame) -> TFResult:
    """
    Para 5 minutos: momentum confirmado con MACD + EMA + ADX.
    """
    res = TFResult(tf=300, direction=None, score=0)
    if len(df) < 35:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = chop_index(high, low, close).iloc[-1]
    res.volatility = _volatility_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # MACD — clave en M5
    m = macd(close, 8, 17, 9)
    hist = m["hist"]
    line = m["line"]
    if len(hist) >= 3:
        if hist.iloc[-2] <= 0 < hist.iloc[-1]:
            calls += 1; score += 30; reasons.append("MACD M5 cruce alcista")
        elif hist.iloc[-2] >= 0 > hist.iloc[-1]:
            puts  += 1; score += 30; reasons.append("MACD M5 cruce bajista")
        elif hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]:
            calls += 1; score += 18; reasons.append("MACD M5 momentum creciente")
        elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2] < hist.iloc[-3]:
            puts  += 1; score += 18; reasons.append("MACD M5 momentum decreciente")
        elif line.iloc[-1] > 0:
            calls += 1; score += 8;  reasons.append("MACD M5 línea positiva")
        elif line.iloc[-1] < 0:
            puts  += 1; score += 8;  reasons.append("MACD M5 línea negativa")

    # EMA 8/21 — alineación de tendencia
    e8  = ema(close, 8).iloc[-1]
    e21 = ema(close, 21).iloc[-1]
    price = close.iloc[-1]
    if e8 > e21 and price > e8:
        calls += 1; score += 22; reasons.append("EMA8>EMA21 M5 precio arriba")
    elif e8 < e21 and price < e8:
        puts  += 1; score += 22; reasons.append("EMA8<EMA21 M5 precio abajo")
    elif e8 > e21:
        calls += 1; score += 10; reasons.append("EMA8>EMA21 M5")
    elif e8 < e21:
        puts  += 1; score += 10; reasons.append("EMA8<EMA21 M5")

    # ADX — fuerza de tendencia
    adx_d = adx(high, low, close, 14)
    adx_v = adx_d["adx"].iloc[-1]
    dip, dim = adx_d["dip"].iloc[-1], adx_d["dim"].iloc[-1]
    if adx_v >= 20:
        bonus = 25 if adx_v >= 30 else 15
        score += bonus
        if dip > dim:
            calls += 1; reasons.append(f"ADX M5 tendencia alcista {adx_v:.0f}")
        else:
            puts  += 1; reasons.append(f"ADX M5 tendencia bajista {adx_v:.0f}")

    # RSI confirmación
    r = rsi(close, 14).iloc[-1]
    if r < 40:
        calls += 1; score += 12; reasons.append(f"RSI M5 bajo {r:.0f}")
    elif r > 60:
        puts  += 1; score += 12; reasons.append(f"RSI M5 alto {r:.0f}")

    # Stoch
    st = stoch(high, low, close, 14, 3)
    k = st["k"].iloc[-1]
    if k < 30 and k > st["k"].iloc[-2]:
        calls += 1; score += 11; reasons.append(f"Stoch M5 rebote {k:.0f}")
    elif k > 70 and k < st["k"].iloc[-2]:
        puts  += 1; score += 11; reasons.append(f"Stoch M5 caída {k:.0f}")

    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score   = min(score, 100)
    res.reasons = reasons
    return res


# ── M15: Estrategia de tendencia ──────────────────────────
def _analyze_m15(df: pd.DataFrame) -> TFResult:
    """
    Para 15 minutos: confirmar tendencia con EMA triple + ADX fuerte + S/R.
    """
    res = TFResult(tf=900, direction=None, score=0)
    if len(df) < 40:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    res.chop       = chop_index(high, low, close).iloc[-1]
    res.volatility = _volatility_score(close, high, low)

    if res.chop > MAX_CHOP:
        res.reasons = [f"Lateral CHOP={res.chop:.0f}"]
        return res

    score, calls, puts = 0, 0, 0
    reasons: list[str] = []

    # EMA triple 8/21/55 — alineación perfecta
    e8  = ema(close, 8).iloc[-1]
    e21 = ema(close, 21).iloc[-1]
    e55 = ema(close, 55).iloc[-1]
    price = close.iloc[-1]
    if e8 > e21 > e55 and price > e8:
        calls += 1; score += 35; reasons.append("EMA 8>21>55 M15 alineación alcista perfecta")
    elif e8 < e21 < e55 and price < e8:
        puts  += 1; score += 35; reasons.append("EMA 8<21<55 M15 alineación bajista perfecta")
    elif e8 > e21 > e55:
        calls += 1; score += 20; reasons.append("EMA M15 alcista 8>21>55")
    elif e8 < e21 < e55:
        puts  += 1; score += 20; reasons.append("EMA M15 bajista 8<21<55")
    elif e8 > e21:
        calls += 1; score += 10; reasons.append("EMA M15 8>21")
    elif e8 < e21:
        puts  += 1; score += 10; reasons.append("EMA M15 8<21")

    # ADX — filtro de tendencia fuerte
    adx_d = adx(high, low, close, 14)
    adx_v = adx_d["adx"].iloc[-1]
    dip, dim = adx_d["dip"].iloc[-1], adx_d["dim"].iloc[-1]
    if adx_v >= 25:
        bonus = 30 if adx_v >= 35 else 18
        score += bonus
        if dip > dim:
            calls += 1; reasons.append(f"ADX M15 {adx_v:.0f} DI+ domina")
        else:
            puts  += 1; reasons.append(f"ADX M15 {adx_v:.0f} DI- domina")
    elif adx_v >= 18:
        score += 8
        if dip > dim:
            calls += 1; reasons.append(f"ADX M15 tendencia media {adx_v:.0f}")
        else:
            puts  += 1; reasons.append(f"ADX M15 tendencia media {adx_v:.0f}")

    # MACD — dirección macro (filtro de magnitud: ignorar señales < 0.01% del precio)
    m = macd(close, 12, 26, 9)
    hist = m["hist"]
    min_macd = abs(price) * 0.0001   # 0.01% del precio como mínimo
    if len(hist) >= 2 and abs(hist.iloc[-1]) > min_macd:
        if hist.iloc[-1] > 0 and hist.iloc[-1] >= hist.iloc[-2]:
            calls += 1; score += 18; reasons.append("MACD M15 histograma positivo y creciendo")
        elif hist.iloc[-1] < 0 and hist.iloc[-1] <= hist.iloc[-2]:
            puts  += 1; score += 18; reasons.append("MACD M15 histograma negativo y cayendo")
        elif hist.iloc[-1] > 0:
            calls += 1; score += 8;  reasons.append("MACD M15 positivo")
        elif hist.iloc[-1] < 0:
            puts  += 1; score += 8;  reasons.append("MACD M15 negativo")

    # RSI M15 — solo zonas extremas (el RSI neutro no vota para no crear empates)
    r = rsi(close, 14).iloc[-1]
    if r < 30:
        calls += 1; score += 18; reasons.append(f"RSI M15 sobreventa {r:.0f}")
    elif r > 70:
        puts  += 1; score += 18; reasons.append(f"RSI M15 sobrecompra {r:.0f}")
    elif r < 40:
        calls += 1; score += 10; reasons.append(f"RSI M15 bajo {r:.0f}")
    elif r > 60:
        puts  += 1; score += 10; reasons.append(f"RSI M15 alto {r:.0f}")

    # Soporte / Resistencia
    sr = sr_levels(close)
    rng = (sr["resistance"] - sr["support"]) or 1e-10
    if (price - sr["support"]) / rng < 0.08:
        calls += 1; score += 10; reasons.append(f"S/R M15 cerca soporte")
    elif (sr["resistance"] - price) / rng < 0.08:
        puts  += 1; score += 10; reasons.append(f"S/R M15 cerca resistencia")

    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score   = min(score, 100)
    res.reasons = reasons
    return res


# ── Análisis por TF (dispatcher) ──────────────────────────
def _analyze_tf(df: pd.DataFrame, tf: int) -> TFResult:
    if tf == 60:   return _analyze_m1(df)
    if tf == 300:  return _analyze_m5(df)
    if tf == 900:  return _analyze_m15(df)
    return TFResult(tf=tf, direction=None, score=0)


# ── Kelly Criterion ────────────────────────────────────────
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

    # Mayoría de TF deben coincidir (o 1 solo si score muy alto >= 60)
    dirs = [r.direction for r in tf_results if r.direction is not None]
    calls = dirs.count("CALL")
    puts  = dirs.count("PUT")
    max_dir = max(calls, puts)

    best_score = max((r.score for r in tf_results), default=0)
    need = 1 if best_score >= 60 else MIN_TF_AGREE  # 1 TF basta si muy convincente

    if max_dir < need:
        return None

    direction: Direction = "CALL" if calls >= puts else "PUT"

    # Score compuesto ponderado de los TF que coinciden
    matching = [r for r in tf_results if r.direction == direction]
    composite = int(min(
        sum(r.score * WEIGHTS[r.tf] for r in matching) /
        sum(WEIGHTS[r.tf] for r in matching),
        100
    ))

    if composite < MIN_COMPOSITE:
        return None

    # Volatilidad promedio
    avg_vol = sum(r.volatility for r in tf_results) / len(tf_results)

    # Razones sin duplicar
    all_reasons: list[str] = []
    for r in matching:
        for reason in r.reasons:
            tag = f"[{TF_NAMES[r.tf]}] {reason}"
            if tag not in all_reasons:
                all_reasons.append(tag)

    # Expiración = TF más corto que coincide
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
