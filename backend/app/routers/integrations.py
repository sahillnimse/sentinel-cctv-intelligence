"""Government database integration API.

One place to see which authorities the platform can query, and to query them.
Reads fan out across every connector that has a view of the subject, so an
investigator gets one answer per authority rather than having to know which
system holds what.
"""

from fastapi import APIRouter, HTTPException

from .. import integrations

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
def list_connectors():
    return integrations.describe()


@router.get("/vehicle/{plate}")
def vehicle(plate: str):
    """Every authority's view of one vehicle."""
    results = integrations.lookup_vehicle(plate)
    return {
        "subject": plate,
        "kind": "vehicle",
        "results": results,
        "alerts": [a for r in results for a in r.get("alerts", [])],
        "hits": sum(1 for r in results if r.get("found")),
    }


@router.get("/person/{reference}")
def person(reference: str):
    """Every authority's view of one person.

    `reference` is a person identifier or watchlist label, never a raw
    biometric. A face match is a lead for human review; it is not an
    identification and does not by itself authorise a biometric submission.
    """
    results = integrations.lookup_person(reference)
    return {
        "subject": reference,
        "kind": "person",
        "results": results,
        "alerts": [a for r in results for a in r.get("alerts", [])],
        "hits": sum(1 for r in results if r.get("found")),
    }


@router.get("/{key}/vehicle/{plate}")
def one_vehicle(key: str, plate: str):
    c = integrations.get(key)
    if c is None:
        raise HTTPException(404, f"No connector '{key}'")
    result = c.lookup_vehicle(plate)
    if result is None:
        raise HTTPException(400, f"{key} has no view of vehicles")
    return result.as_dict()


@router.get("/{key}/person/{reference}")
def one_person(key: str, reference: str):
    c = integrations.get(key)
    if c is None:
        raise HTTPException(404, f"No connector '{key}'")
    result = c.lookup_person(reference)
    if result is None:
        raise HTTPException(400, f"{key} has no view of people")
    return result.as_dict()
