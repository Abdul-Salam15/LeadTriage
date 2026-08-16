"""
PHASE 8: APPLY CLUSTER INSIGHTS TO ALL LEADS

After LLM analyzes cluster representatives, apply learnings to ALL leads
in each cluster and compute individual final scores.

  Individual_Score = Cluster_Base_Score + Adjustments

Adjustments (per MD):
  ├─ Budget premium/discount      (+5..+15 / -5..-10)
  ├─ Recency bonus                (+10 / +5 / -5)
  ├─ Authority bonus              (+10 / +5 / 0)
  ├─ Notes quality bonus          (+10 / +5 / 0)
  ├─ Price sensitivity penalty    (-15 / -10)
  ├─ Uncertainty penalty          (-15 / -10 / -5)
  └─ Anomaly adjustment           (±10 to ±20)

Final score capped at 100.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Adjustment helpers
# ---------------------------------------------------------------------------

def _cluster_base_score(cluster: dict) -> int:
    """Derive a 0-100 base score for a cluster from its LLM analysis."""
    analysis = cluster.get("llm_analysis", {})
    overall = analysis.get("overall_assessment", {})
    intent = overall.get("intent_level")
    confidence = overall.get("intent_confidence", 0.5)
    prob = overall.get("estimated_deal_probability", 0.5)

    intent_base = {"HIGH": 80, "MEDIUM": 60, "LOW": 40, "NEGATIVE": 20}.get(intent, 50)
    base = intent_base + round((confidence - 0.5) * 20) + round((prob - 0.5) * 10)
    return max(0, min(100, base))


def _budget_adjustment(lead: dict, cluster: dict) -> int:
    budget = (lead.get("cleaned_data") or {}).get("budget_monthly") or 0
    members = cluster.get("member_lead_ids", [])
    if not members:
        return 0
    # Cluster average budget from member intel (approx).
    avg_budget = cluster.get("avg_budget_score", 0.5) * 10000  # rough $10k anchor
    if budget == 0:
        return -10
    if budget > avg_budget * 1.3:
        return 10
    if budget > avg_budget:
        return 5
    if budget < avg_budget * 0.7:
        return -8
    return -3


def _recency_adjustment(lead: dict) -> int:
    days = (lead.get("cleaned_data") or {}).get("days_since_created")
    if days is None:
        return 0
    if days < 7:
        return 10
    if days <= 30:
        return 5
    return -5


def _authority_adjustment(lead: dict) -> int:
    cleaned = lead.get("cleaned_data") or {}
    notes = cleaned.get("notes_analysis") or {}
    notes_text = (notes.get("notes") or cleaned.get("notes_cleaned") or "").lower()

    if re.search(r"i make the call|decision is mine|i sign off|this is my priority", notes_text):
        return 10
    score = cleaned.get("title_decision_authority_score", 0.4)
    if score >= 0.7:
        return 5
    return 0


def _notes_quality_adjustment(lead: dict) -> int:
    quality = (lead.get("intelligence_features", {})
               .get("notes_quality_signals", {}).get("quality_score") or 0)
    if quality >= 0.8:
        return 10
    if quality >= 0.5:
        return 5
    return 0


def _price_sensitivity_adjustment(lead: dict) -> int:
    notes = (lead.get("cleaned_data") or {}).get("notes_analysis") or {}
    notes_text = (notes.get("notes") or (lead.get("cleaned_data") or {}).get("notes_cleaned") or "").lower()
    signals = notes.get("extracted_signals") or []

    if "price_sensitive" in signals or "budget_locked" in signals or re.search(r"price sensitive|budget not locked", notes_text):
        return -15
    if re.search(r"need to see roi|will compare|comparing", notes_text):
        return -10
    return 0


def _uncertainty_adjustment(lead: dict) -> int:
    notes = (lead.get("cleaned_data") or {}).get("notes_analysis") or {}
    notes_text = (notes.get("notes") or (lead.get("cleaned_data") or {}).get("notes_cleaned") or "").lower()

    if re.search(r"not totally sure what we need|not sure what we need", notes_text):
        return -15
    if re.search(r"exploring options|exploring", notes_text):
        return -10
    if re.search(r"comparing a few options|comparing a few|comparing", notes_text):
        return -5
    return 0


def _anomaly_adjustment(lead: dict, cluster: dict) -> int:
    """Larger deviation from cluster average intelligence -> penalty/bonus."""
    lead_intel = (lead.get("intelligence_features", {})
                  .get("combined_intelligence", {}).get("combined_intelligence_score") or 0)
    cluster_avg = cluster.get("avg_intelligence_score", 0.5)
    diff = lead_intel - cluster_avg
    if abs(diff) > 0.25:
        return int(round(diff * 80))
    return 0


# ---------------------------------------------------------------------------
# Per-lead strong-signal override
# ---------------------------------------------------------------------------

import re as _re

_STRONG_INTENT_PATTERNS = [
    _re.compile(r"ready to buy|need a contract|send over contract|contract sent|ready to purchase", _re.I),
    _re.compile(r"budget approved|budget is ready|budget.*approved|approved.*budget", _re.I),
    _re.compile(r"\bASAP\b|as soon as possible|immediately|right away", _re.I),
    _re.compile(r"demo.*next week|schedule.*demo|book.*demo|demo.*today", _re.I),
    _re.compile(r"system is down|need a replacement|need to replace|down.*need", _re.I),
    _re.compile(r"high priority|very interested|eager to|excited to", _re.I),
    _re.compile(r"need.*live by|launching.*need|deploy.*asap", _re.I),
    _re.compile(r"ready to go|let.s go|sign me up|count me in", _re.I),
]

_LOW_INTENT_PATTERNS = [
    _re.compile(r"just browsing|exploring options|research phase|might have budget", _re.I),
    _re.compile(r"no budget|no funds|can.t afford|too expensive|not now|maybe next year", _re.I),
    _re.compile(r"intern|student|class project|research project", _re.I),
    _re.compile(r"competitor|checking out your pricing", _re.I),
    _re.compile(r"wrong number|unsubscribed|remove me|stop emailing", _re.I),
    _re.compile(r"do not contact|don.t contact", _re.I),
]


def _strong_signal_override(lead: dict, cluster_base: int) -> int:
    """Check lead notes for unmistakable high/low intent signals.

    If a lead has strong positive signals, raise its floor so it isn't stuck
    in a LOW cluster.  If it has strong negative signals, lower its ceiling.
    Returns the adjusted base score.
    """
    cleaned = lead.get("cleaned_data") or {}
    notes = (cleaned.get("notes_analysis") or {}).get("notes") or cleaned.get("notes_cleaned") or ""

    strong_high = any(p.search(notes) for p in _STRONG_INTENT_PATTERNS)
    strong_low = any(p.search(notes) for p in _LOW_INTENT_PATTERNS)

    if strong_high and not strong_low:
        # Raise floor: a lead with "ready to buy" should never score below TIER2.
        return max(cluster_base, 70)
    if strong_low and not strong_high:
        # Lower ceiling: a lead with "just browsing" / "intern" should never score above TIER3.
        return min(cluster_base, 60)
    return cluster_base


# ---------------------------------------------------------------------------
# Per-lead scoring
# ---------------------------------------------------------------------------

def score_lead(lead: dict, cluster: dict) -> dict:
    """Compute final score + tier for one lead within its cluster."""
    raw_base = _cluster_base_score(cluster)
    base = _strong_signal_override(lead, raw_base)
    adjustments = {
        "budget_adjustment": _budget_adjustment(lead, cluster),
        "recency_bonus": _recency_adjustment(lead),
        "authority_bonus": _authority_adjustment(lead),
        "notes_quality_bonus": _notes_quality_adjustment(lead),
        "price_sensitivity_penalty": _price_sensitivity_adjustment(lead),
        "uncertainty_penalty": _uncertainty_adjustment(lead),
        "anomaly_adjustment": _anomaly_adjustment(lead, cluster),
    }
    final_score = base + sum(adjustments.values())
    final_score = max(0, min(100, final_score))

    if final_score >= 85:
        tier = "TIER1"
    elif final_score >= 70:
        tier = "TIER2"
    elif final_score >= 55:
        tier = "TIER3"
    elif final_score >= 40:
        tier = "TIER4"
    else:
        tier = "TIER5"

    return {
        "cluster_base_score": raw_base,
        "signal_adjusted_base": base if base != raw_base else None,
        "individual_adjustments": adjustments,
        "final_score": final_score,
        "score_calculation_transparency": f"{base} + ({sum(adjustments.values())}) = {final_score}",
        "tier": tier,
    }


# ---------------------------------------------------------------------------
# Apply insights to all leads
# ---------------------------------------------------------------------------

def apply_cluster_insights(qualified_leads: list[dict], clusters: list[dict], assignments: dict) -> list[dict]:
    """
    Assign each qualified lead to its cluster, inherit insights, and score.
    Mutates and returns the qualified leads list.
    """
    cluster_by_id = {c["cluster_id"]: c for c in clusters}

    for lead in qualified_leads:
        lead_id = lead.get("lead_id")
        cluster_id = assignments.get(lead_id)
        cluster = cluster_by_id.get(cluster_id)

        if cluster is None:
            # Fallback: single "orphan" cluster object.
            cluster = {
                "cluster_id": "cluster_000",
                "cluster_name": "Ungrouped",
                "member_lead_ids": [lead_id],
                "avg_intelligence_score": (lead.get("intelligence_features", {})
                                           .get("combined_intelligence", {})
                                           .get("combined_intelligence_score") or 0.5),
                "avg_budget_score": 0.5,
                "avg_timeline_score": 0.5,
                "avg_authority_score": 0.5,
                "llm_analysis": None,
            }

        llm = cluster.get("llm_analysis") or {}
        overall = llm.get("overall_assessment") or {}

        lead["cluster_assignment"] = {
            "cluster_id": cluster_id,
            "cluster_name": cluster.get("cluster_name"),
            "cluster_base_score": _cluster_base_score(cluster),
            "confidence_in_assignment": 0.90,
        }
        lead["scoring"] = score_lead(lead, cluster)
        lead["analysis_summary"] = {
            "intent_level": overall.get("intent_level"),
            "intent_confidence": overall.get("intent_confidence"),
            "primary_pain_point": (llm.get("common_characteristics") or {}).get("primary_pain_point"),
            "urgency": (llm.get("urgency_assessment") or {}).get("urgency_level"),
            "fit_assessment": (llm.get("fit_assessment") or {}).get("fit_explanation"),
            "estimated_deal_probability": overall.get("estimated_deal_probability"),
            "estimated_sales_cycle_weeks": (llm.get("urgency_assessment") or {}).get("decision_timeline_weeks"),
            "recommendation": overall.get("recommended_action"),
        }
        lead["sales_strategy"] = {
            "conversation_starters": [cs.get("example") for cs in (llm.get("conversation_strategy") or {}).get("conversation_starters", [])],
            "key_talking_points": [cs.get("starter") for cs in (llm.get("conversation_strategy") or {}).get("conversation_starters", [])],
            "potential_objections": [r.get("risk") for r in llm.get("risk_factors", [])],
            "next_steps": llm.get("next_steps", []),
        }

    return qualified_leads


def rank_leads(qualified_leads: list[dict]) -> list[dict]:
    """Sort qualified leads by final score descending (ties broken by
    intelligence score then lead_id for a stable, deterministic order)."""
    def _key(lead):
        scoring = lead.get("scoring") or {}
        intel = (lead.get("intelligence_features", {})
                 .get("combined_intelligence", {}).get("combined_intelligence_score") or 0)
        return (-scoring.get("final_score", 0), -intel, lead.get("lead_id") or "")

    scored = sorted(qualified_leads, key=_key)
    for idx, lead in enumerate(scored, 1):
        lead["rank"] = idx
    return scored


# ---------------------------------------------------------------------------
# Phase 9: Ranking & Categorization (tier summary)
# ---------------------------------------------------------------------------

TIER_META = {
    "TIER1": {
        "label": "HOT LEADS",
        "action": "CONTACT WITHIN 48 HOURS",
        "contact_method": "Phone call preferred",
        "time_to_contact": "Within 24-48 hours",
        "priority_level": "HIGHEST",
        "expected_win_rate": "70-80%",
        "expected_sales_cycle": "2-4 weeks",
    },
    "TIER2": {
        "label": "WARM LEADS",
        "action": "CONTACT THIS WEEK",
        "contact_method": "Phone call or email",
        "time_to_contact": "Within 3-5 days",
        "priority_level": "VERY_HIGH",
        "expected_win_rate": "50-60%",
        "expected_sales_cycle": "4-8 weeks",
    },
    "TIER3": {
        "label": "INTERESTED",
        "action": "NURTURE CAMPAIGN",
        "contact_method": "Email nurture sequence",
        "time_to_contact": "Within 1-2 weeks",
        "priority_level": "MEDIUM",
        "expected_win_rate": "30-40%",
        "expected_sales_cycle": "8-12 weeks",
    },
    "TIER4": {
        "label": "EXPLORATORY",
        "action": "MONITOR & REVISIT",
        "contact_method": "Low-touch check-in",
        "time_to_contact": "Within 1 month",
        "priority_level": "LOW",
        "expected_win_rate": "10-20%",
        "expected_sales_cycle": "12+ weeks",
    },
    "TIER5": {
        "label": "LOW PRIORITY",
        "action": "ARCHIVE / EDUCATIONAL TRACK",
        "contact_method": "Mailing list only",
        "time_to_contact": "No active outreach",
        "priority_level": "LOWEST",
        "expected_win_rate": "0-5%",
        "expected_sales_cycle": "Not recommended",
    },
}


def tier_summary(qualified_leads: list[dict]) -> dict:
    """Build the per-tier summary (count, avg score, total pipeline value)."""
    by_tier: dict[str, list[dict]] = {}
    for lead in qualified_leads:
        tier = (lead.get("scoring") or {}).get("tier") or "TIER5"
        by_tier.setdefault(tier, []).append(lead)

    summary = {}
    for tier in ("TIER1", "TIER2", "TIER3", "TIER4", "TIER5"):
        members = by_tier.get(tier, [])
        if not members:
            continue
        scores = [(l.get("scoring") or {}).get("final_score", 0) for l in members]
        budgets = [
            (l.get("cleaned_data") or {}).get("budget_monthly") or 0 for l in members
        ]
        summary[tier] = {
            "count": len(members),
            "avg_score": round(sum(scores) / len(scores), 1),
            "total_pipeline_value_monthly": sum(budgets),
            **TIER_META[tier],
        }
    return summary


def recommended_immediate_outreach(qualified_leads: list[dict]) -> int:
    return sum(1 for l in qualified_leads if (l.get("scoring") or {}).get("tier") == "TIER1")
