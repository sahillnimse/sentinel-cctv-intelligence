"""MOCK AFIS and NAFIS — fingerprint identification.

============================ INTEGRATION CONTRACT ============================
AFIS is the State-level Automated Fingerprint Identification System. NAFIS is
the NCRB's National Automated Fingerprint Identification System. Both answer
the same question at different scopes: does this person's biometric match an
enrolled record, and what does that record say.

Neither is reachable from a hackathon environment, and neither would ever be
queried from a face match alone in a real deployment. That matters enough to
say plainly in the code: a face match is a *lead*, not an identification. The
lawful sequence is face match -> human review -> a person of interest ->
tenprint or latent submission to AFIS/NAFIS by an authorised officer. This
connector models that hand-off; it does not pretend a camera can fingerprint
somebody.

Production replaces `lookup_person` with an authenticated submission to the
respective service, keeping the return shape. NAFIS in particular is
access-controlled per officer and every query is itself auditable, which is
why calls here route through the platform's own audit trail.

Returns:
    matched, match_score, biometric_id, enrolment_date, enrolling_agency,
    record_type, offence_categories, scope
=============================================================================
"""

import hashlib
from datetime import datetime, timedelta

from .base import ConnectorInfo, LookupResult

AGENCIES_STATE = ["Gujarat FSL Gandhinagar", "Ahmedabad City Police",
                  "Surat City Police", "Vadodara Range CID"]
AGENCIES_NATIONAL = ["NCRB Delhi", "CBI Central Fingerprint Bureau",
                     "Maharashtra CID", "Rajasthan Police", "MP Police"]

RECORD_TYPES = ["TENPRINT", "LATENT", "ARREST TENPRINT"]

OFFENCES = ["property offences", "vehicle theft", "burglary",
            "narcotics", "cheating", "assault"]


def _digest(value: str) -> list[int]:
    return list(hashlib.sha256(value.encode()).digest())


class _FingerprintConnector:
    """Shared behaviour. AFIS and NAFIS differ in scope, not in interface."""

    key = ""
    label = ""
    authority = ""
    scope = ""
    agencies: list[str] = []
    hit_rate = 5          # 1 in N enrolled subjects match
    kind = "person"

    def configured(self) -> bool:
        return True

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            self.key, self.label, self.authority, self.kind, live=False,
            detail=("deterministic mock — biometric services are not reachable from "
                    "a sandbox, and a face match is a lead requiring human review "
                    "before any biometric submission"),
            fields=["matched", "match_score", "biometric_id", "enrolment_date",
                    "enrolling_agency", "record_type", "offence_categories", "scope"],
        )

    def lookup_vehicle(self, plate: str) -> None:
        return None       # fingerprints have no view of vehicles

    def lookup_person(self, reference: str) -> LookupResult:
        subject = (reference or "").strip().upper()
        if not subject:
            return LookupResult(self.key, reference, found=False)

        d = _digest(f"{self.key}:{subject}")
        if d[0] % self.hit_rate != 0:
            return LookupResult(self.key, subject, found=False,
                                record={"matched": False, "scope": self.scope})

        enrolled = datetime(2019, 1, 1) + timedelta(days=d[1] * 8)
        score = 72 + d[2] % 27          # AFIS scores are similarity, not probability
        n_off = 1 + d[3] % 3
        record = {
            "matched": True,
            "match_score": score,
            "biometric_id": f"{self.key.upper()}-{d[4] % 900000 + 100000}",
            "enrolment_date": enrolled.date().isoformat(),
            "enrolling_agency": self.agencies[d[5] % len(self.agencies)],
            "record_type": RECORD_TYPES[d[6] % len(RECORD_TYPES)],
            "offence_categories": sorted({OFFENCES[d[7 + i] % len(OFFENCES)]
                                          for i in range(n_off)}),
            "scope": self.scope,
        }
        return LookupResult(
            self.key, subject, found=True, record=record,
            alerts=[f"{self.label} match at score {score} "
                    f"({record['record_type'].lower()}, {record['enrolling_agency']})"],
        )


class AfisConnector(_FingerprintConnector):
    key = "afis"
    label = "AFIS"
    authority = "Gujarat State Fingerprint Bureau"
    scope = "state"
    agencies = AGENCIES_STATE
    hit_rate = 4


class NafisConnector(_FingerprintConnector):
    key = "nafis"
    label = "NAFIS"
    authority = "NCRB, Government of India"
    scope = "national"
    agencies = AGENCIES_NATIONAL
    hit_rate = 6
