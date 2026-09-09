from __future__ import annotations

from ..config import Config
from .base import Connector


def build_connectors(cfg: Config) -> list[Connector]:
    from .bitcoin import BitcoinConnector
    from .fina import FinaConnector
    from .plaid import PlaidConnector
    from .zerion import ZerionConnector
    return [PlaidConnector(cfg), FinaConnector(cfg), ZerionConnector(cfg), BitcoinConnector(cfg)]
