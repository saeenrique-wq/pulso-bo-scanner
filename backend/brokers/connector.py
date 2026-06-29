"""BrokerConnector — gestor central de brokers con auto-reconexión y failover."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .base import Asset, BaseBroker, Candle

log = logging.getLogger(__name__)

# Pares OTC objetivo
OTC_TARGETS = [
    "EURUSD-OTC", "EURJPY-OTC", "GBPUSD-OTC", "EURGBP-OTC",
    "USDJPY-OTC", "AUDCAD-OTC", "AUDCHF-OTC", "GBPJPY-OTC",
]

# Pares REAL (solo yfinance, solo lun-vie)
REAL_TARGETS = ["EURUSD", "EURJPY", "GBPUSD", "EURGBP"]


class BrokerConnector:
    """
    Gestiona múltiples brokers con:
    - Prioridad: primero el broker OTC si está conectado
    - Reconexión automática cada 60s
    - Heartbeat / detección de desconexión
    - Failover automático al siguiente broker disponible
    - Auto-descubrimiento de activos OTC abiertos
    """

    def __init__(self):
        self._brokers: dict[str, BaseBroker] = {}
        self._priority: list[str] = ["iqoption", "pocketoption", "quotex", "demo"]
        self._last_ping: dict[str, float] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._otc_assets_cache: list[Asset] = []
        self._otc_cache_ts: float = 0.0

    def register(self, broker_id: str, broker: BaseBroker):
        self._brokers[broker_id] = broker
        log.info(f"[Connector] Broker registrado: {broker_id}")

    def remove(self, broker_id: str):
        self._brokers.pop(broker_id, None)

    # ── Broker OTC activo ──────────────────────────────────
    def otc_broker(self) -> Optional[BaseBroker]:
        """Devuelve el primer broker OTC disponible según prioridad."""
        for bid in self._priority:
            b = self._brokers.get(bid)
            if b and b.is_ready() and bid != "demo":
                return b
        return None

    def real_broker(self) -> Optional[BaseBroker]:
        """Devuelve broker para activos REAL (demo = yfinance OK)."""
        for bid in self._priority:
            b = self._brokers.get(bid)
            if b and b.is_ready():
                return b
        return None

    def is_otc_available(self) -> bool:
        return self.otc_broker() is not None

    def status(self) -> dict:
        res = {}
        for bid, b in self._brokers.items():
            res[bid] = {"ready": b.is_ready(), "name": b.name}
        return res

    # ── Descubrimiento de activos OTC ─────────────────────
    async def get_otc_assets(self, min_payout: float = 0.75) -> list[Asset]:
        """
        Consulta activos OTC del broker activo.
        Usa caché de 5 min para no sobrecargar la conexión.
        """
        now = time.time()
        if self._otc_assets_cache and now - self._otc_cache_ts < 300:
            return self._otc_assets_cache

        broker = self.otc_broker()
        if not broker:
            return []

        try:
            raw = await broker.get_assets(market_type="OTC")
            # Filtrar por payout mínimo y por los targets configurados
            result = [
                a for a in raw
                if a.payout >= min_payout
            ]
            # Priorizar OTC_TARGETS y añadir otros disponibles al final
            ordered = sorted(
                result,
                key=lambda a: (OTC_TARGETS.index(a.symbol)
                               if a.symbol in OTC_TARGETS else len(OTC_TARGETS))
            )
            self._otc_assets_cache = ordered
            self._otc_cache_ts = now
            log.info(f"[Connector] Activos OTC descubiertos: {[a.symbol for a in ordered]}")
            return ordered
        except Exception as e:
            log.warning(f"[Connector] get_otc_assets error: {e}")
            return self._otc_assets_cache  # devolver caché anterior si hay error

    async def get_real_assets(self, min_payout: float = 0.80) -> list[Asset]:
        from .demo import REAL_ASSETS
        return [
            Asset(symbol=sym, broker="DEMO", payout=data[2],
                  is_open=True, market_type="REAL", category="Forex")
            for sym, data in REAL_ASSETS.items()
        ]

    # ── Obtención de velas con routing automático ─────────
    async def get_candles(self, symbol: str, timeframe: int,
                           count: int = 150) -> list[Candle]:
        is_otc = symbol.upper().endswith("-OTC") or "_OTC" in symbol.upper()

        if is_otc:
            broker = self.otc_broker()
            if not broker:
                return []  # NUNCA retornar datos falsos para OTC
        else:
            broker = self.real_broker()
            if not broker:
                return []

        try:
            return await broker.get_candles(symbol, timeframe, count)
        except Exception as e:
            log.warning(f"[Connector] get_candles {symbol} {timeframe}s: {e}")
            return []

    # ── Reconexión automática ──────────────────────────────
    async def start_watchdog(self, interval: int = 60):
        """Tarea de fondo: reconecta brokers caídos cada `interval` segundos."""
        while True:
            await asyncio.sleep(interval)
            for bid, b in list(self._brokers.items()):
                if bid == "demo":
                    continue
                if not b.is_ready():
                    log.info(f"[Connector] Reconectando {bid}...")
                    try:
                        ok = await asyncio.wait_for(b.connect(), timeout=15)
                        if ok:
                            log.info(f"[Connector] {bid} reconectado")
                            self._otc_cache_ts = 0  # invalidar caché de activos
                        else:
                            log.warning(f"[Connector] {bid} reconexión fallida")
                    except asyncio.TimeoutError:
                        log.warning(f"[Connector] {bid} timeout en reconexión")
                    except Exception as e:
                        log.warning(f"[Connector] {bid} error reconexión: {e}")
