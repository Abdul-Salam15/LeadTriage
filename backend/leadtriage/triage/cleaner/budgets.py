"""
PHASE 3.10: BUDGET STANDARDIZATION

Input examples:
  "5,000/mo"   -> 5000 [EXACT, MONTHLY] -> Mid Market, seriousness 0.75
  "$6k/mo"     -> 6000 [EXACT, MONTHLY] -> Mid Market, 0.75
  "$6-8k"      -> min 6000, max 8000, avg 7000 [RANGE] -> Mid Market, 0.75
  "0"          -> 0 [EXACT] -> No Budget, 0.2
  "TBD"        -> [BUDGET_NOT_DISCLOSED], 0.4
  ""           -> [MISSING_BUDGET], 0.3
  "500"        -> 500 [EXACT] -> Micro, 0.2
  "18k"        -> 18000 [EXACT] -> Upper Mid Market, 0.85
  "depends"    -> [BUDGET_VARIABLE]

Process:
  1. Extract numeric value + symbols ($, k, M, /)
  2. Convert abbreviations (k -> 1000, M -> 1000000)
  3. Handle ranges (min/max/avg, [RANGE])
  4. Handle approximations (~)
  5. Handle special values (0, TBD, Varies, Depends)
  6. Normalize period (monthly default)
  7. Categorize budget + seriousness score
"""

from __future__ import annotations

import re

BUDGET_NOT_DISCLOSED = {"tbd", "tba", "tbf"}
BUDGET_VARIABLE = {"varies", "depends", "not disclosed", "wont share", "won't share"}

MULTIPLIERS = {"k": 1000, "m": 1000000, "b": 1000000000}


def _parse_single(token: str) -> float | None:
    """Parse a single budget token like '6k', '5000', '$8,000/mo' -> 8000."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([kmb]?)\s*(?:/\s*mo(?:nth)?s?)?", token.lower())
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = m.group(2)
    value = num * MULTIPLIERS.get(mult, 1)
    return value


def budget_category(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value == 0:
        return "NO_BUDGET"
    if value < 1000:
        return "MICRO"
    if value < 5000:
        return "SMALL"
    if value < 10000:
        return "MID_MARKET"
    if value < 20000:
        return "UPPER_MID_MARKET"
    if value < 50000:
        return "LARGE"
    return "ENTERPRISE"


def seriousness_score(value: float | None, category: str) -> float:
    if value is None:
        return 0.3
    if value == 0:
        return 0.2
    mapping = {
        "MICRO": 0.2,
        "SMALL": 0.5,
        "MID_MARKET": 0.75,
        "UPPER_MID_MARKET": 0.85,
        "LARGE": 0.95,
        "ENTERPRISE": 0.95,
    }
    return mapping.get(category, 0.3)


def clean_budget(raw) -> dict:
    original = "" if raw is None else str(raw).strip()
    text = original.lower()

    if text == "":
        return {
            "budget_monthly": None,
            "budget_monthly_original": original,
            "budget_is_range": False,
            "budget_min": None,
            "budget_max": None,
            "budget_is_approximate": False,
            "budget_is_disclosed": False,
            "budget_category": "UNKNOWN",
            "budget_seriousness_score": 0.3,
            "budget_data_quality": "MISSING",
            "budget_flag": "MISSING_BUDGET",
        }

    if text in BUDGET_NOT_DISCLOSED:
        return {
            "budget_monthly": None,
            "budget_monthly_original": original,
            "budget_is_range": False,
            "budget_min": None,
            "budget_max": None,
            "budget_is_approximate": False,
            "budget_is_disclosed": False,
            "budget_category": "NOT_DISCLOSED",
            "budget_seriousness_score": 0.4,
            "budget_data_quality": "NOT_DISCLOSED",
            "budget_flag": "BUDGET_NOT_DISCLOSED",
        }

    if text in BUDGET_VARIABLE or any(v in text for v in BUDGET_VARIABLE):
        return {
            "budget_monthly": None,
            "budget_monthly_original": original,
            "budget_is_range": False,
            "budget_min": None,
            "budget_max": None,
            "budget_is_approximate": False,
            "budget_is_disclosed": False,
            "budget_category": "VARIABLE",
            "budget_seriousness_score": 0.4,
            "budget_data_quality": "VARIABLE",
            "budget_flag": "BUDGET_VARIABLE",
        }

    # Approximate?
    is_approximate = text.startswith("~") or "approx" in text

    # Range detection: "5k-7k", "$6-8k", "8k-12k", "5,000-7,000"
    range_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*([kmb]?)\s*-\s*(\d+(?:[.,]\d+)?)\s*([kmb]?)(\s*/mo)?",
        text,
    )
    if range_match:
        lo_num = float(range_match.group(1).replace(",", ""))
        lo_unit = (range_match.group(2) or range_match.group(4)).lower()
        hi_num = float(range_match.group(3).replace(",", ""))
        hi_unit = range_match.group(4).lower()
        lo = lo_num * MULTIPLIERS.get(lo_unit, 1)
        hi = hi_num * MULTIPLIERS.get(hi_unit, 1)
        avg = (lo + hi) / 2
        category = budget_category(avg)
        return {
            "budget_monthly": avg,
            "budget_monthly_original": original,
            "budget_is_range": True,
            "budget_min": lo,
            "budget_max": hi,
            "budget_is_approximate": is_approximate,
            "budget_is_disclosed": True,
            "budget_category": category,
            "budget_seriousness_score": seriousness_score(avg, category),
            "budget_data_quality": "RANGE",
            "budget_flag": "RANGE_PROVIDED",
        }

    value = _parse_single(original)
    if value is None:
        return {
            "budget_monthly": None,
            "budget_monthly_original": original,
            "budget_is_range": False,
            "budget_min": None,
            "budget_max": None,
            "budget_is_approximate": is_approximate,
            "budget_is_disclosed": False,
            "budget_category": "UNKNOWN",
            "budget_seriousness_score": 0.3,
            "budget_data_quality": "UNPARSEABLE",
            "budget_flag": "UNPARSEABLE_BUDGET",
        }

    category = budget_category(value)
    flag = None
    if value == 0:
        flag = "NO_BUDGET"
    elif is_approximate:
        flag = "APPROXIMATE"

    return {
        "budget_monthly": value,
        "budget_monthly_original": original,
        "budget_is_range": False,
        "budget_min": None,
        "budget_max": None,
        "budget_is_approximate": is_approximate,
        "budget_is_disclosed": True,
        "budget_category": category,
        "budget_seriousness_score": seriousness_score(value, category),
        "budget_data_quality": "EXACT" if not is_approximate else "APPROXIMATE",
        "budget_flag": flag,
    }
