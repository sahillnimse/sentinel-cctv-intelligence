"""WebSocket alert hub.

Ingestion workers run in plain threads; the FastAPI event loop is captured at
startup so workers can push alerts onto it thread-safely.

Two fanout modes:

  in-process   the default. Correct and dependency-free for a single central
               instance, which is what a district deployment runs.

  shared bus   set ALERT_BUS_URL to a Redis URL. Events are published to a
               channel and every instance's subscriber delivers them to its own
               sockets, so the central tier can sit behind a load balancer
               without an operator missing alerts raised on another instance.

The bus is loopback-delivered: with it enabled, a publisher does not also send
locally, because its own subscriber will receive the message. If publishing
fails the event is sent locally anyway, since a degraded fanout beats a
dropped alert.
"""

import asyncio
import json
import logging
import threading
from typing import Optional

from fastapi import WebSocket

from .config import settings

log = logging.getLogger("sentinel.ws")

_loop: Optional[asyncio.AbstractEventLoop] = None
_clients: set[WebSocket] = set()
_clients_lock = threading.Lock()

_bus = None                      # redis client when the shared bus is up
_bus_task: Optional[asyncio.Task] = None
_bus_state = {"enabled": False, "connected": False, "error": ""}


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    with _clients_lock:
        _clients.add(ws)


def disconnect(ws: WebSocket) -> None:
    with _clients_lock:
        _clients.discard(ws)


def client_count() -> int:
    with _clients_lock:
        return len(_clients)


async def _send_all(payload: str) -> None:
    with _clients_lock:
        targets = list(_clients)
    dead = []
    for ws in targets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    if dead:
        with _clients_lock:
            for ws in dead:
                _clients.discard(ws)


# --- shared bus -------------------------------------------------------------

def bus_status() -> dict:
    return dict(_bus_state)


async def start_bus() -> bool:
    """Connect the shared alert bus. No-op when ALERT_BUS_URL is unset.

    Never raises: a bus that will not come up leaves the in-process fanout in
    place and records why, rather than stopping the server from booting.
    """
    global _bus, _bus_task
    url = (settings.alert_bus_url or "").strip()
    if not url:
        return False
    _bus_state["enabled"] = True
    try:
        import redis.asyncio as aioredis
    except ImportError:
        _bus_state["error"] = ("redis package not installed; "
                               "falling back to in-process fanout")
        log.warning(_bus_state["error"])
        return False
    try:
        client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        await client.ping()
    except Exception as exc:
        _bus_state["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("alert bus unavailable (%s); using in-process fanout",
                    _bus_state["error"])
        return False
    _bus = client
    _bus_state.update(connected=True, error="")
    _bus_task = asyncio.create_task(_subscribe(), name="alert-bus-subscriber")
    log.info("alert bus connected on channel %s", settings.alert_bus_channel)
    return True


async def stop_bus() -> None:
    global _bus, _bus_task
    if _bus_task is not None:
        _bus_task.cancel()
        _bus_task = None
    if _bus is not None:
        try:
            await _bus.aclose()
        except Exception:
            pass
        _bus = None
    _bus_state.update(connected=False)


async def _subscribe() -> None:
    """Deliver everything on the channel to this instance's sockets."""
    channel = settings.alert_bus_channel
    while True:
        try:
            pubsub = _bus.pubsub()
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                await _send_all(message["data"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A dropped Redis connection must not take the hub down with it.
            _bus_state.update(connected=False, error=f"{type(exc).__name__}: {exc}")
            log.warning("alert bus subscriber dropped (%s); retrying", exc)
            await asyncio.sleep(2.0)
        else:
            await asyncio.sleep(1.0)


async def _publish(payload: str) -> None:
    try:
        await _bus.publish(settings.alert_bus_channel, payload)
        _bus_state.update(connected=True)
    except Exception as exc:
        # Publish failed, so no subscriber will loop this back to us. Deliver
        # locally rather than losing the alert.
        _bus_state.update(connected=False, error=f"{type(exc).__name__}: {exc}")
        log.warning("alert bus publish failed (%s); delivering locally", exc)
        await _send_all(payload)


def broadcast(event: dict) -> None:
    """Thread-safe broadcast, callable from worker threads or async code."""
    payload = json.dumps(event, default=str)
    if _loop is None:
        return
    coro = _publish(payload) if _bus is not None else _send_all(payload)
    asyncio.run_coroutine_threadsafe(coro, _loop)
