"""
PHASE 3.6: EMPLOYEE COUNT STANDARDIZATION

Input examples:
  "20"        -> 20 [EXACT]  -> Small Team
  "26 people" -> 26 [EXACT]  -> Growing Company
  ""          -> [UNKNOWN]
  "35-55"     -> min 35, max 55, midpoint 45 [RANGE]
  "19+"       -> 19 [APPROXIMATE_MIN]
  "~43"       -> 43 [APPROXIMATE]
  "4+"        -> 4 [APPROXIMATE_MIN] -> Very Small

Process:
  1. Extract numeric value(s) via regex
  2. Handle ranges (min/max/midpoint, [RANGE])
  3. Handle approximations (~, approximately) [APPROXIMATE]
  4. Handle minimums (19+) [APPROXIMATE_MIN]
  5. Remove text (people, staff, team)
  6. Validate 1-100,000
  7. Empty -> [UNKNOWN]
  8. Categorize company size
"""

from __future__ import annotations

import re

NUMBERS = re.compile(r"(\d[\d,]*)")


def _extract_numbers(text: str) -> list[int]:
    return [int(n.replace(",", "")) for n in NUMBERS.findall(text)]


def size_category(value: int) -> str:
    if value <= 5:
        return "Solo/Very Small"
    if value <= 20:
        return "Small Team"
    if value <= 50:
        return "Growing Company"
    if value <= 100:
        return "Established Company"
    if value <= 500:
        return "Large Company"
    return "Enterprise"


def clean_employees(raw) -> dict:
    original = "" if raw is None else str(raw).strip()
    text = original.lower()

    if original == "" or original in ("-", "n/a", "none"):
        return {
            "employees": None,
            "employees_original": original,
            "employees_data_quality": "UNKNOWN",
            "employees_is_missing": True,
            "employees_is_range": False,
            "employees_is_approximate": False,
            "employee_size_category": None,
            "employee_size_category_confidence": "NONE",
            "employees_flag": "MISSING_EMPLOYEES",
        }

    numbers = _extract_numbers(text)
    if not numbers:
        return {
            "employees": None,
            "employees_original": original,
            "employees_data_quality": "UNKNOWN",
            "employees_is_missing": False,
            "employees_is_range": False,
            "employees_is_approximate": False,
            "employee_size_category": None,
            "employee_size_category_confidence": "NONE",
            "employees_flag": "UNPARSEABLE_EMPLOYEES",
        }

    is_range = "-" in text and len(numbers) >= 2
    is_approximate = "~" in text or "approx" in text or "approximately" in text
    is_min = text.rstrip().endswith("+")

    if is_range:
        lo, hi = numbers[0], numbers[1]
        midpoint = (lo + hi) // 2
        quality = "RANGE"
        if lo < 1 or hi > 100000:
            quality = "INVALID"
        return {
            "employees": midpoint,
            "employees_min": lo,
            "employees_max": hi,
            "employees_original": original,
            "employees_data_quality": quality,
            "employees_is_missing": False,
            "employees_is_range": True,
            "employees_is_approximate": is_approximate,
            "employee_size_category": size_category(midpoint),
            "employee_size_category_confidence": "MEDIUM",
            "employees_flag": "RANGE",
        }

    value = numbers[0]
    if value < 1 or value > 100000:
        return {
            "employees": None,
            "employees_original": original,
            "employees_data_quality": "INVALID",
            "employees_is_missing": False,
            "employees_is_range": False,
            "employees_is_approximate": is_approximate,
            "employee_size_category": None,
            "employee_size_category_confidence": "NONE",
            "employees_flag": "INVALID_EMPLOYEES",
        }

    flag = None
    if is_min:
        quality = "APPROXIMATE_MIN"
        flag = "APPROXIMATE_MIN"
    elif is_approximate:
        quality = "APPROXIMATE"
        flag = "APPROXIMATE"
    else:
        quality = "EXACT"

    confidence = "HIGH" if quality == "EXACT" else "MEDIUM"

    return {
        "employees": value,
        "employees_original": original,
        "employees_data_quality": quality,
        "employees_is_missing": False,
        "employees_is_range": False,
        "employees_is_approximate": is_approximate or is_min,
        "employee_size_category": size_category(value),
        "employee_size_category_confidence": confidence,
        "employees_flag": flag,
    }
