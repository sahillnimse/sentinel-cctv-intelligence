"""Store-and-forward spool for edge nodes.

A district node in Valsad or Dahod loses its uplink regularly. Analytics keeps
running locally; detections queue here in SQLite and drain when the link comes
back. Video never travels, only the metadata record, which is why a spool of a
few megabytes covers hours of outage.

SQLite rather than the main ORM on purpose: the spool must survive the process
that writes it, cost nothing when idle, and have no dependency on the central
database being reachable. It is the one piece that has to work when everything
else is down.
"""

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger("sentinel.edge.spool")

SCHEMA = """
CREATE TABLE IF NOT EXISTS spool (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,
    payload    TEXT    NOT NULL,
    created_at REAL    NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS spool_created ON spool(created_at);
"""


class Spool:
    """Durable FIFO queue of pending events.

    Thread-safe via a lock around a single connection; the write rate here is
    a few events per second per node, so contention is not a concern and one
    connection avoids SQLite's multi-connection locking entirely.
    """

    def __init__(self, path: Path, max_rows: int = 100_000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_rows = max_rows
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        # WAL keeps readers from blocking the writer during a drain.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()

    def put(self, kind: str, payload: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO spool (kind, payload, created_at) VALUES (?, ?, ?)",
                (kind, json.dumps(payload, default=str), time.time()),
            )
            self._conn.commit()
            rowid = cur.lastrowid

            # Bounded: if the link has been down long enough to fill the spool,
            # drop the oldest. Losing the oldest metadata beats the node
            # filling its disk and stopping detection altogether.
            count = self._conn.execute("SELECT COUNT(*) FROM spool").fetchone()[0]
            if count > self.max_rows:
                excess = count - self.max_rows
                self._conn.execute(
                    "DELETE FROM spool WHERE id IN "
                    "(SELECT id FROM spool ORDER BY created_at LIMIT ?)", (excess,))
                self._conn.commit()
                log.warning("spool full, dropped %d oldest events", excess)
        return rowid

    def peek(self, limit: int = 100) -> list[tuple[int, str, dict]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kind, payload FROM spool ORDER BY created_at LIMIT ?",
                (limit,)).fetchall()
        out = []
        bad_ids = []
        for rid, kind, payload in rows:
            try:
                out.append((rid, kind, json.loads(payload)))
            except json.JSONDecodeError:
                log.error("spool row %s has unparseable payload, dropping", rid)
                bad_ids.append(rid)
        if bad_ids:
            self.ack(bad_ids)
        return out

    def ack(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._lock:
            self._conn.executemany("DELETE FROM spool WHERE id = ?", [(i,) for i in ids])
            self._conn.commit()

    def fail(self, ids: Iterable[int], error: str) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE spool SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                [(error[:300], i) for i in ids])
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), MIN(created_at), MAX(created_at), MAX(attempts) "
                "FROM spool").fetchone()
        count, oldest, newest, attempts = row
        return {
            "pending": count or 0,
            "oldest_age_s": round(time.time() - oldest, 1) if oldest else 0.0,
            "newest_age_s": round(time.time() - newest, 1) if newest else 0.0,
            "max_attempts": attempts or 0,
            "path": str(self.path),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class Forwarder(threading.Thread):
    """Drains a spool to the central tier, backing off while the link is down.

    `send` takes a batch and returns True only when the centre has accepted it.
    Anything else counts as a failed attempt and the batch stays queued, which
    is what makes delivery at-least-once rather than best-effort.
    """

    def __init__(self, spool: Spool, send: Callable[[list[tuple[int, str, dict]]], bool],
                 batch: int = 100, idle_seconds: float = 5.0,
                 backoff_start: float = 2.0, backoff_cap: float = 60.0):
        super().__init__(daemon=True, name="edge-forwarder")
        self.spool = spool
        self.send = send
        self.batch = batch
        self.idle_seconds = idle_seconds
        self.backoff_start = backoff_start
        self.backoff_cap = backoff_cap
        self.stop_event = threading.Event()
        self.online = True
        self.delivered = 0

    def run(self) -> None:
        backoff = self.backoff_start
        while not self.stop_event.is_set():
            rows = self.spool.peek(self.batch)
            if not rows:
                self.stop_event.wait(self.idle_seconds)
                continue
            try:
                ok = self.send(rows)
            except Exception as exc:
                ok = False
                self.spool.fail([r[0] for r in rows], str(exc))
                log.warning("forward failed: %s", exc)

            if ok:
                self.spool.ack([r[0] for r in rows])
                self.delivered += len(rows)
                if not self.online:
                    log.info("uplink restored, drained %d events", len(rows))
                self.online = True
                backoff = self.backoff_start
            else:
                self.online = False
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, self.backoff_cap)

    def stats(self) -> dict:
        return {"online": self.online, "delivered": self.delivered,
                "alive": self.is_alive(), **self.spool.stats()}
