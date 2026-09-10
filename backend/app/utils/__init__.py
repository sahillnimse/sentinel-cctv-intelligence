"""Shared small utilities (no app imports — safe to use from anywhere)."""

import re

# userinfo inside any URL: scheme://credentials@host. Matches inside longer
# strings too (e.g. "could not open rtsp://user@host/...").
_CREDENTIALS_RE = re.compile(r"(://)[^/@\s]+@")


def redact_url(url: str | None) -> str | None:
    """Strip credentials from a URL for non-privileged readers.

    ``rtsp://email:pass@host/stream`` -> ``rtsp://***@host/stream``.
    URLs without userinfo pass through unchanged. Works on longer strings
    containing a URL as well. Same shape the frontend already uses for
    display masking, so clients keep working.
    """
    if not url:
        return url
    return _CREDENTIALS_RE.sub(r"\1***@", url)
