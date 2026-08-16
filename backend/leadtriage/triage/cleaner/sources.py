"""
PHASE 3.9: SOURCE STANDARDIZATION

Input examples:
  "webform"    -> [WEBFORM, 0.60]
  "linkedin"   -> [LINKEDIN, 0.80]
  "event"      -> [EVENT, 0.70]
  "referral"   -> [REFERRAL, 0.90]
  "cold reply" -> [COLD_OUTREACH, 0.50]
  ""           -> [UNKNOWN, 0.45]

Process:
  1. Strip whitespace & lowercase
  2. Fuzzy match against known source categories
  3. Assign quality score
  4. Empty -> UNKNOWN (0.45)
"""

from __future__ import annotations

import re

SOURCE_RULES = [
    ("WEBFORM", 0.60, [r"webform", r"web form", r"\bform\b", r"website", r"web"]),
    ("LINKEDIN", 0.80, [r"linkedin", r"\bli\b", r"social", r"twitter", r"facebook"]),
    ("EVENT", 0.70, [r"event", r"conference", r"trade show", r"webinar", r"meetup"]),
    ("REFERRAL", 0.90, [r"referral", r"\brefer\b", r"referred", r"intro", r"referral partner", r"word of mouth"]),
    ("COLD_OUTREACH", 0.50, [r"cold", r"cold email", r"cold call", r"cold reply", r"outreach"]),
]


def classify_source(raw: str) -> tuple[str, float, str]:
    """Return (canonical_source, quality_score, confidence)."""
    original = "" if raw is None else str(raw).strip()
    text = original.lower()

    if text == "":
        return "UNKNOWN", 0.45, "LOW"

    for category, score, patterns in SOURCE_RULES:
        for pat in patterns:
            if re.search(pat, text):
                return category, score, "HIGH"

    return "OTHER", 0.40, "LOW"


def clean_source(raw) -> dict:
    canonical, score, confidence = classify_source(raw)
    original = "" if raw is None else str(raw).strip()

    return {
        "source": canonical,
        "source_original": original,
        "source_quality_score": score,
        "source_confidence": confidence,
        "source_flag": "MISSING_SOURCE" if canonical == "UNKNOWN" else None,
    }
