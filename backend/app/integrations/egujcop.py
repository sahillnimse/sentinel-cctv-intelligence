"""MOCK eGujCop — Gujarat Police CCTNS.

============================ INTEGRATION CONTRACT ============================
eGujCop is the Gujarat Police deployment of CCTNS (Crime and Criminal Tracking
Network & Systems). It is the authority for FIRs, stolen-vehicle reports,
wanted and missing persons, and arrest records within the State.

This module ships NO real data and makes NO outbound calls. Production
replaces the bodies of `lookup_vehicle` and `lookup_person` with authenticated
calls to the eGujCop / CCTNS interface, keeping the same return shape.

Vehicle lookup returns, per the CCTNS theft record:
    fir_number, fir_date, police_station, district, sections, status,
    reported_stolen, complainant, investigating_officer

Person lookup returns:
    person_id, name, aliases, wanted, missing, arrest_history, last_known_district

Determinism: derived from a stable hash of the normalized subject, so demos
and screenshots reproduce exactly without a datastore.
=============================================================================
"""

import hashlib
from datetime import datetime, timedelta

from ..utils.plates import normalize
from .base import ConnectorInfo, LookupResult

DISTRICTS = ["Ahmedabad City", "Surat City", "Vadodara City", "Rajkot City",
             "Gandhinagar", "Valsad", "Dahod", "Jamnagar", "Junagadh", "Kutch"]

STATIONS = ["Sector 7 PS", "Navrangpura PS", "Satellite PS", "Vastrapur PS",
            "Adajan PS", "Gotri PS", "Bhaktinagar PS", "Sector 21 PS"]

# Indian Penal Code / BNS sections that actually attach to vehicle theft.
THEFT_SECTIONS = ["IPC 379", "IPC 379 r/w 411", "BNS 303(2)", "IPC 380"]

STATUSES = ["UNDER INVESTIGATION", "CHARGESHEETED", "RECOVERED", "PENDING"]

FIRST_NAMES = ["Rakesh", "Imran", "Sanjay", "Dinesh", "Prakash", "Ashok",
               "Mukesh", "Nitin", "Jayesh", "Ravi"]
LAST_NAMES = ["Solanki", "Chauhan", "Parmar", "Vaghela", "Rathod", "Zala",
              "Makwana", "Damor", "Baria", "Kharadi"]


def _digest(value: str) -> list[int]:
    h = hashlib.sha256(value.encode()).digest()
    return list(h)


class EGujCopConnector:
    key = "egujcop"
    label = "eGujCop (CCTNS)"
    authority = "Gujarat Police"
    kind = "both"

    def configured(self) -> bool:
        return True   # the mock always answers; a live one would check credentials

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            self.key, self.label, self.authority, self.kind, live=False,
            detail="deterministic mock — no live CCTNS credentials issued to participants",
            fields=["fir_number", "fir_date", "police_station", "district",
                    "sections", "status", "reported_stolen", "complainant",
                    "investigating_officer"],
        )

    def lookup_vehicle(self, plate: str) -> LookupResult:
        subject = normalize(plate)
        if not subject:
            return LookupResult(self.key, plate, found=False)

        d = _digest("veh:" + subject)

        # Most vehicles have no FIR against them. Roughly one in six does,
        # which keeps the console honest rather than flagging everything.
        if d[0] % 6 != 0:
            return LookupResult(self.key, subject, found=False,
                                record={"reported_stolen": False})

        reported = datetime(2026, 1, 1) + timedelta(days=d[1] % 250)
        status = STATUSES[d[2] % len(STATUSES)]
        stolen = status not in {"RECOVERED"}
        record = {
            "fir_number": f"{d[3] % 900 + 100}/{reported.year}",
            "fir_date": reported.date().isoformat(),
            "police_station": STATIONS[d[4] % len(STATIONS)],
            "district": DISTRICTS[d[5] % len(DISTRICTS)],
            "sections": THEFT_SECTIONS[d[6] % len(THEFT_SECTIONS)],
            "status": status,
            "reported_stolen": stolen,
            "complainant": f"{FIRST_NAMES[d[7] % len(FIRST_NAMES)]} "
                           f"{LAST_NAMES[d[8] % len(LAST_NAMES)]}",
            "investigating_officer": f"PSI {LAST_NAMES[d[9] % len(LAST_NAMES)]}",
        }
        alerts = []
        if stolen:
            alerts.append(f"Reported stolen under FIR {record['fir_number']} "
                          f"({record['police_station']})")
        return LookupResult(self.key, subject, found=True, record=record, alerts=alerts)

    def lookup_person(self, reference: str) -> LookupResult:
        subject = (reference or "").strip().upper()
        if not subject:
            return LookupResult(self.key, reference, found=False)

        d = _digest("per:" + subject)
        if d[0] % 4 != 0:
            return LookupResult(self.key, subject, found=False)

        wanted = d[1] % 3 == 0
        missing = (not wanted) and d[2] % 5 == 0
        record = {
            "person_id": f"GJ-CCTNS-{d[3] % 90000 + 10000}",
            "name": f"{FIRST_NAMES[d[4] % len(FIRST_NAMES)]} "
                    f"{LAST_NAMES[d[5] % len(LAST_NAMES)]}",
            "aliases": [FIRST_NAMES[d[6] % len(FIRST_NAMES)]] if d[6] % 2 else [],
            "wanted": wanted,
            "missing": missing,
            "arrest_history": d[7] % 5,
            "last_known_district": DISTRICTS[d[8] % len(DISTRICTS)],
        }
        alerts = []
        if wanted:
            alerts.append(f"Wanted person, {record['arrest_history']} prior arrest(s)")
        if missing:
            alerts.append("Reported missing")
        return LookupResult(self.key, subject, found=True, record=record, alerts=alerts)
