"""
PHASE 4: DISQUALIFICATION LAYER (Pre-Clustering)

After cleaning all data, apply business rules to identify and separate
leads that should not go to sales.

Rules (from the MD):
  R1: SPAM or DUPLICATE          -> DISQUALIFIED
  R2: NOT_BUYER or WRONG_FIT     -> DISQUALIFIED
  R3: COMPETITOR                 -> DISQUALIFIED
  R4: authority==0 AND no budget -> LOW_PRIORITY
  R5: VC/portfolio/intro         -> DISQUALIFIED
  R6: academic/research/interview-> DISQUALIFIED

Output statuses: DISQUALIFIED | LOW_PRIORITY | QUALIFIED
"""

from __future__ import annotations

import re

VC_INTRO_PATTERNS = [
    r"\bvc\b",
    r"investor",
    r"portfolio compan",
    r"\bintro(?:duction)?\b",
    r"wanting to intro",
]

ACADEMIC_PATTERNS = [
    r"university project",
    r"\bresearch\b",
    r"journalist",
    r"\binterview\b",
    r"final year student",
    r"can i interview",
]

AUTHORITY_OVERRIDE_PATTERNS = [
    r"i make the call",
    r"decision is mine",
    r"i sign off",
    r"this is my priority",
]


def _notes_text(cleaned: dict) -> str:
    notes = cleaned.get("notes_analysis") or {}
    return notes.get("notes_cleaned") or notes.get("notes") or ""


def evaluate_lead(cleaned_data: dict, notes_analysis: dict | None = None) -> dict:
    """
    Apply the six disqualification rules to a single cleaned lead.

    `cleaned_data` is the Phase 3 output for one lead; `notes_analysis`
    is the 3.11 notes result.
    """
    notes = notes_analysis or cleaned_data.get("notes_analysis") or {}
    flags = set(notes.get("flagged_as", []))
    notes_text = notes.get("notes_cleaned") or notes.get("notes") or ""
    notes_lower = notes_text.lower()

    title_score = cleaned_data.get("title_decision_authority_score", 0.40)
    budget = cleaned_data.get("budget_monthly")

    # R1: Spam or Duplicate
    if "SPAM" in flags or "DUPLICATE" in flags:
        reason = "Spam or duplicate submission"
        if "SPAM" in flags:
            reason = "Spam content"
        return {
            "status": "DISQUALIFIED",
            "disqualification_reason": reason,
            "disqualification_confidence": 0.99,
            "recommendation": "Remove from pipeline",
            "applied_rule": "R1",
        }

    # R3: Competitor (more specific than generic non-buyer)
    if "COMPETITOR" in flags:
        return {
            "status": "DISQUALIFIED",
            "disqualification_reason": "Competitor gathering information",
            "disqualification_confidence": 0.95,
            "recommendation": "Track but do not contact for sales",
            "applied_rule": "R3",
        }

    # R5: VC / Portfolio / Intro (more specific than generic non-buyer)
    if any(re.search(p, notes_lower) for p in VC_INTRO_PATTERNS):
        return {
            "status": "DISQUALIFIED",
            "disqualification_reason": "VC/Portfolio company intro, not direct buyer",
            "disqualification_confidence": 0.90,
            "recommendation": "Track for relationship building, not sales",
            "applied_rule": "R5",
        }

    # R6: Academic / Research / Interview (more specific than generic non-buyer)
    if any(re.search(p, notes_lower) for p in ACADEMIC_PATTERNS):
        return {
            "status": "DISQUALIFIED",
            "disqualification_reason": "Academic/research inquiry, not buyer",
            "disqualification_confidence": 0.90,
            "recommendation": "May want to do interview, not sales",
            "applied_rule": "R6",
        }

    # R2: Explicitly not a buyer / wrong fit
    if "NOT_BUYER" in flags or "WRONG_FIT" in flags:
        return {
            "status": "DISQUALIFIED",
            "disqualification_reason": "Explicitly not a buyer / Wrong audience",
            "disqualification_confidence": 0.95,
            "recommendation": "Remove or add to educational track",
            "applied_rule": "R2",
        }

    # R4: Wrong decision-maker level (authority == 0, no budget, no authority override)
    if title_score == 0 and not budget:
        has_authority_override = any(
            re.search(p, notes_lower) for p in AUTHORITY_OVERRIDE_PATTERNS
        )
        if not has_authority_override:
            return {
                "status": "LOW_PRIORITY",
                "disqualification_reason": "Not decision maker, no budget",
                "disqualification_confidence": 0.85,
                "recommendation": "Nurture for future / Educational track",
                "applied_rule": "R4",
            }

    return {
        "status": "QUALIFIED",
        "disqualification_reason": None,
        "disqualification_confidence": None,
        "recommendation": "Continue to next phases",
        "applied_rule": None,
    }


def disqualify_batch(cleaned_leads: list[dict]) -> dict:
    """
    Run the disqualification layer over all cleaned leads.

    Returns:
      {
        "qualified": [...],
        "disqualified": [...],
        "low_priority": [...],
        "summary": {...}
      }
    """
    qualified, disqualified, low_priority = [], [], []

    for lead in cleaned_leads:
        verdict = evaluate_lead(lead, lead.get("notes_analysis"))
        record = {
            "lead_id": lead.get("lead_id"),
            "status": verdict["status"],
            "disqualification_reason": verdict["disqualification_reason"],
            "disqualification_confidence": verdict["disqualification_confidence"],
            "recommendation": verdict["recommendation"],
            "applied_rule": verdict["applied_rule"],
            "cleaned_data": lead,
        }
        if verdict["status"] == "QUALIFIED":
            qualified.append(record)
        elif verdict["status"] == "LOW_PRIORITY":
            low_priority.append(record)
        else:
            disqualified.append(record)

    return {
        "qualified": qualified,
        "disqualified": disqualified,
        "low_priority": low_priority,
        "summary": {
            "total": len(cleaned_leads),
            "qualified": len(qualified),
            "disqualified": len(disqualified),
            "low_priority": len(low_priority),
        },
    }
