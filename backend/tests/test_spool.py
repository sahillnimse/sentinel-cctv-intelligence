"""Edge store-and-forward spool.

What matters operationally: nothing is lost while the uplink is down, nothing
is acknowledged that was not delivered, and a long outage cannot fill the
node's disk and stop detection.
"""

import pytest

from app.edge.spool import Forwarder, Spool


@pytest.fixture
def spool(tmp_path):
    s = Spool(tmp_path / "spool.db")
    yield s
    s.close()


class TestSpool:
    def test_put_and_peek(self, spool):
        spool.put("sighting", {"plate": "GJ01AB1234"})
        rows = spool.peek()
        assert len(rows) == 1
        _, kind, payload = rows[0]
        assert kind == "sighting"
        assert payload["plate"] == "GJ01AB1234"

    def test_fifo_order(self, spool):
        for i in range(5):
            spool.put("vehicle", {"n": i})
        assert [p["n"] for _, _, p in spool.peek()] == [0, 1, 2, 3, 4]

    def test_ack_removes(self, spool):
        spool.put("sighting", {"plate": "A"})
        spool.put("sighting", {"plate": "B"})
        rows = spool.peek()
        spool.ack([rows[0][0]])
        remaining = spool.peek()
        assert len(remaining) == 1
        assert remaining[0][2]["plate"] == "B"

    def test_fail_keeps_row_and_counts(self, spool):
        spool.put("sighting", {"plate": "A"})
        rid = spool.peek()[0][0]
        spool.fail([rid], "connection refused")
        assert len(spool.peek()) == 1
        assert spool.stats()["max_attempts"] == 1

    def test_ack_empty_is_safe(self, spool):
        spool.ack([])
        spool.fail([], "x")

    def test_peek_limit(self, spool):
        for i in range(10):
            spool.put("vehicle", {"n": i})
        assert len(spool.peek(limit=3)) == 3

    def test_survives_reopen(self, tmp_path):
        path = tmp_path / "persist.db"
        s1 = Spool(path)
        s1.put("sighting", {"plate": "GJ01AB1234"})
        s1.close()

        s2 = Spool(path)
        assert len(s2.peek()) == 1
        s2.close()

    def test_bounded_drops_oldest(self, tmp_path):
        s = Spool(tmp_path / "bounded.db", max_rows=10)
        for i in range(25):
            s.put("vehicle", {"n": i})
        rows = s.peek(limit=100)
        assert len(rows) <= 10
        # the survivors are the newest, not the oldest
        assert rows[-1][2]["n"] == 24
        s.close()

    def test_stats_on_empty(self, spool):
        st = spool.stats()
        assert st["pending"] == 0
        assert st["oldest_age_s"] == 0.0


class TestForwarder:
    def test_delivers_and_acks(self, spool):
        sent = []

        def send(rows):
            sent.extend(rows)
            return True

        spool.put("sighting", {"plate": "GJ01AB1234"})
        fw = Forwarder(spool, send, idle_seconds=0.01)
        fw.start()
        try:
            for _ in range(200):
                if not spool.peek():
                    break
                fw.stop_event.wait(0.02)
        finally:
            fw.stop_event.set()
            fw.join(timeout=2)

        assert spool.peek() == []
        assert len(sent) == 1
        assert fw.delivered == 1

    def test_failure_keeps_events_queued(self, spool):
        def send(rows):
            return False

        spool.put("sighting", {"plate": "GJ01AB1234"})
        fw = Forwarder(spool, send, idle_seconds=0.01, backoff_start=0.01,
                       backoff_cap=0.02)
        fw.start()
        try:
            fw.stop_event.wait(0.2)
            # Nothing acknowledged, because nothing was delivered.
            assert len(spool.peek()) == 1
            assert fw.online is False
        finally:
            fw.stop_event.set()
            fw.join(timeout=2)

    def test_exception_is_not_fatal(self, spool):
        def send(rows):
            raise ConnectionError("uplink down")

        spool.put("sighting", {"plate": "GJ01AB1234"})
        fw = Forwarder(spool, send, idle_seconds=0.01, backoff_start=0.01,
                       backoff_cap=0.02)
        fw.start()
        try:
            fw.stop_event.wait(0.2)
            assert fw.is_alive()
            assert len(spool.peek()) == 1
            assert spool.stats()["max_attempts"] >= 1
        finally:
            fw.stop_event.set()
            fw.join(timeout=2)
