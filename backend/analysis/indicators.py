"""Indicadores técnicos para análisis de opciones binarias."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + g/l.replace(0, np.nan))).fillna(50)

def macd(s: pd.Series, f=12, sl=26, sig=9):
    line = ema(s,f) - ema(s,sl)
    signal = ema(line, sig)
    return {"line": line, "signal": signal, "hist": line - signal}

def bollinger(s: pd.Series, n=20, std=2.0):
    mid = s.rolling(n).mean()
    sd  = s.rolling(n).std()
    upper, lower = mid + std*sd, mid - std*sd
    pct = (s - lower) / (upper - lower).replace(0, np.nan)
    bw  = (upper - lower) / mid.replace(0, np.nan)
    return {"upper":upper,"middle":mid,"lower":lower,
            "pct_b":pct.fillna(0.5),"bw":bw.fillna(0)}

def stoch(high, low, close, k=14, d=3):
    lo = low.rolling(k).min()
    hi = high.rolling(k).max()
    K = 100*(close-lo)/(hi-lo).replace(0,np.nan)
    return {"k":K.fillna(50),"d":K.rolling(d).mean().fillna(50)}

def adx(high, low, close, n=14):
    ph,pl,pc = high.shift(1),low.shift(1),close.shift(1)
    tr = pd.concat([high-low,(high-pc).abs(),(low-pc).abs()],axis=1).max(axis=1)
    dmp = np.where((high-ph)>(pl-low), np.maximum(high-ph,0), 0.)
    dmm = np.where((pl-low)>(high-ph), np.maximum(pl-low,0), 0.)
    atr_s = pd.Series(tr).ewm(alpha=1/n,adjust=False).mean()
    dip = 100*pd.Series(dmp).ewm(alpha=1/n,adjust=False).mean()/atr_s.replace(0,np.nan)
    dim = 100*pd.Series(dmm).ewm(alpha=1/n,adjust=False).mean()/atr_s.replace(0,np.nan)
    dx  = (100*(dip-dim).abs()/(dip+dim).replace(0,np.nan)).fillna(0)
    return {"adx":dx.ewm(alpha=1/n,adjust=False).mean(),"dip":dip,"dim":dim}

def atr(high, low, close, n=14):
    pc = close.shift(1)
    tr = pd.concat([high-low,(high-pc).abs(),(low-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def chop_index(high, low, close, n=14):
    """Choppiness Index — >61.8 = rango lateral, <38.2 = tendencia fuerte."""
    tr_sum = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],
                       axis=1).max(axis=1).rolling(n).sum()
    hl_range = (high.rolling(n).max() - low.rolling(n).min()).replace(0, np.nan)
    return (100 * np.log10(tr_sum / hl_range) / np.log10(n)).fillna(50)

def trend_streak(close, n=10):
    """Velas consecutivas en la misma dirección contando desde la última hacia atrás."""
    dirs = np.sign(close.diff()).dropna()
    if len(dirs) == 0:
        return 0
    last_dir = dirs.iloc[-1]
    if last_dir == 0:
        return 0
    streak = 0
    for d in reversed(dirs.tolist()):
        if d == last_dir:
            streak += 1
        else:
            break
    return int(streak)

def candle_patterns(df: pd.DataFrame) -> dict:
    if len(df) < 3:
        return {}
    c, p = df.iloc[-1], df.iloc[-2]
    body   = abs(c.close - c.open)
    total  = (c.high - c.low) or 1e-10
    uw     = c.high - max(c.open, c.close)
    lw     = min(c.open, c.close) - c.low
    bull_c = c.close > c.open
    bull_p = p.close > p.open
    return {
        "doji":             body/total < 0.10,
        "hammer":           bull_c and lw > 2*body and uw < body,
        "shooting_star":    not bull_c and uw > 2*body and lw < body,
        "pin_bull":         lw > 2*body and body/total < 0.35,
        "pin_bear":         uw > 2*body and body/total < 0.35,
        "bull_engulf":      not bull_p and bull_c and c.open<p.close and c.close>p.open,
        "bear_engulf":      bull_p and not bull_c and c.open>p.close and c.close<p.open,
        "3_white":          all(df.iloc[-i].close>df.iloc[-i].open for i in range(1,4)),
        "3_black":          all(df.iloc[-i].close<df.iloc[-i].open for i in range(1,4)),
    }

def sr_levels(close, n=50):
    r = close.tail(n)
    return {"resistance": float(r.max()), "support": float(r.min()),
            "pivot": float((r.max()+r.min()+r.iloc[-1])/3)}
