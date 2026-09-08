"""Retention pruning.

Housekeeping must not destroy the evidence chain. An alert carries a
sighting_id and its evidence is that sighting's snapshot, so pruning a
sighting out from under a live alert leaves the alerts view rendering a hit
with nothing behind it.
"""

from datetime import datetime, timedelta

import pytest

from app.main import prune_older_than
from app.models import Alert, Base, Camera, Sighting, VehicleDetection, WatchlistEntry


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path}/retention.db")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _fixture(db, *, age_days: float, acknowledged: bool):
    cam = Camera(name="Junction", rtsp_url="rtsp://x/1")
    db.add(cam)
    db.commit()
    ts = datetime.utcnow() - timedelta(days=age_days)
    s = Sighting(camera_id=cam.id, plate="GJ01AB1234", ts=ts, snapshot="a.jpg")
    db.add(s)
    w = WatchlistEntry(plate="GJ01AB1234")
    db.add(w)
    db.commit()
    a = Alert(sighting_id=s.id, watchlist_id=w.id, camera_id=cam.id,
              plate="GJ01AB1234", ts=ts, acknowledged=acknowledged)
    db.add(a)
    db.add(VehicleDetection(camera_id=cam.id, vehicle_type="car", ts=ts))
    db.commit()
    return cam, s, a


class TestPrune:
    def test_acknowledged_alert_and_its_sighting_go_together(self, db):
        _, s, a = _fixture(db, age_days=2, acknowledged=True)
        sid, aid = s.id, a.id

        prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        db.expunge_all()

        assert db.get(Alert, aid) is None
        assert db.get(Sighting, sid) is None

    def test_unacknowledged_alert_keeps_its_evidence(self, db):
        _, s, a = _fixture(db, age_days=30, acknowledged=False)
        sid, aid = s.id, a.id

        prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        db.expunge_all()

        # An outstanding alert is not housekeeping, however old it is.
        alert = db.get(Alert, aid)
        assert alert is not None
        assert db.get(Sighting, alert.sighting_id) is not None, \
            "unacknowledged alert was left pointing at a deleted sighting"

    def test_no_alert_ever_points_at_a_missing_sighting(self, db):
        for age, ack in ((2, True), (5, False), (0.1, True)):
            _fixture(db, age_days=age, acknowledged=ack)

        prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        db.expunge_all()

        for alert in db.query(Alert).all():
            assert db.get(Sighting, alert.sighting_id) is not None, \
                f"alert {alert.id} orphaned by pruning"

    def test_recent_data_untouched(self, db):
        _, s, a = _fixture(db, age_days=0, acknowledged=True)
        sid, aid = s.id, a.id

        prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        db.expunge_all()

        assert db.get(Sighting, sid) is not None
        assert db.get(Alert, aid) is not None

    def test_detections_are_pruned_by_age(self, db):
        _fixture(db, age_days=2, acknowledged=True)
        counts = prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        assert counts["detections"] == 1

    def test_returns_counts(self, db):
        _fixture(db, age_days=2, acknowledged=True)
        counts = prune_older_than(db, datetime.utcnow() - timedelta(days=1))
        assert set(counts) == {"alerts", "sightings", "detections"}
        assert counts["alerts"] == 1
        assert counts["sightings"] == 1

    def test_empty_database_is_safe(self, db):
        assert prune_older_than(db, datetime.utcnow()) == {
            "alerts": 0, "sightings": 0, "detections": 0}
