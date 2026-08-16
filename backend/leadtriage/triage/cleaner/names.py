"""
PHASE 3.3: NAME STANDARDIZATION

Input examples:
  "Gbenga"      -> "Gbenga"
  "Lola W."     -> "Lola"
  "josh"        -> "Josh"
  "john smith"  -> "John"
  ""            -> [MISSING_NAME]

Process:
  1. Strip whitespace
  2. Extract first name (if full name with spaces)
  3. Title case
  4. Remove middle initials / suffixes
  5. Remove prefixes (Mr., Ms., Dr., Prof.)
  6. Flag missing
  7. Validate (alphabetic + hyphens/apostrophes)
"""

from __future__ import annotations

import re

PREFIXES = re.compile(r"^(Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Sir|Madam|Mx\.?)\s+", re.IGNORECASE)
VALID_NAME = re.compile(r"^[A-Za-z\u00C0-\u017F'\-\. ]+$")
INITIAL_LIKE = re.compile(r"(?:^|\s)[A-Za-z]\.?\s*$")


def clean_name(raw) -> dict:
    original = "" if raw is None else str(raw).strip()

    if original == "":
        return {
            "name": None,
            "name_original": original,
            "name_data_quality": "MISSING",
            "name_is_missing": True,
            "name_appears_valid": False,
            "name_flag": "MISSING_NAME",
        }

    # Remove common prefixes.
    cleaned = PREFIXES.sub("", original).strip()

    # Take first token as first name.
    first = cleaned.split()[0] if cleaned.split() else cleaned

    # If it's an initial or single letter, try the next token.
    tokens = cleaned.split()
    if len(tokens) > 1 and re.match(r"^[A-Za-z]\.?$", tokens[0]):
        first = tokens[1]

    # Title case: "josh" -> "Josh", "deji" -> "Deji"
    first = first[:1].upper() + first[1:].lower() if first else first

    # Remove stray trailing periods.
    first = first.rstrip(".")

    appears_valid = bool(VALID_NAME.match(first)) and len(first) >= 2

    if not appears_valid:
        return {
            "name": first if first else None,
            "name_original": original,
            "name_data_quality": "INVALID",
            "name_is_missing": False,
            "name_appears_valid": False,
            "name_flag": "INVALID_NAME",
        }

    return {
        "name": first,
        "name_original": original,
        "name_data_quality": "EXACT",
        "name_is_missing": False,
        "name_appears_valid": True,
        "name_flag": None,
    }
