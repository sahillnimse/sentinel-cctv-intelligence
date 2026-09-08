"""WebSocket alert hub.

Ingestion workers run in plain threads; the FastAPI event loop is captured at
startup so workers can push alerts onto it thread-safely.
"""

import asyncio
import json
from typing import Optional

from fastapi import WebSocket

_loop: Optional[asyncio.AbstractEventLoop] = None
_clients: set[WebSocket] = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)


def disconnect(ws: WebSocket) -> None:
    _clients.discard(ws)


async def _send_all(payload: str) -> None:
    dead = []
    for ws in _clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def broadcast(event: dict) -> None:
    """Thread-safe broadcast, callable from worker threads or async code."""
    payload = json.dumps(event, default=str)
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_send_all(payload), _loop)
