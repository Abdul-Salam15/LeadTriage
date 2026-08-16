"""
PHASE 3.8: WEBSITE STANDARDIZATION

Input examples:
  "luxauto.io"            -> "luxauto.io" [VALID]
  "www.luxauto.io"        -> "luxauto.io" [NORMALIZED]
  "http://upshiftloop.agency" -> "upshiftloop.agency" [NORMALIZED]
  ""                      -> [MISSING_WEBSITE]

Process:
  1. Strip whitespace
  2. Remove protocol (http://, https://, ftp://)
  3. Remove "www."
  4. Lowercase
  5. Validate domain format
  6. Flag missing
  7. Cross-check with email domain
"""

from __future__ import annotations

import re

PROTOCOL = re.compile(r"^[a-z]+://", re.IGNORECASE)
WWW = re.compile(r"^www\.", re.IGNORECASE)
DOMAIN_VALID = re.compile(
    r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$"
)

# Strings that are placeholder-ish and should be treated as missing.
PLACEHOLDERS = {"n/a", "none", "na", "-", "website", "www", "http", "https"}


def clean_website(raw, email_domain: str | None = None) -> dict:
    original = "" if raw is None else str(raw).strip()

    if original == "" or original.lower() in PLACEHOLDERS:
        return {
            "website": None,
            "website_original": original,
            "website_is_missing": True,
            "website_is_valid": False,
            "website_matches_email_domain": None,
            "website_flag": "MISSING_WEBSITE",
        }

    normalized = original.strip()
    normalized = PROTOCOL.sub("", normalized).strip()
    normalized = WWW.sub("", normalized).strip()
    normalized = normalized.lower().rstrip("/").strip()

    if not DOMAIN_VALID.match(normalized):
        return {
            "website": None,
            "website_original": original,
            "website_is_missing": False,
            "website_is_valid": False,
            "website_matches_email_domain": None,
            "website_flag": "INVALID_WEBSITE",
        }

    matches_email = None
    if email_domain:
        matches_email = normalized == email_domain.lower()

    return {
        "website": normalized,
        "website_original": original,
        "website_is_missing": False,
        "website_is_valid": True,
        "website_matches_email_domain": matches_email,
        "website_flag": "DOMAIN_MISMATCH" if matches_email is False else None,
    }
