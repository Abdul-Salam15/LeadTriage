"""
PHASE 3.2: DATE STANDARDIZATION

Input examples:
  "06/28/2024"  -> "2024-06-28" [US format]
  "2024-06-08"  -> "2024-06-08" [ISO]
  "Jun 7 2024"  -> "2024-06-07" [Month name]
  "04-06-2024"  -> [AMBIGUOUS]
  "6/1/24"      -> "2024-06-01" [Short]
  "19-06-2024"  -> "2024-06-19" [DD-MM]
  ""            -> [MISSING_DATE]

Resolution:
  - Try formats in order of likelihood
  - Slash-separated => US format (MM/DD/YYYY) by convention
  - Dash-separated  => ambiguous when both MM-DD and DD-MM are valid;
    resolved to DD-MM when day > 12, else flagged ambiguous
  - Validate range (not before 1990, not in the future)
  - Standardize to ISO 8601 (YYYY-MM-DD)
  - Metadata: days_since_created, recency_category

Storage:
{
  "created_date": "2024-06-28",
  "created_date_original": "06/28/2024",
  "created_date_format_detected": "MM/DD/YYYY",
  "created_date_is_ambiguous": false,
  "days_since_created": 48,
  "recency_category": "RECENT",
  "last_contact_date": "2024-06-28",
  "days_since_last_contact": 48
}
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# (regex, format name, ambiguous-flag fn)
# Slash formats are US by convention and never ambiguous.
DATE_PATTERNS = [
    # ISO
    (re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$"), "YYYY-MM-DD", None),
    # Slash -> US
    (re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$"), "MM/DD/YYYY", None),
    (re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2})\s*$"), "M/D/YY", None),
    # Dash -> DD-MM or ambiguous
    (re.compile(r"^\s*(\d{1,2})[-.](\d{1,2})[-.](\d{4})\s*$"), "DD-MM-YYYY", "DASH"),
    (re.compile(r"^\s*(\d{1,2})[-.](\d{1,2})[-.](\d{2})\s*$"), "D-M-YY", "DASH"),
]

MONTH_NAMES = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}
MONTH_NAME_FULL = {
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
}

MIN_YEAR = 1990


def _make_valid_date(year: int, month: int, day: int):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_yy(two: int) -> int:
    return 2000 + two if two < 100 else two


def _parse_iso(text: str) -> date | None:
    """Parse YYYY-MM-DD (also YYYY-M-D)."""
    m = re.match(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$", text)
    if not m:
        return None
    return _make_valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_month_name(text: str) -> tuple[date | None, str | None]:
    """Handle 'Jun 7 2024', '7 Jun 2024', 'June 7, 2024'."""
    m1 = re.match(r"^\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\s*$", text)
    if m1:
        month_str, day, year = m1.group(1).lower(), int(m1.group(2)), int(m1.group(3))
        if month_str in MONTH_NAMES or month_str in MONTH_NAME_FULL:
            month = _month_index(month_str)
            return _make_valid_date(year, month, day), "MMM D YYYY"
    m2 = re.match(r"^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", text)
    if m2:
        day, month_str, year = int(m2.group(1)), m2.group(2).lower(), int(m2.group(3))
        if month_str in MONTH_NAMES or month_str in MONTH_NAME_FULL:
            month = _month_index(month_str)
            return _make_valid_date(year, month, day), "D MMM YYYY"
    return None, None


def _month_index(name: str) -> int:
    all_names = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]
    for i, full in enumerate(all_names, start=1):
        if name in (full, full[:3]):
            return i
    return 0


def _flag_outcome(**kwargs) -> dict:
    base = {
        "created_date": None,
        "created_date_original": kwargs.get("created_date_original", ""),
        "created_date_format_detected": kwargs.get("created_date_format_detected"),
        "created_date_is_ambiguous": kwargs.get("created_date_is_ambiguous", False),
        "created_date_flag": kwargs.get("created_date_flag"),
        "days_since_created": None,
        "recency_category": None,
        "last_contact_date": None,
        "days_since_last_contact": None,
    }
    return base


def parse_date_string(value: str, today: date | None = None) -> dict:
    """
    Parse a raw date string and produce the standard Phase 3.2 output.
    `today` is injectable for deterministic tests.
    """
    original = "" if value is None else str(value).strip()
    today = today or date.today()

    if original == "":
        return _flag_outcome(
            created_date_original=original, created_date_flag="MISSING_DATE"
        )

    # ISO always first.
    iso_parsed = _parse_iso(original)
    if iso_parsed is not None:
        return _build_date_result(
            iso_parsed, original, "YYYY-MM-DD", False, today
        )

    # Month-name forms.
    mn_parsed, mn_fmt = _parse_month_name(original)
    if mn_parsed is not None:
        return _build_date_result(mn_parsed, original, mn_fmt, False, today)

    for pattern, name, ambiguity in DATE_PATTERNS:
        m = pattern.match(original)
        if not m:
            continue
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))

        if name == "MM/DD/YYYY":
            parsed = _make_valid_date(c, a, b)
            if parsed:
                return _build_date_result(parsed, original, name, False, today)
        elif name == "M/D/YY":
            parsed = _make_valid_date(_resolve_yy(c), a, b)
            if parsed:
                return _build_date_result(parsed, original, name, False, today)
        elif name in ("DD-MM-YYYY", "D-M-YY"):
            year = c if name == "DD-MM-YYYY" else _resolve_yy(c)
            as_dd_mm = _make_valid_date(year, b, a)  # day-month-year
            as_mm_dd = _make_valid_date(year, a, b)  # month-day-year

            if as_dd_mm and as_mm_dd and a != b:
                # Both interpretations valid -> ambiguous.
                result = _flag_outcome(
                    created_date_original=original,
                    created_date_format_detected=name,
                    created_date_is_ambiguous=True,
                    created_date_flag="AMBIGUOUS_DATE",
                )
                result["ambiguous_alternatives"] = {
                    "mm_dd_yyyy": as_mm_dd.isoformat(),
                    "dd_mm_yyyy": as_dd_mm.isoformat(),
                }
                return result
            if as_dd_mm:
                return _build_date_result(as_dd_mm, original, name, False, today)
            if as_mm_dd:
                return _build_date_result(as_mm_dd, original, name, False, today)
        continue

    # Fallback: unparsable.
    return _flag_outcome(
        created_date_original=original, created_date_flag="UNPARSABLE_DATE"
    )


def _build_date_result(parsed: date, original: str, fmt: str, ambiguous: bool, today: date) -> dict:
    # Validate range: not before 1990, not in the future (+1 day TZ grace).
    if parsed.year < MIN_YEAR or parsed > today + timedelta(days=1):
        return _flag_outcome(
            created_date_original=original,
            created_date_format_detected=fmt,
            created_date_flag="OUT_OF_RANGE_DATE",
        )

    iso = parsed.isoformat()
    days_since = max(0, (today - parsed).days)
    if days_since <= 7:
        recency = "FRESH"
    elif days_since <= 30:
        recency = "RECENT"
    else:
        recency = "STALE"

    return {
        "created_date": iso,
        "created_date_original": original,
        "created_date_format_detected": fmt,
        "created_date_is_ambiguous": ambiguous,
        "created_date_flag": None,
        "days_since_created": days_since,
        "recency_category": recency,
        "last_contact_date": iso,
        "days_since_last_contact": days_since,
    }


def clean_date(raw, today: date | None = None) -> dict:
    return parse_date_string(raw, today=today)


def get_recency_score(category: str | None) -> float:
    """Recency score used in Phase 5 timeline signals."""
    mapping = {
        "FRESH": 0.95,
        "RECENT": 0.70,
        "STALE": 0.40,
    }
    return mapping.get(category, 0.10)
