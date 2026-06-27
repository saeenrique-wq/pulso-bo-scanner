from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Asset:
    symbol: str
    broker: str
    payout: float
    is_open: bool = True
    market_type: str = "REAL"
    category: str = "forex"


@dataclass
class BrokerConfig:
    email: str = ""
    password: str = ""
    demo: bool = True
    extra: dict = field(default_factory=dict)


class BaseBroker(ABC):
    name: str = "base"
    broker_id: str = "base"

    def __init__(self, config: BrokerConfig):
        self.config = config
        self.connected = False

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def get_assets(self, market_type: str = "REAL") -> list[Asset]: ...

    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: int, count: int = 150) -> list[Candle]: ...

    def is_ready(self) -> bool:
        return self.connected
