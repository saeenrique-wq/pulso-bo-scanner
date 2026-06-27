"""Demo broker — activos reales de plataformas BO (Quotex, IQ Option, Pocket Option, Exnova)."""
from __future__ import annotations

import asyncio
from typing import Optional
import pandas as pd
import yfinance as yf
import httpx

from .base import Asset, BaseBroker, BrokerConfig, Candle

# ── LOS 5 PARES QUE ESCANEA ESTE BOT ────────────────────────
# EURUSD, TRUMP COIN, EURJPY, EURGBP, GBPUSD
TOP5_REAL = ["EURUSD", "TRUMPUSD", "EURJPY", "EURGBP", "GBPUSD"]
TOP5_OTC  = ["EURUSD-OTC", "TRUMPUSD-OTC", "EURJPY-OTC", "EURGBP-OTC", "GBPUSD-OTC"]

# ── ACTIVOS — prefijo "binance:" usa Binance API, resto usa yfinance ──
# (ticker, categoria, payout)
REAL_ASSETS = {
    "EURUSD":   ("EURUSD=X",          "Forex",  0.87),
    "GBPUSD":   ("GBPUSD=X",          "Forex",  0.86),
    "EURJPY":   ("EURJPY=X",          "Forex",  0.85),
    "EURGBP":   ("EURGBP=X",          "Forex",  0.82),
    "USDJPY":   ("USDJPY=X",          "Forex",  0.85),
    "AUDUSD":   ("AUDUSD=X",          "Forex",  0.84),
    "USDCAD":   ("USDCAD=X",          "Forex",  0.84),
    "USDCHF":   ("USDCHF=X",          "Forex",  0.83),
    "NZDUSD":   ("NZDUSD=X",          "Forex",  0.82),
    "GBPJPY":   ("GBPJPY=X",          "Forex",  0.84),
    "XAUUSD":   ("GC=F",              "Commodities", 0.88),
    "XAGUSD":   ("SI=F",              "Commodities", 0.83),
    "USOIL":    ("CL=F",              "Commodities", 0.80),
    "BTCUSD":   ("BTC-USD",           "Crypto", 0.86),
    "ETHUSD":   ("ETH-USD",           "Crypto", 0.85),
    "XRPUSD":   ("XRP-USD",           "Crypto", 0.83),
    "TRUMPUSD": ("binance:TRUMPUSDT", "Crypto", 0.82),  # Binance API
    "US30":     ("^DJI",              "Indices", 0.80),
    "US500":    ("^GSPC",             "Indices", 0.80),
    "US100":    ("^NDX",              "Indices", 0.80),
}

OTC_ASSETS = {
    "EURUSD-OTC":   ("EURUSD=X",          "OTC", 0.84),
    "GBPUSD-OTC":   ("GBPUSD=X",          "OTC", 0.83),
    "EURJPY-OTC":   ("EURJPY=X",          "OTC", 0.82),
    "EURGBP-OTC":   ("EURGBP=X",          "OTC", 0.80),
    "USDJPY-OTC":   ("USDJPY=X",          "OTC", 0.82),
    "AUDUSD-OTC":   ("AUDUSD=X",          "OTC", 0.82),
    "USDCAD-OTC":   ("USDCAD=X",          "OTC", 0.81),
    "USDCHF-OTC":   ("USDCHF=X",          "OTC", 0.81),
    "NZDUSD-OTC":   ("NZDUSD=X",          "OTC", 0.80),
    "GBPJPY-OTC":   ("GBPJPY=X",          "OTC", 0.81),
    "USDBRL-OTC":   ("BRL=X",             "OTC", 0.82),
    "USDMXN-OTC":   ("MXN=X",             "OTC", 0.80),
    "XAUUSD-OTC":   ("GC=F",              "OTC", 0.85),
    "BTCUSD-OTC":   ("BTC-USD",           "OTC", 0.83),
    "TRUMPUSD-OTC": ("binance:TRUMPUSDT", "OTC", 0.81),
}

_TF_YF  = {60: "1m", 300: "5m", 900: "15m", 3600: "1h"}
_TF_BIN = {60: "1m", 300: "5m", 900: "15m", 3600: "1h"}
_ALL    = {**REAL_ASSETS, **OTC_ASSETS}

BINANCE_URL = "https://api.binance.com/api/v3/klines"


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

        if ticker.startswith("binance:"):
            return await self._binance_candles(ticker[8:], timeframe, count)
        return await self._yfinance_candles(ticker, timeframe, count)

    async def _binance_candles(self, pair: str, timeframe: int, count: int) -> list[Candle]:
        interval = _TF_BIN.get(timeframe, "5m")
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(BINANCE_URL, params={
                    "symbol": pair, "interval": interval, "limit": count
                })
            if r.status_code != 200:
                return []
            return [
                Candle(
                    time   = int(k[0]) // 1000,
                    open   = float(k[1]),
                    high   = float(k[2]),
                    low    = float(k[3]),
                    close  = float(k[4]),
                    volume = float(k[5]),
                )
                for k in r.json()
            ]
        except Exception:
            return []

    async def _yfinance_candles(self, ticker: str, timeframe: int, count: int) -> list[Candle]:
        interval = _TF_YF.get(timeframe, "5m")
        period   = "3d" if timeframe <= 300 else "7d"
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
                try:   return float(cell)
                except: return d

            return [
                Candle(time=int(pd.Timestamp(ts).timestamp()),
                       open=_v(row["Open"]), high=_v(row["High"]),
                       low=_v(row["Low"]),   close=_v(row["Close"]),
                       volume=_v(row.get("Volume", 0.0)))
                for ts, row in df.iterrows()
            ]
        except Exception:
            return []


# ── Helpers para normalizar nombres OTC entre brokers ─────────
# IQ Option / Exnova usan "EURUSD(OTC)" → nosotros usamos "EURUSD-OTC"
# Pocket Option usa "EURUSD_otc" o "EURUSD-OTC"
# Quotex usa "EURUSD-OTC" (ya compatible)

def _to_internal(sym: str) -> str:
    """Convierte nombre de broker → nombre interno (ej. EURUSD(OTC) → EURUSD-OTC)."""
    s = sym.upper().strip().replace(" ", "")
    if s.endswith("(OTC)"):
        return s[:-5] + "-OTC"
    if s.endswith("_OTC"):
        return s[:-4] + "-OTC"
    return s

def _to_broker_otc(sym: str, style: str = "parens") -> str:
    """Convierte nombre interno OTC → nombre del broker específico."""
    base = sym.replace("-OTC", "").upper()
    if style == "parens":   return base + "(OTC)"    # IQ Option / Exnova
    if style == "dash":     return base + "-OTC"      # Quotex
    if style == "underscore": return base + "_otc"    # Pocket Option
    return sym


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
        if hasattr(self,'_c'): self._c.close(); self.connected = False

    async def get_assets(self, market_type="REAL"):
        if not self.connected: return []
        raw = await self._c.get_all_asset()
        result = []
        for s in (raw or []):
            if not s.get("open") or s.get("payout", 0) < 75:
                continue
            sym_int = _to_internal(s.get("symbol", ""))
            is_otc  = sym_int.endswith("-OTC")
            want_otc = market_type.upper() == "OTC"
            if is_otc != want_otc:
                continue
            result.append(Asset(sym_int, self.name, s["payout"]/100,
                                True, market_type.upper(), "Forex"))
        return result

    async def get_candles(self, symbol, timeframe, count=150):
        if not self.connected: return []
        # Quotex acepta "EURUSD-OTC" directamente
        raw = await self._c.get_candles(symbol, timeframe, timeframe*count, None)
        return [Candle(int(c.get("time",0)), float(c.get("open",0)),
                       float(c.get("max",0)),  float(c.get("min",0)),
                       float(c.get("close",0))) for c in (raw or [])][-count:]


class PocketBroker(BaseBroker):
    name = "PocketOption"; broker_id = "pocketoption"

    async def connect(self):
        try:
            from BinaryOptionsToolsV2.pocketoption import PocketOption
            ssid = self.config.extra.get("ssid", "")
            if not ssid: print("[PocketOption] falta POCKET_SSID"); return False
            self._c = PocketOption(ssid, self.config.demo)
            await self._c.connect(); self.connected = True; return True
        except ImportError:
            print("[PocketOption] pip install binaryoptionstoolsv2"); return False

    async def disconnect(self):
        if hasattr(self,'_c'): await self._c.disconnect(); self.connected = False

    async def get_assets(self, market_type="REAL"):
        if not self.connected: return []
        raw = await self._c.get_asset()
        result = []
        for sym, d in (raw or {}).items():
            if not d.get("open") or d.get("payout", 0) < 75:
                continue
            sym_int  = _to_internal(sym)
            is_otc   = sym_int.endswith("-OTC")
            want_otc = market_type.upper() == "OTC"
            if is_otc != want_otc:
                continue
            result.append(Asset(sym_int, self.name, d["payout"]/100,
                                True, market_type.upper(), "Forex"))
        return result

    async def get_candles(self, symbol, timeframe, count=150):
        if not self.connected: return []
        # Pocket Option usa "EURUSD_otc" para pares OTC
        broker_sym = _to_broker_otc(symbol, "underscore") if symbol.endswith("-OTC") else symbol
        raw = await self._c.get_candles(broker_sym, timeframe, count)
        return [Candle(int(c.get("time",0)), float(c.get("open",0)),
                       float(c.get("max", c.get("high",0))),
                       float(c.get("min", c.get("low",0))),
                       float(c.get("close",0))) for c in (raw or [])]


class IQBroker(BaseBroker):
    """
    Exnova / IQ Option — misma plataforma, distinto dominio.
    host por defecto: exnova.org  (IQ Option usa iqoption.com)

    Active IDs de los 5 pares del scanner (estándar IQ Option / Exnova):
      EURUSD=1  GBPUSD=2  EURJPY=4  EURGBP=5
      OTC: EURUSD-OTC=76  GBPUSD-OTC=77  EURJPY-OTC=79  EURGBP-OTC=80
      TRUMPUSD → no disponible en Exnova, usa Binance como fallback
    """
    name = "Exnova/IQOption"
    broker_id = "iqoption"

    # IDs de activos en la plataforma (hardcoded — estándar IQ Option / Exnova)
    _IDS: dict[str, int] = {
        "EURUSD":     1,
        "GBPUSD":     2,
        "EURJPY":     4,
        "EURGBP":     5,
        "EURUSD-OTC": 76,
        "GBPUSD-OTC": 77,
        "EURJPY-OTC": 79,
        "EURGBP-OTC": 80,
    }

    async def connect(self) -> bool:
        try:
            from iqoptionapi.api import IQOptionAPI
        except ImportError:
            print("[Exnova] pip install iqoptionapi")
            return False
        host = self.config.extra.get("host", "exnova.org")
        self._api = IQOptionAPI(host, self.config.email, self.config.password)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._api.connect)
            ok = result[0] if isinstance(result, (tuple, list)) else bool(result)
            if ok:
                self.connected = True
                print(f"[Exnova] Conectado como {self.config.email}")
            else:
                reason = result[1] if isinstance(result, (tuple, list)) else "desconocido"
                print(f"[Exnova] Fallo de conexion: {reason}")
            return ok
        except Exception as e:
            print(f"[Exnova] Error: {e}")
            return False

    async def disconnect(self):
        if hasattr(self, "_api"):
            try:
                self._api.websocket_client.wss.close()
            except Exception:
                pass
        self.connected = False

    async def get_assets(self, market_type: str = "REAL") -> list[Asset]:
        """Retorna los pares disponibles filtrando por mercado."""
        if not self.connected:
            return []
        want_otc = market_type.upper() == "OTC"
        result = []
        for sym, active_id in self._IDS.items():
            is_otc = sym.endswith("-OTC")
            if is_otc != want_otc:
                continue
            payout = OTC_ASSETS.get(sym, (None, None, 0.82))[2] if is_otc \
                else REAL_ASSETS.get(sym, (None, None, 0.82))[2]
            result.append(Asset(
                symbol=sym, broker=self.name, payout=payout,
                is_open=True, market_type=market_type.upper(), category="Forex",
            ))
        # TRUMPUSD viene de Binance (no está en Exnova)
        trump_sym = "TRUMPUSD-OTC" if want_otc else "TRUMPUSD"
        trump_data = OTC_ASSETS.get(trump_sym) or REAL_ASSETS.get(trump_sym)
        if trump_data:
            result.append(Asset(
                symbol=trump_sym, broker=self.name, payout=trump_data[2],
                is_open=True, market_type=market_type.upper(), category="Crypto",
            ))
        return result

    async def get_candles(self, symbol: str, timeframe: int, count: int = 150) -> list[Candle]:
        # TRUMPUSD no está en Exnova — usar Binance
        if "TRUMP" in symbol:
            return await DemoBroker()._binance_candles("TRUMPUSDT", timeframe, count)

        if not self.connected:
            return []

        active_id = self._IDS.get(symbol)
        if active_id is None:
            return []

        import time as _t

        def _fetch_sync():
            """Bloquea hasta recibir respuesta WebSocket de velas."""
            self._api.getcandles(active_id, timeframe, count, _t.time())
            _t.sleep(2.0)   # esperar respuesta WS
            raw = self._api.candles.data.get(active_id, {}).get(timeframe, {})
            return raw

        try:
            raw = await asyncio.get_event_loop().run_in_executor(None, _fetch_sync)
        except Exception as e:
            print(f"[Exnova] get_candles {symbol}: {e}")
            return []

        if not raw:
            return []

        candles = []
        items = raw.items() if isinstance(raw, dict) else enumerate(raw)
        for ts, cd in sorted(items):
            try:
                candles.append(Candle(
                    time=int(float(ts)),
                    open=float(cd.get("open",  cd.get("o", 0))),
                    high=float(cd.get("max",   cd.get("h", cd.get("high",  0)))),
                    low= float(cd.get("min",   cd.get("l", cd.get("low",   0)))),
                    close=float(cd.get("close",cd.get("c", 0))),
                    volume=float(cd.get("volume", 0)),
                ))
            except Exception:
                pass

        return candles[-count:]
