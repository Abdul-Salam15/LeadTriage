"""
PHASE 3.4: EMAIL STANDARDIZATION

Input examples:
  "gbenga@luxauto.io"  -> VALID
  ""                   -> [MISSING_EMAIL]
  "tempmail@tempmail.com" -> [DISPOSABLE_EMAIL]
  "john@gmail.com"     -> VALID but personal account

Process:
  1. Strip whitespace + lowercase
  2. Validate format (something@something.tld)
  3. Detect disposable providers
  4. Extract domain
  5. Validate domain format
  6. Detect common typos
  7. Flag missing/invalid
"""

from __future__ import annotations

import re

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMAIN_REGEX = re.compile(r"^[a-z0-9\-]+(\.[a-z0-9\-]+)+$")

# Temporary / disposable email providers.
DISPOSABLE_DOMAINS = {
    "tempmail.com",
    "10minutemail.com",
    "mailinator.com",
    "guerrillamail.com",
    "maildrop.cc",
    "yopmail.com",
    "throwawaymail.com",
    "spam4.me",
    "getnada.com",
    "trashmail.com",
}

# Common typos mapped to corrections.
EMAIL_TYPOS = {
    "gmail.om": "gmail.com",
    "gmail.cm": "gmail.com",
    "gmial.com": "gmail.com",
    "yaho.com": "yahoo.com",
    "yahoo.om": "yahoo.com",
    "hotmail.om": "hotmail.com",
    "outllook.com": "outlook.com",
    "outlook.om": "outlook.com",
    "icloud.om": "icloud.com",
}

# Common personal/free email domains (personal account, not company).
PERSONAL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "live.com",
    "msn.com",
}

# Strings that look like email placeholders / broken addresses.
BROKEN_PLACEHOLDERS = {"weird-email-no-domain", "email", "email address", "@", "n/a"}


def clean_email(raw) -> dict:
    original = "" if raw is None else str(raw).strip()

    if original in BROKEN_PLACEHOLDERS or original == "":
        return {
            "email": None,
            "email_original": original,
            "email_is_valid": False,
            "email_is_missing": True,
            "email_is_disposable": False,
            "email_domain": None,
            "email_is_personal_account": False,
            "email_flag": "MISSING_EMAIL" if original == "" else "INVALID_EMAIL",
        }

    # Normalize "john[at]company.com" style obfuscation.
    normalized = original.replace("[at]", "@").replace("[dot]", ".")

    # Remove markdown link artifacts like "[gbenga@luxauto.io](mailto:...)".
    m = re.match(r"^\[([^\]@]+@[^\]@]+)\]\(mailto:.*\)$", normalized)
    if m:
        normalized = m.group(1)

    normalized = normalized.strip().lower()

    # Correct common typos BEFORE validating (e.g. gmail.om -> gmail.com).
    for typo, fix in EMAIL_TYPOS.items():
        if typo in normalized:
            corrected = normalized.replace(typo, fix)
            if EMAIL_REGEX.match(corrected):
                return _build_result(
                    corrected, original, valid=True, typo_fixed=True
                )

    if not EMAIL_REGEX.match(normalized):
        return {
            "email": None,
            "email_original": original,
            "email_is_valid": False,
            "email_is_missing": False,
            "email_is_disposable": False,
            "email_domain": None,
            "email_is_personal_account": False,
            "email_flag": "INVALID_EMAIL",
        }

    domain = normalized.split("@")[1]
    if not DOMAIN_REGEX.match(domain):
        return {
            "email": None,
            "email_original": original,
            "email_is_valid": False,
            "email_is_missing": False,
            "email_is_disposable": False,
            "email_domain": domain,
            "email_is_personal_account": False,
            "email_flag": "INVALID_DOMAIN",
        }

    is_disposable = domain in DISPOSABLE_DOMAINS
    is_personal = domain in PERSONAL_DOMAINS

    flag = None
    if is_disposable:
        flag = "DISPOSABLE_EMAIL"
    elif is_personal:
        flag = "PERSONAL_ACCOUNT"

    return {
        "email": normalized,
        "email_original": original,
        "email_is_valid": True,
        "email_is_missing": False,
        "email_is_disposable": is_disposable,
        "email_domain": domain,
        "email_is_personal_account": is_personal,
        "email_flag": flag,
    }


def _build_result(email, original, valid, typo_fixed=False) -> dict:
    domain = email.split("@")[1]
    result = {
        "email": email,
        "email_original": original,
        "email_is_valid": valid,
        "email_is_missing": False,
        "email_is_disposable": domain in DISPOSABLE_DOMAINS,
        "email_domain": domain,
        "email_is_personal_account": domain in PERSONAL_DOMAINS,
        "email_flag": "TYPO_FIXED" if typo_fixed else None,
    }
    return result
