"""Indian number-plate normalization and fuzzy matching.

OCR on CCTV footage confuses visually similar characters. We store a
normalized form and compare with a small edit-distance budget so a plate
read as 'GJ01AB1Z34' still matches watchlist entry 'GJ01AB1234'.
"""

import re

# Characters OCR commonly confuses, folded toward digits (Indian plates are
# letter-prefixed but the ambiguous positions are usually in the number part).
AMBIGUOUS = str.maketrans({"O": "0", "Q": "0", "I": "1", "Z": "2", "S": "5", "B": "8"})

PLATE_RE = re.compile(r"[^A-Z0-9]")


def normalize(plate: str) -> str:
    """Uppercase, strip non-alphanumerics. Keeps original letters."""
    return PLATE_RE.sub("", (plate or "").upper())


def fold_ambiguous(plate: str) -> str:
    """Normalized form with confusable letters folded to digits, for matching."""
    return normalize(plate).translate(AMBIGUOUS)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def plates_match(read: str, target: str, max_dist: int = 1) -> bool:
    """Fuzzy match an OCR read against a known plate."""
    a, b = fold_ambiguous(read), fold_ambiguous(target)
    if not a or not b:
        return False
    if abs(len(a) - len(b)) > max_dist:
        return False
    return edit_distance(a, b) <= max_dist


# --- Indian plate format validation & positional coercion -------------------

INDIAN_PLATE_RES = [
    re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$"),  # e.g. GJ01AB1234
    re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$"),          # BH series
]

# OCR confusions, direction-aware: what a char becomes when the format says
# this position must be a letter / digit.
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}


def is_valid_indian(plate: str) -> bool:
    s = normalize(plate)
    return any(rx.match(s) for rx in INDIAN_PLATE_RES)


def coerce_indian(plate: str) -> str | None:
    """Force an OCR read into the Indian format using positional knowledge:
    positions that must be letters get digit->letter substitutions and vice
    versa (0<->O, 1<->I, 8<->B, 5<->S...). Returns the coerced plate or None."""
    s = normalize(plate)
    n = len(s)
    if is_valid_indian(s):
        return s
    if not 8 <= n <= 10:
        return None
    for d in (2, 1):          # district digits
        for letters in (3, 2, 1):  # series letters
            if 2 + d + letters + 4 != n:
                continue
            segments = [s[:2], s[2 : 2 + d], s[2 + d : 2 + d + letters], s[2 + d + letters :]]
            out, ok = [], True
            for seg, want in zip(segments, "LDLD"):
                conv = ""
                for ch in seg:
                    if want == "L":
                        conv += ch if ch.isalpha() else _TO_LETTER.get(ch, "?")
                    else:
                        conv += ch if ch.isdigit() else _TO_DIGIT.get(ch, "?")
                if "?" in conv:
                    ok = False
                    break
                out.append(conv)
            if ok:
                cand = "".join(out)
                if is_valid_indian(cand):
                    return cand
    return None
