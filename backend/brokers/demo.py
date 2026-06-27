"""Demo broker — activos reales de plataformas BO (Quotex, IQ Option, Pocket Option, Exnova)."""
from __future__ import annotations

import asyncio
from typing import Optional
import pandas as pd
import yfinance as yf

from .base import Asset, BaseBroker, BrokerConfig, Candle

# ── TOP 5 MÁS OPERADOS EN PLATAFORMAS BO ──────────────────
# Escaneados primero y con prioridad — los de mayor volumen y señales
TOP5_REAL = ["EURUSD", "GBPUSD", "XAUUSD", "BTCUSD", "USDJPY"]
TOP5_OTC  = ["EURUSD-OTC", "GBPUSD-OTC", "XAUUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC"]

# ── ACTIVOS REALES — exactamente los disponibles en Quotex / IQ Option / Exnova / Pocket Option ──
# (sym_bo): (ticker_yfinance, categoria_bo, payout_tipico)
REAL_ASSETS = {
    # Pares forex principales — disponibles en todas las plataformas BO
    "EURUSD":  ("EURUSD=X",  "Forex",      0.87),
    "GBPUSD":  ("GBPUSD=X",  "Forex",      0.86),
    "USDJPY":  ("USDJPY=X",  "Forex",      0.85),
    "AUDUSD":  ("AUDUSD=X",  "Forex",      0.84),
    "USDCAD":  ("USDCAD=X",  "Forex",      0.84),
    "USDCHF":  ("USDCHF=X",  "Forex",      0.83),
    "NZDUSD":  ("NZDUSD=X",  "Forex",      0.82),
    "EURGBP":  ("EURGBP=X",  "Forex",      0.82),
    "EURJPY":  ("EURJPY=X",  "Forex",      0.85),
    "GBPJPY":  ("GBPJPY=X",  "Forex",      0.84),
    "GBPAUD":  ("GBPAUD=X",  "Forex",      0.82),
    "EURCAD":  ("EURCAD=X",  "Forex",      0.82),
    # Oro y Plata — los más operados en BO
    "XAUUSD":  ("GC=F",      "Commodities", 0.88),
    "XAGUSD":  ("SI=F",      "Commodities", 0.83),
    # Petróleo — disponible en Quotex / IQ Option
    "USOIL":   ("CL=F",      "Commodities", 0.80),
    # Crypto — disponibles en todas las plataformas BO
    "BTCUSD":  ("BTC-USD",   "Crypto",     0.86),
    "ETHUSD":  ("ETH-USD",   "Crypto",     0.85),
    "LTCUSD":  ("LTC-USD",   "Crypto",     0.83),
    "XRPUSD":  ("XRP-USD",   "Crypto",     0.83),
    # Índices — disponibles en Quotex y IQ Option
    "US30":    ("^DJI",      "Indices",    0.80),
    "US500":   ("^GSPC",     "Indices",    0.80),
    "US100":   ("^NDX",      "Indices",    0.80),
    "AUS200":  ("^AXJO",     "Indices",    0.80),
}

# ── ACTIVOS OTC — exclusivos de plataformas BO, disponibles 24/7 incluyendo fines de semana ──
# Pares reales de Quotex / IQ Option / Pocket Option / Exnova.
# Los pares exóticos (USDBRL, USDMXN, etc.) usan el precio spot de yfinance como proxy.
OTC_ASSETS = {
    # Majors OTC — todos los brokers BO
    "EURUSD-OTC":  ("EURUSD=X",  "OTC", 0.84),
    "GBPUSD-OTC":  ("GBPUSD=X",  "OTC", 0.83),
    "USDJPY-OTC":  ("USDJPY=X",  "OTC", 0.82),
    "AUDUSD-OTC":  ("AUDUSD=X",  "OTC", 0.82),
    "USDCAD-OTC":  ("USDCAD=X",  "OTC", 0.81),
    "USDCHF-OTC":  ("USDCHF=X",  "OTC", 0.81),
    "NZDUSD-OTC":  ("NZDUSD=X",  "OTC", 0.80),
    "EURGBP-OTC":  ("EURGBP=X",  "OTC", 0.80),
    "EURJPY-OTC":  ("EURJPY=X",  "OTC", 0.82),
    "GBPJPY-OTC":  ("GBPJPY=X",  "OTC", 0.81),
    "NZDCAD-OTC":  ("NZDCAD=X",  "OTC", 0.80),
    "EURCAD-OTC":  ("EURCAD=X",  "OTC", 0.80),
    "GBPCAD-OTC":  ("GBPCAD=X",  "OTC", 0.80),
    # Exóticos OTC — muy populares en Quotex / Pocket Option / Exnova
    "USDBRL-OTC":  ("BRL=X",     "OTC", 0.82),
    "USDMXN-OTC":  ("MXN=X",     "OTC", 0.80),
    "USDINR-OTC":  ("INR=X",     "OTC", 0.80),
    "USDTRY-OTC":  ("TRY=X",     "OTC", 0.82),
    "USDZAR-OTC":  ("ZAR=X",     "OTC", 0.80),
    "USDSGD-OTC":  ("SGD=X",     "OTC", 0.80),
    "USDHKD-OTC":  ("HKD=X",     "OTC", 0.80),
    "USDTWD-OTC":  ("TWD=X",     "OTC", 0.80),
    # Commodities OTC
    "XAUUSD-OTC":  ("GC=F",      "OTC", 0.85),
    "XAGUSD-OTC":  ("SI=F",      "OTC", 0.82),
    # Crypto OTC
    "BTCUSD-OTC":  ("BTC-USD",   "OTC", 0.83),
    "ETHUSD-OTC":  ("ETH-USD",   "OTC", 0.82),
}

_TF = {60: "1m", 300: "5m", 900: "15m", 3600: "1h"}
_ALL = {**REAL_ASSETS, **OTC_ASSETS}


class DemoBroker(BaseBroker):
    name = "DEMO"
    broker_id = "demo"

    def __init__(self):
        super().__init__(BrokerConfig())

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False

    async def get_assets(self, market_type: str = "REAL") -> list[Asset]:
        pool = OTC_ASSETS if market_type.upper() == "OTC" else REAL_ASSETS
        return [
            Asset(symbol=sym, broker=self.name, payout=data[2],
                  is_open=True, market_type=market_type.upper(), category=data[1])
            for sym, data in pool.items()
        ]

    async def get_candles(self, symbol: str, timeframe: int, count: int = 150) -> list[Candle]:
        entry = _ALL.get(symbol)
        if not entry:
            return []
        ticker = entry[0]
        interval = _TF.get(timeframe, "5m")
        period = "3d" if timeframe <= 300 else "7d"
        try:
            df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: yf.download(ticker, period=period, interval=interval,
                                     progress=False, auto_adjust=True),
            )
            if df.empty:
                return []
            df = df.tail(count)

            def _v(cell, d=0.0):
                if hasattr(cell, "iloc"):
                    return float(cell.iloc[0])
                try:
                    return float(cell)
                except Exception:
                    return d

            return [
                Candle(time=int(pd.Timestamp(ts).timestamp()),
                       open=_v(row["Open"]), high=_v(row["High"]),
                       low=_v(row["Low"]),  close=_v(row["Close"]),
                       volume=_v(row.get("Volume", 0.0)))
                for ts, row in df.iterrows()
            ]
        except Exception:
            return []


# Adapter stubs para brokers reales (instalan su propia lib)
class QuotexBroker(BaseBroker):
    name = "Quotex"; broker_id = "quotex"
    async def connect(self):
        try:
            from pyquotex.stable_api import Quotex
            self._c = Quotex(email=self.config.email, password=self.config.password)
            ok, _ = await self._c.connect()
            self.connected = ok; return ok
        except ImportError:
            print("[Quotex] pip install pyquotex"); return False
    async def disconnect(self):
        if hasattr(self,'_c'): self._c.close(); self.connected=False
    async def get_assets(self, market_type="REAL"):
        if not self.connected: return []
        raw = await self._c.get_all_asset()
        return [Asset(s.get("symbol",""), self.name, s.get("payout",0)/100,
                      s.get("open",False), market_type.upper(), "forex")
                for s in (raw or []) if s.get("open") and s.get("payout",0)>=75]
    async def get_candles(self, symbol, timeframe, count=150):
        if not self.connected: return []
        raw = await self._c.get_candles(symbol, timeframe, timeframe*count, None)
        return [Candle(int(c.get("time",0)),float(c.get("open",0)),
                       float(c.get("max",0)),float(c.get("min",0)),
                       float(c.get("close",0))) for c in (raw or [])][-count:]


class PocketBroker(BaseBroker):
    name = "PocketOption"; broker_id = "pocketoption"
    async def connect(self):
        try:
            from BinaryOptionsToolsV2.pocketoption import PocketOption
            ssid = self.config.extra.get("ssid","")
            if not ssid: print("[PocketOption] falta POCKET_SSID"); return False
            self._c = PocketOption(ssid, self.config.demo)
            await self._c.connect(); self.connected=True; return True
        except ImportError:
            print("[PocketOption] pip install binaryoptionstoolsv2"); return False
    async def disconnect(self):
        if hasattr(self,'_c'): await self._c.disconnect(); self.connected=False
    async def get_assets(self, market_type="REAL"):
        if not self.connected: return []
        raw = await self._c.get_asset()
        return [Asset(sym, self.name, d.get("payout",0)/100,
                      d.get("open",False), market_type.upper(), "forex")
                for sym,d in (raw or {}).items() if d.get("open") and d.get("payout",0)>=75]
    async def get_candles(self, symbol, timeframe, count=150):
        if not self.connected: return []
        raw = await self._c.get_candles(symbol, timeframe, count)
        return [Candle(int(c.get("time",0)),float(c.get("open",0)),
                       float(c.get("max",c.get("high",0))),
                       float(c.get("min",c.get("low",0))),
                       float(c.get("close",0))) for c in (raw or [])]


class IQBroker(BaseBroker):
    name = "Exnova/IQOption"; broker_id = "iqoption"
    async def connect(self):
        try:
            import time as _t
            from iqoptionapi.stable_api import IQ_Option
            self._c = IQ_Option(self.config.email, self.config.password)
            ok, _ = await asyncio.get_event_loop().run_in_executor(None, self._c.connect)
            if ok:
                self._c.change_balance("PRACTICE" if self.config.demo else "REAL")
                self.connected=True
            return ok
        except ImportError:
            print("[IQOption] pip install iqoptionapi"); return False
    async def disconnect(self):
        if hasattr(self,'_c'): self._c.close(); self.connected=False
    async def get_assets(self, market_type="REAL"):
        if not self.connected: return []
        all_a = await asyncio.get_event_loop().run_in_executor(None, self._c.get_all_open_time)
        assets=[]
        for cat in ("forex","crypto","commodity"):
            for sym,d in all_a.get(cat,{}).items():
                if d.get("open"):
                    pay=(d.get("profit",{}).get("front",0))/100
                    if pay>=0.75:
                        assets.append(Asset(sym.upper(),self.name,pay,True,market_type.upper(),cat))
        return assets
    async def get_candles(self, symbol, timeframe, count=150):
        if not self.connected: return []
        import time as _t
        tf_min={60:1,300:5,900:15,3600:60}.get(timeframe,5)
        raw = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._c.get_candles(symbol, tf_min*60, count, _t.time()))
        return [Candle(int(c.get("from",0)),float(c.get("open",0)),
                       float(c.get("max",0)),float(c.get("min",0)),
                       float(c.get("close",0)),float(c.get("volume",0)))
                for c in (raw or [])]
