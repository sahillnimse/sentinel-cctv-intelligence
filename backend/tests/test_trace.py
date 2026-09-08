"""Vehicle trace — the endpoint the technical test case is scored on.

The measured failure mode on real grid footage is single-character drift: the
prefix and body of a plate stay stable while the last characters wander and
the state code occasionally flips. The trace has to survive that consistently:
if the route is assembled fuzzily and alerts fire fuzzily, the watchlist
verdict on the trace must not be decided by exact string equality.
"""

from datetime import datetime, timedelta

import pytest

from app.models import Base, Camera, Sighting, WatchlistEntry


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path}/trace.db")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def grid(db):
    """Four cameras along a corridor, ~1.2 km apart."""
    cams = []
    for i in range(4):
        c = Camera(name=f"CAM{i + 1:02d}", rtsp_url=f"rtsp://x/{i}",
                   latitude=23.00 + i * 0.011, longitude=72.54,
                   location_name=f"Junction {i + 1}")
        db.add(c)
        cams.append(c)
    db.commit()
    return cams


def sight(db, cam, plate, minutes_ago):
    s = Sighting(camera_id=cam.id, plate=plate, plate_raw=plate, confidence=0.9,
                 ts=datetime.utcnow() - timedelta(minutes=minutes_ago),
                 snapshot=f"{plate}.jpg")
    db.add(s)
    db.commit()
    return s


class TestRouteAssembly:
    def test_exact_reads_form_a_route(self, db, grid):
        for i, cam in enumerate(grid):
            sight(db, cam, "GJ01AB1234", 20 - i * 5)

        from app.routers.sightings import _build_route
        route = _build_route(db, "GJ01AB1234", fuzzy=True)
        assert len(route) == 4
        assert [p.camera_name for p in route] == ["CAM01", "CAM02", "CAM03", "CAM04"]

    def test_route_is_time_ordered(self, db, grid):
        sight(db, grid[2], "GJ01AB1234", 5)
        sight(db, grid[0], "GJ01AB1234", 20)
        sight(db, grid[1], "GJ01AB1234", 12)

        from app.routers.sightings import _build_route
        route = _build_route(db, "GJ01AB1234", fuzzy=True)
        assert [p.camera_name for p in route] == ["CAM01", "CAM02", "CAM03"]

    def test_drifted_reads_join_the_same_route(self, db, grid):
        # One physical vehicle, read four slightly different ways.
        for cam, plate, mins in zip(grid,
                                    ["GJ01AB1234", "GJ01AB1235", "GJ01AB1234", "GJ0IAB1234"],
                                    [20, 15, 10, 5]):
            sight(db, cam, plate, mins)

        from app.routers.sightings import _build_route
        route = _build_route(db, "GJ01AB1234", fuzzy=True)
        assert len(route) == 4, "drifted reads were not collected into one route"

    def test_exact_mode_ignores_drift(self, db, grid):
        sight(db, grid[0], "GJ01AB1234", 20)
        sight(db, grid[1], "GJ01AB1235", 15)

        from app.routers.sightings import _build_route
        assert len(_build_route(db, "GJ01AB1234", fuzzy=False)) == 1

    def test_unrelated_plates_excluded(self, db, grid):
        sight(db, grid[0], "GJ01AB1234", 20)
        sight(db, grid[1], "MH12XY9999", 15)

        from app.routers.sightings import _build_route
        route = _build_route(db, "GJ01AB1234", fuzzy=True)
        assert len(route) == 1

    def test_unknown_plate_returns_empty(self, db, grid):
        from app.routers.sightings import _build_route
        assert _build_route(db, "XX00XX0000", fuzzy=True) == []

    def test_empty_plate_rejected(self, db):
        from fastapi import HTTPException
        from app.routers.sightings import _build_route
        with pytest.raises(HTTPException):
            _build_route(db, "!!!", fuzzy=True)


class TestMatchingPlates:
    def test_only_scans_distinct_plates(self, db, grid):
        # Same plate seen many times must not multiply the candidate set.
        for i in range(20):
            sight(db, grid[i % 4], "GJ01AB1234", 30 - i)

        from app.routers.sightings import _matching_plates
        assert _matching_plates(db, "GJ01AB1234", fuzzy=True) == ["GJ01AB1234"]

    def test_exact_mode_short_circuits(self, db):
        from app.routers.sightings import _matching_plates
        assert _matching_plates(db, "GJ01AB1234", fuzzy=False) == ["GJ01AB1234"]


class TestWatchlistVerdict:
    """The bug this file was written for."""

    def test_exact_watchlist_hit(self, db, grid):
        sight(db, grid[0], "GJ01AB1234", 10)
        db.add(WatchlistEntry(plate="GJ01AB1234", reason="stolen", active=True))
        db.commit()

        from app.routers.sightings import trace
        assert trace("GJ01AB1234", db=db).watchlisted is True

    def test_misread_query_still_flags_the_vehicle(self, db, grid):
        # Watchlist holds the clean plate; the OCR dropped a character.
        sight(db, grid[0], "2BH9249H", 10)
        db.add(WatchlistEntry(plate="26BH9249H", reason="stolen", active=True))
        db.commit()

        from app.routers.sightings import trace
        result = trace("2BH9249H", db=db)
        assert len(result.route) == 1
        assert result.watchlisted is True, \
            "route found fuzzily but watchlist verdict fell back to exact match"
        assert result.watchlist_reason == "stolen"

    def test_clean_query_matches_a_drifted_sighting(self, db, grid):
        sight(db, grid[0], "GJ01AB1235", 10)
        db.add(WatchlistEntry(plate="GJ01AB1234", reason="wanted", active=True))
        db.commit()

        from app.routers.sightings import trace
        assert trace("GJ01AB1234", db=db).watchlisted is True

    def test_inactive_entry_does_not_flag(self, db, grid):
        sight(db, grid[0], "GJ01AB1234", 10)
        db.add(WatchlistEntry(plate="GJ01AB1234", reason="stolen", active=False))
        db.commit()

        from app.routers.sightings import trace
        assert trace("GJ01AB1234", db=db).watchlisted is False

    def test_unrelated_plate_stays_clear(self, db, grid):
        sight(db, grid[0], "MH12XY9999", 10)
        db.add(WatchlistEntry(plate="GJ01AB1234", reason="stolen", active=True))
        db.commit()

        from app.routers.sightings import trace
        result = trace("MH12XY9999", db=db)
        assert result.watchlisted is False
        assert result.watchlist_reason == ""
