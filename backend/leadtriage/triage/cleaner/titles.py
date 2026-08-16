"""
PHASE 3.7: TITLE STANDARDIZATION

Input examples:
  "Head of Ops"  -> OPERATIONAL, authority 0.85 [HIGH]
  "VP Growth"    -> "VP" C-SUITE, 0.85 [HIGH]
  "Student"      -> NOT_DECISION_MAKER, 0.0 [NONE]
  "Developer"    -> INDIVIDUAL_CONTRIBUTOR, 0.30 [LOW]
  "Owner"        -> OWNERSHIP, 0.95 [HIGH]
  "CEO"          -> C-SUITE, 0.95 [HIGH]
  "Recruiter"    -> NOT_RELEVANT, 0.0 [NONE]
  ""             -> UNKNOWN, 0.40

Process:
  1. Strip whitespace
  2. Detect non-professional titles
  3. Standardize C-suite / operational / ownership titles
  4. Estimate decision authority score 0-1
  5. Empty -> UNKNOWN
"""

from __future__ import annotations

import re

NON_DECISION_MAKER = re.compile(
    r"\b(student|intern|apprentice|trainee|recruiter)\b", re.IGNORECASE
)
INDIVIDUAL_CONTRIBUTOR = re.compile(
    r"\b(developer|engineer|analyst|specialist|freelancer|designer|writer|copywriter)\b",
    re.IGNORECASE,
)
NOT_RELEVANT = re.compile(r"\b(recruiter|hr)\b", re.IGNORECASE)

C_SUITE = {
    "ceo": ("CEO", 0.95),
    "chief executive officer": ("CEO", 0.95),
    "cto": ("CTO", 0.95),
    "chief technology officer": ("CTO", 0.95),
    "coo": ("COO", 0.95),
    "chief operating officer": ("COO", 0.95),
    "vp": ("VP", 0.85),
    "vice president": ("VP", 0.85),
    "svp": ("SVP", 0.90),
    "senior vice president": ("SVP", 0.90),
    "chief": ("Chief", 0.95),
}

OWNERSHIP = re.compile(r"\b(owner|co[- ]?owner|founder|co[- ]?founder)\b", re.IGNORECASE)

HEAD_OF = re.compile(r"^(head of|director of|manager|lead|head)\b", re.IGNORECASE)

C_SUITE_PATTERN = re.compile(r"^(ceo|cto|coo|cfo|cmo|vp|svp)\b", re.IGNORECASE)

TITLE_ROLE_WORDS = re.compile(
    r"^(head of ops|vp growth|head of revops|managing director|partner|consultant|"
    r"marketing manager|head of growth|director of ops|founder|owner|ceo|coo|cto|"
    r"vp ops|head of operations|managing partner)$",
    re.IGNORECASE,
)


def decision_authority(title: str) -> tuple[float, str]:
    """Return (score, level) based on a standardized title."""
    lower = title.lower()

    if TITLE_ROLE_WORDS.match(lower):
        # High-authority operational/ownership titles.
        if lower in ("ceo", "coo", "cto", "founder", "owner", "managing director", "managing partner"):
            return 0.95, "HIGH"
        return 0.85, "HIGH"

    if OWNERSHIP.search(lower):
        return 0.95, "HIGH"
    if C_SUITE_PATTERN.match(lower) or lower in C_SUITE:
        return 0.85, "HIGH"
    if HEAD_OF.match(lower):
        return 0.85, "HIGH"
    if "director" in lower:
        return 0.85, "HIGH"
    if re.search(r"\b(senior manager|manager|lead)\b", lower):
        return 0.70, "MEDIUM"
    if NOT_RELEVANT.search(lower):
        return 0.0, "NONE"
    if NON_DECISION_MAKER.search(lower):
        return 0.0, "NONE"
    if INDIVIDUAL_CONTRIBUTOR.search(lower):
        return 0.30, "LOW"
    return 0.40, "UNKNOWN"


def _category_for(title: str) -> str:
    lower = title.lower()
    if NON_DECISION_MAKER.search(lower) or "student" in lower:
        return "NOT_DECISION_MAKER"
    if NOT_RELEVANT.search(lower) and "recruiter" in lower:
        return "NOT_RELEVANT"
    if INDIVIDUAL_CONTRIBUTOR.search(lower):
        return "INDIVIDUAL_CONTRIBUTOR"
    if OWNERSHIP.search(lower):
        return "OWNERSHIP"
    if lower in C_SUITE or C_SUITE_PATTERN.match(lower):
        return "C-SUITE"
    if HEAD_OF.match(lower) or "head of" in lower or "director" in lower:
        return "OPERATIONAL"
    if "manager" in lower or "lead" in lower:
        return "MANAGEMENT"
    if "partner" in lower:
        return "PARTNER"
    return "OTHER"


def standardize_title(raw: str) -> str:
    """Normalize a title: trim, collapse spaces, keep canonical casing."""
    title = " ".join(raw.split())
    lower = title.lower()

    if lower in C_SUITE:
        return C_SUITE[lower][0]

    # "VP Growth" -> "VP", "VP Ops" -> "VP"
    m = re.match(r"^(vp|svp)\b", lower)
    if m:
        return C_SUITE[lower.split()[0]][0]

    if OWNERSHIP.search(lower):
        return "Founder" if "founder" in lower else "Owner"

    # Keep operational titles as-is but title-case.
    if HEAD_OF.match(lower) or "director" in lower or "manager" in lower or "lead" in lower:
        return title[:1].upper() + title[1:]

    return title[:1].upper() + title[1:]


def clean_title(raw) -> dict:
    original = "" if raw is None else str(raw).strip()

    if original == "":
        return {
            "title": None,
            "title_original": original,
            "title_is_missing": True,
            "title_category": "UNKNOWN",
            "title_decision_authority_score": 0.40,
            "title_decision_authority_level": "UNKNOWN",
            "title_is_likely_decision_maker": False,
            "title_flag": "MISSING_TITLE",
        }

    standardized = standardize_title(original)
    category = _category_for(standardized)
    score, level = decision_authority(standardized)
    is_decision_maker = level in ("HIGH", "MEDIUM")

    return {
        "title": standardized,
        "title_original": original,
        "title_is_missing": False,
        "title_category": category,
        "title_decision_authority_score": score,
        "title_decision_authority_level": level,
        "title_is_likely_decision_maker": is_decision_maker,
        "title_flag": None,
    }
