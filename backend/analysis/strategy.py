"""Estrategia de alta efectividad para opciones binarias.

Objetivo: >80% de señales ganadoras mediante:
  1. Chop Filter — NO operar en mercados laterales (CHOP > 61.8)
  2. Trend Streak — mínimo 3 velas consecutivas en dirección
  3. Confluencia 4/4 en indicadores clave
  4. Multi-TF: M1 + M5 + M15 deben TODOS coincidir
  5. Score mínimo 78/100

Sistema de puntuación (100 pts):
  RSI extremo           20 pts
  MACD crossover        20 pts
  Bollinger touch       15 pts
  EMA triple alineada   15 pts
  ADX > 25 + DI        10 pts
  Stoch extremo         10 pts
  Patrón de vela        10 pts
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from .indicators import (adx, atr, bollinger, candle_patterns, chop_index,
                          ema, macd, rsi, sr_levels, stoch, trend_streak)

Direction = Literal["CALL", "PUT"]

MIN_SCORE   = 78    # mínimo para emitir señal (>80% efectividad)
MIN_TF_AGREE = 3    # los 3 TF deben coincidir (M1+M5+M15)
MAX_CHOP    = 61.8  # rechazar si mercado es lateral
MIN_STREAK  = 2     # mínimo 2 velas consecutivas en dirección
MIN_PAYOUT  = 0.80

TIMEFRAMES = [60, 300, 900]
TF_NAMES   = {60: "M1", 300: "M5", 900: "M15"}
EXPIRATION = {60: 1, 300: 5, 900: 15}

# Pesos por TF — M15 tiene más peso porque filtra más ruido
WEIGHTS = {60: 0.25, 300: 0.35, 900: 0.40}


@dataclass
class TFResult:
    tf: int
    direction: Direction | None
    score: int
    reasons: list[str] = field(default_factory=list)
    chop: float = 50.0


@dataclass
class Signal:
    symbol: str
    broker: str
    direction: Direction
    score: int
    payout: float
    expiration: int
    market_type: str = "REAL"
    category: str = "forex"
    timestamp: float = field(default_factory=time.time)
    reasons: list[str] = field(default_factory=list)
    tf_results: list[TFResult] = field(default_factory=list)
    win_rate_hist: float = 0.0
    ai_score: float = 0.0       # Ollama AI confidence 0-1
    kelly_pct: float = 0.0      # Kelly criterion sizing %

    def to_dict(self) -> dict:
        return {
            "symbol":       self.symbol,
            "broker":       self.broker,
            "direction":    self.direction,
            "score":        self.score,
            "payout":       round(self.payout * 100, 1),
            "expiration":   self.expiration,
            "market_type":  self.market_type,
            "category":     self.category,
            "timestamp":    self.timestamp,
            "reasons":      self.reasons,
            "win_rate_hist": round(self.win_rate_hist * 100, 1),
            "ai_score":     round(self.ai_score * 100, 1),
            "kelly_pct":    round(self.kelly_pct * 100, 1),
            "tf_results": [
                {"tf": TF_NAMES[t.tf], "dir": t.direction,
                 "score": t.score, "chop": round(t.chop, 1),
                 "reasons": t.reasons}
                for t in self.tf_results
            ],
        }


def _to_df(candles) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(
        [(c.time, c.open, c.high, c.low, c.close, c.volume)
         for c in candles],
        columns=["time","open","high","low","close","volume"],
    ).sort_values("time").reset_index(drop=True)
    return df


def _analyze_tf(df: pd.DataFrame, tf: int) -> TFResult:
    res = TFResult(tf=tf, direction=None, score=0)
    if len(df) < 40:
        return res

    close, high, low = df["close"], df["high"], df["low"]
    score = 0
    calls = puts = 0
    reasons: list[str] = []

    # ── Chop filter ──────────────────────────────────────────
    chop = chop_index(high, low, close).iloc[-1]
    res.chop = chop
    if chop > MAX_CHOP:
        res.reasons = [f"CHOP lateral {chop:.1f} > {MAX_CHOP}"]
        return res   # no signal in choppy market

    # ── Trend Streak ─────────────────────────────────────────
    streak = trend_streak(close)
    if abs(streak) < MIN_STREAK:
        res.reasons = [f"Sin tendencia (streak={streak})"]
        return res

    # ── RSI (20 pts) ─────────────────────────────────────────
    r = rsi(close).iloc[-1]
    if r < 25:
        calls += 1; score += 20; reasons.append(f"RSI sobreventa {r:.1f}")
    elif r > 75:
        puts  += 1; score += 20; reasons.append(f"RSI sobrecompra {r:.1f}")
    elif r < 38:
        calls += 1; score += 10; reasons.append(f"RSI bajo {r:.1f}")
    elif r > 62:
        puts  += 1; score += 10; reasons.append(f"RSI alto {r:.1f}")

    # ── MACD cross (20 pts) ──────────────────────────────────
    m = macd(close)
    h = m["hist"]
    if len(h) >= 2:
        if h.iloc[-2] < 0 < h.iloc[-1]:
            calls += 1; score += 20; reasons.append("MACD cruce alcista")
        elif h.iloc[-2] > 0 > h.iloc[-1]:
            puts  += 1; score += 20; reasons.append("MACD cruce bajista")
        elif h.iloc[-1] > 0 and h.iloc[-1] > h.iloc[-2]:
            calls += 1; score += 10; reasons.append("MACD momentum alcista")
        elif h.iloc[-1] < 0 and h.iloc[-1] < h.iloc[-2]:
            puts  += 1; score += 10; reasons.append("MACD momentum bajista")

    # ── Bollinger Bands (15 pts) ─────────────────────────────
    bb = bollinger(close)
    pb = bb["pct_b"].iloc[-1]
    bw = bb["bw"].iloc[-1]
    if bw > 0.008:   # evitar señales en squeeze
        if pb < 0.04:
            calls += 1; score += 15; reasons.append(f"BB toque inferior %B={pb:.2f}")
        elif pb > 0.96:
            puts  += 1; score += 15; reasons.append(f"BB toque superior %B={pb:.2f}")
        elif pb < 0.18:
            calls += 1; score += 7;  reasons.append(f"BB zona baja %B={pb:.2f}")
        elif pb > 0.82:
            puts  += 1; score += 7;  reasons.append(f"BB zona alta %B={pb:.2f}")

    # ── EMA triple 8/21/55 (15 pts) ─────────────────────────
    e8, e21, e55 = ema(close,8).iloc[-1], ema(close,21).iloc[-1], ema(close,55).iloc[-1]
    price = close.iloc[-1]
    if e8 > e21 > e55 and price > e8:
        calls += 1; score += 15; reasons.append("EMA alcista 8>21>55")
    elif e8 < e21 < e55 and price < e8:
        puts  += 1; score += 15; reasons.append("EMA bajista 8<21<55")
    elif e8 > e21:
        calls += 1; score += 7; reasons.append("EMA8 > EMA21")
    elif e8 < e21:
        puts  += 1; score += 7; reasons.append("EMA8 < EMA21")

    # ── ADX + DI (10 pts) ────────────────────────────────────
    adx_d = adx(high, low, close)
    adx_v = adx_d["adx"].iloc[-1]
    dip, dim = adx_d["dip"].iloc[-1], adx_d["dim"].iloc[-1]
    if adx_v > 25:
        score += 10
        if dip > dim:
            calls += 1; reasons.append(f"ADX tendencia alcista {adx_v:.1f}")
        else:
            puts  += 1; reasons.append(f"ADX tendencia bajista {adx_v:.1f}")

    # ── Stochastic (10 pts) ──────────────────────────────────
    st = stoch(high, low, close)
    k, d_ = st["k"].iloc[-1], st["d"].iloc[-1]
    if k < 20 and k > d_:
        calls += 1; score += 10; reasons.append(f"Stoch sobreventa K={k:.1f}")
    elif k > 80 and k < d_:
        puts  += 1; score += 10; reasons.append(f"Stoch sobrecompra K={k:.1f}")

    # ── Patrón de vela (10 pts) ──────────────────────────────
    pats = candle_patterns(df)
    bull_pats = ["hammer","pin_bull","bull_engulf","3_white"]
    bear_pats = ["shooting_star","pin_bear","bear_engulf","3_black"]
    for p in bull_pats:
        if pats.get(p):
            calls += 1; score += 10; reasons.append(f"Patrón: {p}"); break
    for p in bear_pats:
        if pats.get(p):
            puts  += 1; score += 10; reasons.append(f"Patrón: {p}"); break

    # ── Soporte/Resistencia ──────────────────────────────────
    sr = sr_levels(close)
    rng = (sr["resistance"] - sr["support"]) or 1e-10
    if (price - sr["support"]) / rng < 0.05:
        calls += 1; score += 5; reasons.append(f"Cerca soporte {sr['support']:.5f}")
    elif (sr["resistance"] - price) / rng < 0.05:
        puts  += 1; score += 5; reasons.append(f"Cerca resistencia {sr['resistance']:.5f}")

    # ── Dirección final ──────────────────────────────────────
    if calls > puts:
        res.direction = "CALL"
    elif puts > calls:
        res.direction = "PUT"

    res.score = min(score, 100)
    res.reasons = reasons
    return res


def kelly_criterion(win_rate: float, payout: float) -> float:
    """Kelly fraction = (p*b - q) / b  donde b = payout, p = win_rate."""
    if win_rate <= 0 or payout <= 0:
        return 0.0
    q = 1.0 - win_rate
    b = payout
    kelly = (win_rate * b - q) / b
    return max(0.0, min(kelly * 0.5, 0.15))  # medio Kelly, tope 15%


def analyze(
    candles_by_tf: dict[int, list],
    symbol: str,
    broker: str,
    payout: float,
    market_type: str = "REAL",
    category: str = "forex",
    win_rate_hist: float = 0.0,
) -> Signal | None:

    if payout < MIN_PAYOUT:
        return None

    tf_results: list[TFResult] = []
    for tf in TIMEFRAMES:
        df = _to_df(candles_by_tf.get(tf, []))
        tf_results.append(_analyze_tf(df, tf))

    # Todos los TF deben coincidir
    dirs = [r.direction for r in tf_results if r.direction is not None]
    if len(dirs) < MIN_TF_AGREE:
        return None
    calls = dirs.count("CALL")
    puts  = dirs.count("PUT")
    if calls < MIN_TF_AGREE and puts < MIN_TF_AGREE:
        return None

    direction: Direction = "CALL" if calls >= puts else "PUT"

    # Score ponderado solo de TFs que coinciden
    composite = int(min(
        sum(r.score * WEIGHTS[r.tf] for r in tf_results if r.direction == direction),
        100
    ))

    if composite < MIN_SCORE:
        return None

    # Razones agregadas sin duplicar
    all_reasons: list[str] = []
    for r in tf_results:
        if r.direction == direction:
            for reason in r.reasons:
                tag = f"[{TF_NAMES[r.tf]}] {reason}"
                if tag not in all_reasons:
                    all_reasons.append(tag)

    exp_tf = min(r.tf for r in tf_results if r.direction == direction)
    kelly  = kelly_criterion(win_rate_hist, payout)

    return Signal(
        symbol=symbol, broker=broker, direction=direction,
        score=composite, payout=payout,
        expiration=EXPIRATION[exp_tf],
        market_type=market_type, category=category,
        reasons=all_reasons, tf_results=tf_results,
        win_rate_hist=win_rate_hist, kelly_pct=kelly,
    )
