"""
PHASE 5: INTELLIGENCE FEATURES (Pre-LLM Signals)

Extract structured intelligence features for each QUALIFIED lead without
using an LLM. These features feed clustering (Phase 6), provide context
for LLM analysis (Phase 7), and drive scoring (Phase 8).

Sections (mirrors MD):
  5.1 Budget Signals
  5.2 Timeline Signals
  5.3 Decision Authority Signals
  5.4 Use Case Clarity Signals
  5.5 Competitive Position Signals
  5.6 Company Fit Signals
  5.7 Notes Quality Signals
  5.8 Combined Intelligence Score
"""

from __future__ import annotations

import re

from triage.cleaner.notes import (
    COMPARISON_SIGNALS,
    TIMELINE_SIGNALS,
)

# ---------------------------------------------------------------------------
# 5.1 Budget Signals
# ---------------------------------------------------------------------------

BUDGET_CATEGORY_ENCODING = {
    "MICRO": 0,
    "SMALL": 1,
    "MID_MARKET": 2,
    "UPPER_MID_MARKET": 3,
    "LARGE": 4,
    "ENTERPRISE": 5,
}

BUDGET_CONFIDENCE = {
    "EXACT": "HIGH",
    "RANGE_PROVIDED": "MEDIUM",
    "APPROXIMATE": "MEDIUM",
    "BUDGET_NOT_DISCLOSED": "LOW",
    "BUDGET_VARIABLE": "LOW",
    "MISSING_BUDGET": "NONE",
}


def budget_signals(cleaned: dict, max_budget: float | None = None) -> dict:
    budget = cleaned.get("budget_monthly")
    has_budget = cleaned.get("budget_is_disclosed", False) and budget not in (None, 0, "", "TBD")

    category = cleaned.get("budget_category") or "MISSING_BUDGET"
    category = str(category).upper()

    if max_budget and budget:
        normalized = min(1.0, budget / max_budget)
    else:
        normalized = 0.0 if budget in (None, 0) else 0.5

    return {
        "has_budget_mentioned": bool(has_budget),
        "budget_value": budget,
        "budget_category": category,
        "budget_confidence": BUDGET_CONFIDENCE.get(cleaned.get("budget_data_quality"), "NONE"),
        "budget_seriousness_score": cleaned.get("budget_seriousness_score", 0.3),
        "budget_is_range": cleaned.get("budget_is_range", False),
        "budget_min": cleaned.get("budget_min"),
        "budget_max": cleaned.get("budget_max"),
        "budget_signals_feature_vector": [
            1 if has_budget else 0,
            round(normalized, 4),
            BUDGET_CATEGORY_ENCODING.get(category, 0),
        ],
    }


# ---------------------------------------------------------------------------
# 5.2 Timeline Signals
# ---------------------------------------------------------------------------

TIMELINE_URGENCY_LEVELS = {"URGENT": 0.90, "SOON": 0.65, "FLEXIBLE": 0.40, "UNKNOWN": 0.20}

RECENCY_SCORES = {
    "FRESH": 0.95,
    "RECENT": 0.70,
    "STALE": 0.40,
    "VERY_STALE": 0.10,
}

TIMELINE_KEYWORD_PATTERNS = {
    "ASAP": r"\basap\b|start asap|start immediately",
    "THIS_MONTH": r"this month|this week|within 2 weeks|in the next 2 weeks|start asap",
    "THIS_QUARTER": r"this quarter|q[1-4]\b",
    "DECISION_THIS_MONTH": r"decision this month|decision in about a month",
    "URGENT": r"urgent|priority",
}


def timeline_signals(cleaned: dict) -> dict:
    notes = cleaned.get("notes_analysis") or {}
    signals = notes.get("extracted_signals") or []
    notes_text = (notes.get("notes") or cleaned.get("notes_cleaned") or "").lower()

    # Urgency keywords found.
    urgency_keywords = []
    for keyword, pattern in TIMELINE_KEYWORD_PATTERNS.items():
        if re.search(pattern, notes_text, re.IGNORECASE):
            urgency_keywords.append(keyword)
    # Also include signals from the notes analysis.
    for s in signals:
        if s in TIMELINE_SIGNALS:
            urgency_keywords.append(s)

    # Urgency level.
    if any(k in urgency_keywords for k in ("ASAP", "THIS_MONTH", "URGENT", "DECISION_THIS_MONTH")):
        urgency_level = "URGENT"
    elif "THIS_QUARTER" in urgency_keywords:
        urgency_level = "SOON"
    elif (
        any(k in urgency_keywords for k in ("comparing_options", "exploring_options"))
        or re.search(r"exploring|curious about|not totally sure|comparing a few", notes_text)
    ):
        urgency_level = "FLEXIBLE"
    else:
        urgency_level = "UNKNOWN"

    urgency_score = TIMELINE_URGENCY_LEVELS[urgency_level]

    days_since = cleaned.get("days_since_created")
    recency_category = cleaned.get("recency_category")
    if recency_category == "STALE" and (days_since or 0) > 90:
        recency_category = "VERY_STALE"
    recency_score = RECENCY_SCORES.get(recency_category, 0.20)

    combined = round(0.6 * urgency_score + 0.4 * recency_score, 4)

    return {
        "urgency_keywords_found": sorted(set(urgency_keywords)),
        "timeline_urgency_level": urgency_level,
        "urgency_score": urgency_score,
        "days_since_contact": days_since,
        "recency_score": recency_score,
        "combined_timeline_score": combined,
        "timeline_signals_feature_vector": [urgency_score, recency_score, round(min(1.0, (days_since or 0) / 90.0), 4)],
    }


# ---------------------------------------------------------------------------
# 5.3 Decision Authority Signals
# ---------------------------------------------------------------------------

AUTHORITY_LEVEL_SCORE = {"HIGH": 0.85, "MEDIUM": 0.60, "LOW": 0.35, "NONE": 0.10, "UNKNOWN": 0.40}


def authority_signals(cleaned: dict) -> dict:
    notes = cleaned.get("notes_analysis") or {}
    signals = notes.get("extracted_signals") or []
    notes_text = (notes.get("notes") or cleaned.get("notes_cleaned") or "").lower()

    title_score = cleaned.get("title_decision_authority_score", 0.40)
    title_level = cleaned.get("title_decision_authority_level", "UNKNOWN")

    # Notes mention authority.
    notes_authority = bool(
        any(s in signals for s in ("i_make_the_call", "decision_is_mine", "my_priority"))
        or re.search(r"i make the call|decision is mine|i sign off|this is my priority", notes_text)
    )

    if title_level in ("HIGH", "MEDIUM", "LOW", "NONE"):
        authority_confidence = "HIGH"
    elif title_level == "UNKNOWN":
        authority_confidence = "UNKNOWN"
    else:
        authority_confidence = "LOW"

    combined = round(max(title_score, 0.85 if notes_authority else title_score), 4)
    if notes_authority:
        combined = round(max(combined, AUTHORITY_LEVEL_SCORE.get("HIGH", 0.85)), 4)

    return {
        "title_authority_score": title_score,
        "title_decision_level": title_level,
        "notes_mention_authority": notes_authority,
        "authority_confidence": authority_confidence,
        "combined_authority_score": combined,
        "authority_signals_feature_vector": [title_score, 1 if notes_authority else 0],
    }


# ---------------------------------------------------------------------------
# 5.4 Use Case Clarity Signals
# ---------------------------------------------------------------------------

USE_CASE_SPECIFICITY_ENCODING = {"CRYSTAL_CLEAR": 2, "SOMEWHAT_CLEAR": 1, "VAGUE": 0}


def use_case_clarity_signals(cleaned: dict) -> dict:
    notes = cleaned.get("notes_analysis") or {}
    use_cases = notes.get("extracted_use_cases") or []
    pain_points = notes.get("extracted_pain_points") or []
    tools = notes.get("extracted_tools") or []
    signals = notes.get("extracted_signals") or []

    use_cases_clean = [str(uc) for uc in use_cases]
    pain_clean = [str(p) for p in pain_points]

    # Specificity.
    if len(use_cases_clean) >= 2 and (tools or pain_points):
        specificity = "CRYSTAL_CLEAR"
    elif len(use_cases_clean) >= 1:
        specificity = "SOMEWHAT_CLEAR"
    else:
        specificity = "VAGUE"

    clarity_score = 0.0
    clarity_score += min(0.5, 0.2 * len(use_cases_clean))
    clarity_score += min(0.2, 0.1 * len(pain_clean))
    clarity_score += 0.1 if tools else 0.0
    if "ready_to_buy" in signals or "budget_approved" in signals:
        clarity_score += 0.1
    clarity_score = round(min(1.0, clarity_score + 0.1), 4)

    return {
        "extracted_use_cases": use_cases_clean,
        "extracted_pain_points": pain_clean,
        "use_case_specificity": specificity,
        "clarity_score": clarity_score,
        "use_case_signals_feature_vector": [
            min(3, len(use_cases_clean)),
            min(3, len(pain_clean)),
            USE_CASE_SPECIFICITY_ENCODING.get(specificity, 0),
        ],
    }


# ---------------------------------------------------------------------------
# 5.5 Competitive Position Signals
# ---------------------------------------------------------------------------

BUYING_STAGE_ENCODING = {"EARLY": 0, "EXPLORATION": 1, "ACTIVE_EVALUATION": 2, "READY_TO_BUY": 3}

BUYING_STAGE_MATURITY = {
    "EARLY": 0.20,
    "EXPLORATION": 0.45,
    "ACTIVE_EVALUATION": 0.70,
    "READY_TO_BUY": 0.90,
}


def competitive_position_signals(cleaned: dict) -> dict:
    notes = cleaned.get("notes_analysis") or {}
    signals = notes.get("extracted_signals") or []
    notes_text = (notes.get("notes") or cleaned.get("notes_cleaned") or "").lower()

    if "ready_to_buy" in signals or "budget_approved" in signals:
        stage = "READY_TO_BUY"
    elif "comparing_options" in signals or re.search(r"comparing|evaluating|looking at options", notes_text):
        stage = "ACTIVE_EVALUATION"
    elif "exploring_options" in signals or re.search(r"exploring|curious|not totally sure", notes_text):
        stage = "EXPLORATION"
    else:
        stage = "EARLY"

    maturity = BUYING_STAGE_MATURITY[stage]
    competitive_position_score = round(min(1.0, maturity + 0.1), 4)

    return {
        "buying_stage": stage,
        "evaluation_maturity": maturity,
        "competitive_position_score": competitive_position_score,
        "competitive_position_feature_vector": [BUYING_STAGE_ENCODING[stage], round(maturity, 4)],
    }


# ---------------------------------------------------------------------------
# 5.6 Company Fit Signals
# ---------------------------------------------------------------------------

EMPLOYEE_CATEGORY_ENCODING = {
    "Solo/Very Small": 0,
    "Small Team": 1,
    "Growing Company": 2,
    "Established Company": 3,
    "Large Company": 4,
    "Enterprise": 4,
}

INDUSTRY_FIT = {
    "Influencer Marketing Agency": 0.90,
    "Appointment-Setting Agency": 0.90,
    "Cold Email Agency": 0.90,
    "Media Buying Agency": 0.85,
    "Outbound Agency": 0.90,
    "SEO Agency": 0.85,
    "Performance Marketing Agency": 0.85,
    "Lead Gen Agency": 0.90,
    "Agency": 0.85,
    "SaaS": 0.60,
    "Startup": 0.60,
    "Local/Ecom Business": 0.40,
    "Car Dealership": 0.35,
}


def company_fit_signals(cleaned: dict) -> dict:
    company_type = (cleaned.get("notes_analysis") or {}).get("extracted_company_type")
    company_size = cleaned.get("employees")
    size_category = cleaned.get("employee_size_category") or "Unknown"

    # Budget vs company size fit.
    budget = cleaned.get("budget_monthly")
    if company_size and budget:
        per_employee = budget / company_size
        if per_employee >= 150:
            budget_size_fit = 0.90
        elif per_employee >= 80:
            budget_size_fit = 0.75
        elif per_employee >= 30:
            budget_size_fit = 0.55
        else:
            budget_size_fit = 0.25
    elif budget:
        budget_size_fit = 0.50
    else:
        budget_size_fit = 0.20

    # Industry fit.
    industry_fit = INDUSTRY_FIT.get(company_type, 0.40)

    combined = round(0.5 * budget_size_fit + 0.5 * industry_fit, 4)

    return {
        "company_size": company_size,
        "company_size_category": size_category,
        "budget_size_fit": round(budget_size_fit, 4),
        "company_type": company_type,
        "industry_fit": industry_fit,
        "combined_fit_score": combined,
        "company_fit_feature_vector": [
            round(min(1.0, (company_size or 0) / 500.0), 4),
            round(budget_size_fit, 4),
            industry_fit,
        ],
    }


# ---------------------------------------------------------------------------
# 5.7 Notes Quality Signals
# ---------------------------------------------------------------------------

ENGAGEMENT_ENCODING = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
SPECIFICITY_ENCODING = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
SENTIMENT_ENCODING = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2, "SUSPICIOUS": 0}


def notes_quality_signals(cleaned: dict) -> dict:
    notes = cleaned.get("notes_analysis") or {}
    tools = [str(t) for t in (notes.get("extracted_tools") or [])]
    quality = notes.get("notes_quality_score", 0.0)

    return {
        "word_count": notes.get("notes_length_words", 0),
        "engagement_level": notes.get("notes_engagement_level", "LOW"),
        "specificity": notes.get("notes_specificity", "LOW"),
        "tools_mentioned": tools,
        "sentiment": notes.get("notes_sentiment", "NEUTRAL"),
        "quality_score": quality,
        "notes_quality_feature_vector": [
            round(min(1.0, (notes.get("notes_length_words", 0) or 0) / 60.0), 4),
            ENGAGEMENT_ENCODING.get(notes.get("notes_engagement_level", "LOW"), 0),
            SPECIFICITY_ENCODING.get(notes.get("notes_specificity", "LOW"), 0),
            SENTIMENT_ENCODING.get(notes.get("notes_sentiment", "NEUTRAL"), 1),
        ],
    }


# ---------------------------------------------------------------------------
# 5.8 Combined Intelligence Score
# ---------------------------------------------------------------------------

WEIGHTS = {
    "budget": 0.20,
    "timeline": 0.25,
    "authority": 0.20,
    "use_case": 0.15,
    "competitive": 0.10,
    "company_fit": 0.10,
}


def combined_intelligence_score(signals: dict) -> dict:
    budget_s = signals.get("budget_signals", {})
    timeline_s = signals.get("timeline_signals", {})
    authority_s = signals.get("authority_signals", {})
    use_case_s = signals.get("use_case_signals", {})
    competitive_s = signals.get("competitive_position_signals", {})
    fit_s = signals.get("company_fit_signals", {})

    components = {
        "budget_score": budget_s.get("budget_seriousness_score", 0.3),
        "timeline_score": timeline_s.get("combined_timeline_score", 0.3),
        "authority_score": authority_s.get("combined_authority_score", 0.4),
        "use_case_clarity": use_case_s.get("clarity_score", 0.3),
        "competitive_position": competitive_s.get("competitive_position_score", 0.4),
        "company_fit": fit_s.get("combined_fit_score", 0.4),
    }

    combined = (
        components["budget_score"] * WEIGHTS["budget"]
        + components["timeline_score"] * WEIGHTS["timeline"]
        + components["authority_score"] * WEIGHTS["authority"]
        + components["use_case_clarity"] * WEIGHTS["use_case"]
        + components["competitive_position"] * WEIGHTS["competitive"]
        + components["company_fit"] * WEIGHTS["company_fit"]
    )
    combined = round(min(1.0, combined), 4)

    if combined >= 0.80:
        recommendation = "High Intent Lead - Recommend immediate contact"
    elif combined >= 0.60:
        recommendation = "Medium Intent Lead - Recommend prompt follow-up"
    elif combined >= 0.40:
        recommendation = "Exploring Lead - Nurture with targeted content"
    else:
        recommendation = "Low Intent Lead - Lower priority, monitor"

    return {
        "combined_intelligence_score": combined,
        "intelligence_score_components": components,
        "pre_llm_recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Top-level: extract all signals for one cleaned lead.
# ---------------------------------------------------------------------------

def extract_intelligence(cleaned: dict, max_budget: float | None = None) -> dict:
    signals = {
        "budget_signals": budget_signals(cleaned, max_budget),
        "timeline_signals": timeline_signals(cleaned),
        "authority_signals": authority_signals(cleaned),
        "use_case_signals": use_case_clarity_signals(cleaned),
        "competitive_position_signals": competitive_position_signals(cleaned),
        "company_fit_signals": company_fit_signals(cleaned),
        "notes_quality_signals": notes_quality_signals(cleaned),
    }
    signals["combined_intelligence"] = combined_intelligence_score(signals)
    return signals


def extract_intelligence_batch(qualified_leads: list[dict]) -> list[dict]:
    """Extract intelligence for all qualified leads and attach to each."""
    budgets = [
        (q.get("cleaned_data") or q).get("budget_monthly") for q in qualified_leads
    ]
    budgets = [b for b in budgets if isinstance(b, (int, float)) and b > 0]
    max_budget = max(budgets) if budgets else None

    for lead in qualified_leads:
        cleaned = lead.get("cleaned_data") or lead
        lead["intelligence_features"] = extract_intelligence(cleaned, max_budget)
    return qualified_leads
