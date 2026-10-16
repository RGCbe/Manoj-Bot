"""Lazy ccxt import, so the package works without the optional dependency installed."""

from __future__ import annotations

from typing import Any


def create_exchange(exchange_id: str, options: dict[str, Any] | None = None) -> Any:
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("ccxt is not installed; run: pip install 'manoj-bot[crypto]'") from exc
    exchange_cls = getattr(ccxt, exchange_id, None)
    if not isinstance(exchange_cls, type):
        raise ValueError(f"Unknown ccxt exchange {exchange_id!r}")
    settings = {k: v for k, v in (options or {}).items() if v is not None}
    return exchange_cls({"enableRateLimit": True, **settings})
