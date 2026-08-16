"""
PHASE 3.1: LEAD ID STANDARDIZATION

Input examples:
  "L-1369" -> "L-1369" [UNIQUE]
  "1341"   -> "L-1341" [UNIQUE]
  "L-1205-dup" -> "L-1205" [DUPLICATE]
  "1137"   -> "L-1137" [UNIQUE]
  ""       -> [MISSING_LEAD_ID]

Storage:
{
  "lead_id": "L-1369",
  "lead_id_original": "L-1369",
  "lead_id_is_duplicate": false,
  "lead_id_data_quality": "EXACT"
}
"""

from __future__ import annotations

import re

PREFIX_PATTERN = re.compile(r"^(?:\s*)(?:L-|#|ID-|LEAD-|lead_?[-_]?)(.*)$", re.IGNORECASE)
DUPLICATE_MARKERS = re.compile(
    r"[-_\s]*(?:dup(?:licate)?|\(duplicate\)|\[duplicate\]|_copy|copy)", re.IGNORECASE
)
NUMERIC = re.compile(r"\d+")


def _detect_duplicate(raw: str) -> bool:
    return bool(DUPLICATE_MARKERS.search(raw))


def clean_lead_id(raw, seen_ids: set | None = None) -> dict:
    """Standardize a lead id. `seen_ids` (set of normalized ids) flags duplicates."""
    original = "" if raw is None else str(raw).strip()

    if original == "":
        return {
            "lead_id": None,
            "lead_id_original": "",
            "lead_id_is_duplicate": False,
            "lead_id_data_quality": "MISSING",
            "lead_id_flag": "MISSING_LEAD_ID",
        }

    # Detect duplicate marker in the original before we strip it.
    is_dup_marker = _detect_duplicate(original)

    # Remove duplicate suffix.
    without_dup = DUPLICATE_MARKERS.sub("", original).strip()

    # Remove prefix.
    match = PREFIX_PATTERN.match(without_dup)
    number_part = match.group(1).strip() if match else without_dup.strip()

    # Extract digits (handles "L-1205", "1341", "LEAD-1137", etc.)
    digits = "".join(NUMERIC.findall(number_part))

    if not digits:
        return {
            "lead_id": None,
            "lead_id_original": original,
            "lead_id_is_duplicate": is_dup_marker,
            "lead_id_data_quality": "INVALID",
            "lead_id_flag": "INVALID_LEAD_ID",
        }

    normalized = f"L-{int(digits)}"

    # Duplicate within the file (same id seen twice) also flags duplicate.
    is_duplicate = is_dup_marker
    if seen_ids is not None:
        if normalized in seen_ids:
            is_duplicate = True
        else:
            seen_ids.add(normalized)

    # Heuristic quality: exact digit-only input is "EXACT", prefixed is "NORMALIZED".
    if original == digits or original == number_part:
        quality = "EXACT"
    else:
        quality = "NORMALIZED"

    return {
        "lead_id": normalized,
        "lead_id_original": original,
        "lead_id_is_duplicate": is_duplicate,
        "lead_id_data_quality": quality,
        "lead_id_flag": "DUPLICATE" if is_duplicate else None,
    }
