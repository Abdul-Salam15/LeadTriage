"""
PHASE 3.5: COMPANY STANDARDIZATION

Input examples:
  "LuxAuto"      -> "Luxauto" [Normalized]
  "PerformEngine"-> "Performengine"
  "ACME"         -> "Acme"
  "LuxAuto.io"   -> "Luxauto" [Suffix removed]
  "Freelance"    -> [SOLO_OPERATOR]
  "apexsend.co"  -> "Apexsend" [Suffix removed]
  ""             -> [MISSING_COMPANY - infer from email]

Process:
  1. Strip whitespace
  2. Remove common suffixes (.io, .com, .co, Inc., Ltd., LLC, etc.)
  3. Title case
  4. Flag solo operators (Freelance, Individual)
  5. Infer from email domain if missing
  6. Link to email domain
"""

from __future__ import annotations

import re

# URL/domain-ish suffixes.
DOMAIN_SUFFIXES = re.compile(
    r"\.(?:io|com|co|co\.uk|agency|ai|africa|ng|net|org|dev|app|us|xyz|info|biz)$",
    re.IGNORECASE,
)

# Legal suffixes (comma-separated or space-separated).
LEGAL_SUFFIXES = re.compile(
    r"(?:\s*,\s*|\s+)(?:inc\.?|ltd\.?|llc\.?|gmbh|s\.?a\.?|corp\.?|co\b|limited|plc|pte\.?)\s*$",
    re.IGNORECASE,
)

SOLO_OPERATORS = {
    "freelance",
    "freelancer",
    "individual",
    "solo",
    "solo consultant",
    "freelance marketing",
}


def _domain_from(value: str | None) -> str | None:
    """Extract the actual domain from an email address or a bare domain string."""
    if not value:
        return None
    value = value.strip()
    if "@" in value:
        value = value.split("@")[-1].strip()
    value = re.sub(r"^www\.", "", value, flags=re.IGNORECASE)
    if not value or "." not in value:
        return None
    return value.lower()


def _normalize_company(raw: str) -> str:
    value = raw.strip()
    value = DOMAIN_SUFFIXES.sub("", value).strip()
    value = LEGAL_SUFFIXES.sub("", value).strip()
    value = re.sub(r"[_\-.]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def company_slug(value: str | None) -> str | None:
    """Canonical deduplication key: lowercase, separators and suffixes removed.
    'Lux Auto', 'LuxAuto', 'Lux-Auto', 'Lux Auto Inc.' all collapse to 'luxauto'."""
    if not value:
        return None
    value = _normalize_company(value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def clean_company(raw, email_domain: str | None = None) -> dict:
    original = "" if raw is None else str(raw).strip()
    lower = original.lower()

    # Normalize email_domain: caller may pass either the domain or the full email.
    domain_for_company = _domain_from(email_domain)

    is_solo = any(s in lower for s in SOLO_OPERATORS)
    inferred_from = None

    if original == "":
        # Try to infer from email domain.
        if domain_for_company:
            base = domain_for_company.split(".")[0]
            if base and base.lower() not in ("com", "co", "io", "net", "org", "www"):
                normalized = base.title()
                inferred_from = domain_for_company
                return {
                    "company": normalized,
                    "company_slug": company_slug(normalized),
                    "company_original": original,
                    "company_data_quality": "INFERRED",
                    "company_is_missing": False,
                    "company_is_solo_operator": False,
                    "company_inferred_from": inferred_from,
                    "company_email_domain": domain_for_company,
                    "company_flag": "INFERRED_FROM_EMAIL",
                }
        return {
            "company": None,
            "company_slug": None,
            "company_original": original,
            "company_data_quality": "MISSING",
            "company_is_missing": True,
            "company_is_solo_operator": is_solo,
            "company_inferred_from": None,
            "company_email_domain": domain_for_company,
            "company_flag": "MISSING_COMPANY",
        }

    if is_solo:
        return {
            "company": original.title(),
            "company_slug": company_slug(original.title()),
            "company_original": original,
            "company_data_quality": "EXACT",
            "company_is_missing": False,
            "company_is_solo_operator": True,
            "company_inferred_from": None,
            "company_email_domain": domain_for_company,
            "company_flag": "SOLO_OPERATOR",
        }

    normalized = _normalize_company(original)
    looked_like_domain = bool(re.search(r"\.[a-z]{2,}$", original.lower()))

    # Title case.
    normalized = normalized.title()

    # Edge: single lowercase word like "luxauto" stays "Luxauto".
    return {
        "company": normalized,
        "company_slug": company_slug(normalized),
        "company_original": original,
        "company_data_quality": "NORMALIZED" if original != normalized else "EXACT",
        "company_is_missing": False,
        "company_is_solo_operator": False,
        "company_inferred_from": None,
        "company_email_domain": domain_for_company,
        "company_looked_like_domain": looked_like_domain,
        "company_flag": None,
    }
