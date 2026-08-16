"""
PHASE 7: COST-OPTIMIZED LLM ANALYSIS

For each cluster, analyze 2-3 representative leads with a single LLM call.
This replaces 40+ individual calls with ~k cluster-level calls.

The module degrades gracefully: if no OPENAI_API_KEY is configured, it
produces deterministic heuristic analyses so the pipeline still works
end-to-end (tests, demos, no-credit scenarios).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from django.conf import settings

from triage.upload_service import load_job, update_job

# Estimated OpenAI cost per cluster analysis for gpt-4o-mini
# (~1.5k tokens in/out). Heuristic analyses cost nothing.
ESTIMATED_COST_PER_CALL = 0.002


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

CLUSTER_ANALYSIS_SYSTEM_PROMPT = (
    "You are an AI analyst for a B2B automation sales team. Analyze the lead(s) "
    "below and provide a structured assessment in valid JSON only. "
    "No markdown, no commentary outside the JSON."
)


def _lead_sample(lead: dict) -> dict:
    cleaned = lead.get("cleaned_data") or lead
    intel = lead.get("intelligence_features", {})
    notes = cleaned.get("notes_analysis") or {}

    budget = cleaned.get("budget_monthly")
    budget_str = (
        f"${int(cleaned.get('budget_min') or budget):,}/mo"
        if cleaned.get("budget_is_range")
        else (f"${int(budget):,}/mo" if budget else "Not disclosed")
    )

    return {
        "Name": cleaned.get("name"),
        "Company": cleaned.get("company"),
        "Company Size": f"{cleaned.get('employees')} people" if cleaned.get("employees") else "Unknown",
        "Title": cleaned.get("title"),
        "Email": cleaned.get("email"),
        "Budget": budget_str,
        "Source": (cleaned.get("source") or "").title(),
        "Notes": notes.get("notes") or cleaned.get("notes_cleaned") or "",
    }


def build_cluster_analysis_prompt(cluster: dict, leads_by_id: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for one cluster."""
    rep_ids = cluster.get("representative_lead_ids", [])[:3]
    rep_leads = [leads_by_id.get(lid) for lid in rep_ids if lid in leads_by_id]

    samples = []
    for i, lead in enumerate(rep_leads, 1):
        samples.append(f"LEAD SAMPLE {i}:\n{json.dumps(_lead_sample(lead), indent=2, default=str)}")

    user_prompt = f"""
Cluster: {cluster.get('cluster_name')}
Member leads: {cluster.get('member_lead_ids')}

{samples and chr(10).join(samples) or 'No representative leads available.'}

TASK: Provide a SINGLE cluster-level assessment (not per-lead) summarizing this group.
Return exactly this JSON structure:

{{
  "overall_assessment": {{
    "intent_level": "HIGH" | "MEDIUM" | "LOW" | "NEGATIVE",
    "intent_confidence": 0.0-1.0,
    "recommended_action": "CONTACT_NOW" | "NURTURE" | "EXPLORE_FURTHER" | "DISQUALIFY",
    "action_urgency": "WITHIN_48_HOURS" | "WITHIN_1_WEEK" | "WITHIN_1_MONTH",
    "estimated_deal_probability": 0.0-1.0,
    "estimated_average_deal_value": "$X,XXX/month"
  }},
  "common_characteristics": {{
    "primary_pain_point": "string",
    "typical_workflow_impact": "string",
    "primary_motivation": "string"
  }},
  "urgency_assessment": {{
    "urgency_level": "URGENT" | "SOON" | "FLEXIBLE" | "LOW",
    "urgency_confidence": 0.0-1.0,
    "decision_timeline_weeks": "X-Y",
    "key_urgency_signals": ["signal1", "signal2"]
  }},
  "fit_assessment": {{
    "overall_fit_score": 0.0-1.0,
    "fit_explanation": "string",
    "ideal_customer_profile_alignment": {{
      "company_size": "MATCH" | "PARTIAL",
      "budget_range": "MATCH" | "PARTIAL",
      "pain_point_fit": "MATCH" | "PARTIAL",
      "timeline_fit": "MATCH" | "PARTIAL"
    }},
    "potential_objections": ["objection1", "objection2"]
  }},
  "conversation_strategy": {{
    "conversation_starters": [
      {{"starter": "string", "example": "string"}}
    ],
    "positioning": "string"
  }},
  "risk_factors": [
    {{"risk": "string", "severity": "HIGH" | "MEDIUM" | "LOW", "mitigation": "string"}}
  ],
  "next_steps": ["step1", "step2"],
  "success_metrics": {{
    "win_rate_for_this_cluster": 0.0-1.0,
    "average_sales_cycle_weeks": number
  }}
}}

Respond in valid JSON format only.
"""
    return CLUSTER_ANALYSIS_SYSTEM_PROMPT, user_prompt.strip()


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Robustly extract a JSON object from LLM output."""
    text = text.strip()
    # Strip markdown fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... last }.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# ---------------------------------------------------------------------------
# Heuristic fallback (no API key / test mode)
# ---------------------------------------------------------------------------

def _heuristic_cluster_analysis(cluster: dict) -> dict:
    """Deterministic analysis used when no LLM is available."""
    avg_intel = cluster.get("avg_intelligence_score", 0.5)
    avg_timeline = cluster.get("avg_timeline_score", 0.5)
    avg_authority = cluster.get("avg_authority_score", 0.5)
    avg_budget = cluster.get("avg_budget_score", 0.5)

    # --- Notes-level boost: scan member leads for strong intent keywords ---
    # Cluster averages compress individual strong leads.  To close the gap
    # with LLM scoring we look at the raw notes of member leads and boost
    # the effective intelligence score when clear purchase-intent language
    # is present.
    _STRONG_NOTES = re.compile(
        r"ready to buy|budget approved|asap|demo next week|need a contract|"
        r"sign me up|let.s go|launching|need.*live by|high priority|"
        r"very interested|eager to|excited to|ready to go|right away|"
        r"need a replacement|system is down",
        re.I,
    )
    _WEAK_NOTES = re.compile(
        r"just browsing|exploring options|research phase|no budget|"
        r"not now|maybe next year|intern|student|competitor|"
        r"checking out your pricing|do not contact",
        re.I,
    )

    member_notes = []
    for lid in cluster.get("member_lead_ids", []):
        # member_lead_ids are lead_id strings; we do not have the full lead
        # objects here, so we fall back to the signals summary.
        pass

    # Use the cluster signals summary as a proxy for individual notes.
    signals_summary = " ".join(cluster.get("cluster_signals_summary", []))
    strong_hits = len(_STRONG_NOTES.findall(signals_summary))
    weak_hits = len(_WEAK_NOTES.findall(signals_summary))

    intel_boost = 0.0
    # Only boost leads that are not already in NEGATIVE territory.
    # A lead with very low intelligence should not be rescued by keyword
    # matching alone -- the underlying data is too weak.
    if avg_intel >= 0.25 and strong_hits > 0 and weak_hits == 0:
        intel_boost = min(0.15, strong_hits * 0.05)
    elif avg_intel >= 0.25 and strong_hits > 0 and weak_hits > 0:
        intel_boost = min(0.05, (strong_hits - weak_hits) * 0.03)

    adjusted_intel = min(1.0, avg_intel + intel_boost)

    # Intent thresholds: lowered from the original 0.70/0.50/0.35 to match
    # LLM scoring density.  The LLM path assigns HIGH freely based on note
    # context; the heuristic path was too conservative with rigid buckets.
    if adjusted_intel >= 0.60:
        intent = "HIGH"
        action = "CONTACT_NOW"
        timeline = "2-4"
        prob = round(min(0.85, 0.50 + 0.50 * adjusted_intel), 2)
        deal_value = "$7,500/month"
    elif adjusted_intel >= 0.40:
        intent = "MEDIUM"
        action = "EXPLORE_FURTHER"
        timeline = "4-8"
        prob = round(min(0.60, 0.25 + 0.50 * adjusted_intel), 2)
        deal_value = "$5,000/month"
    elif adjusted_intel >= 0.25:
        intent = "LOW"
        action = "NURTURE"
        timeline = "8-12"
        prob = round(min(0.30, 0.10 + 0.40 * adjusted_intel), 2)
        deal_value = "$3,500/month"
    else:
        intent = "NEGATIVE"
        action = "NURTURE"
        timeline = "12+"
        prob = 0.08
        deal_value = "$2,000/month"

    # Urgency is a separate axis driven by timeline signal.
    if avg_timeline >= 0.70:
        urgency = "URGENT"
    elif avg_timeline >= 0.50:
        urgency = "SOON"
    elif avg_timeline >= 0.30:
        urgency = "FLEXIBLE"
    else:
        urgency = "LOW"

    # Confidence formula: use adjusted intel and boost when strong notes exist.
    confidence = round(min(0.95, 0.50 + 0.45 * adjusted_intel), 2)
    fit_score = round(min(0.95, 0.35 + 0.55 * adjusted_intel), 2)

    return {
        "analysis_type": "cluster_analysis",
        "cluster_id": cluster.get("cluster_id"),
        "analysis_source": "heuristic",
        "analysis_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_assessment": {
            "cluster_name": cluster.get("cluster_name"),
            "intent_level": intent,
            "intent_confidence": confidence,
            "recommended_action": action,
            "action_urgency": "WITHIN_48_HOURS" if action == "CONTACT_NOW" else "WITHIN_1_WEEK",
            "estimated_deal_probability": prob,
            "estimated_average_deal_value": deal_value,
        },
        "common_characteristics": {
            "primary_pain_point": cluster.get("characteristics", {}).get("primary_use_case", "General automation"),
            "typical_workflow_impact": "Manual processes consuming significant team time that could be automated.",
            "primary_motivation": "Free up team time for higher-value activities.",
        },
        "urgency_assessment": {
            "urgency_level": urgency,
            "urgency_confidence": round(0.5 + 0.4 * avg_timeline, 2),
            "decision_timeline_weeks": timeline,
            "key_urgency_signals": cluster.get("cluster_signals_summary", []),
        },
        "fit_assessment": {
            "overall_fit_score": fit_score,
            "fit_explanation": "Fit derived from budget, timeline, and use-case clarity signals.",
            "ideal_customer_profile_alignment": {
                "company_size": "MATCH" if cluster.get("avg_budget_score", 0) >= 0.5 else "PARTIAL",
                "budget_range": "MATCH" if avg_budget >= 0.5 else "PARTIAL",
                "pain_point_fit": "MATCH",
                "timeline_fit": "MATCH" if avg_timeline >= 0.5 else "PARTIAL",
            },
            "potential_objections": ["Competitive evaluation", "Integration concerns", "Pricing"],
        },
        "conversation_strategy": {
            "conversation_starters": [
                {
                    "starter": "Address their specific pain point",
                    "example": "Your team spends significant time on manual workflows. Our automation cuts that by 80%. What would freeing up that time be worth?",
                },
                {
                    "starter": "Reference their context",
                    "example": "We've automated exactly this for similar teams. Most see results in the first week.",
                },
            ],
            "positioning": "Speed, simplicity, and industry-specific expertise",
        },
        "risk_factors": [
            {"risk": "Competitive evaluation", "severity": "MEDIUM", "mitigation": "Strong demo + case study"},
            {"risk": "Integration concerns", "severity": "MEDIUM", "mitigation": "Proactive integration demo"},
        ],
        "next_steps": [
            "Call decision maker promptly while interest is fresh",
            "Prepare demo aligned to primary use case",
            "Share ROI calculation based on team time savings",
        ],
        "success_metrics": {
            "win_rate_for_this_cluster": prob,
            "average_sales_cycle_weeks": float(re.search(r"\d+", timeline).group()) if re.search(r"\d+", timeline) else None,
        },
    }


# ---------------------------------------------------------------------------
# OpenAI client wrapper
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")


def _get_model() -> str:
    return getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _normalize_per_lead_to_cluster(analysis: dict) -> dict:
    """If the LLM returned per-lead analysis (a 'leads' array) instead of the
    expected cluster-level structure, aggregate into the standard format."""
    leads = analysis.get("leads", [])
    if not leads:
        return analysis

    # Aggregate intent levels.
    intent_map = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NEGATIVE": 0}
    reverse_intent = {v: k for k, v in intent_map.items()}
    intents = [intent_map.get(
        (l.get("intent_level") or {}).get("classification", "MEDIUM"), 2
    ) for l in leads]
    avg_intent_val = sum(intents) / len(intents) if intents else 2
    avg_intent = reverse_intent.get(round(avg_intent_val), "MEDIUM")

    # Aggregate recommended actions.
    actions = [l.get("recommended_action", "EXPLORE_FURTHER") for l in leads]
    action = max(set(actions), key=actions.count)  # most common

    # Aggregate urgency.
    urg_map = {"URGENT": 3, "SOON": 2, "FLEXIBLE": 1, "LOW": 0}
    reverse_urg = {v: k for k, v in urg_map.items()}
    urgencies = [urg_map.get(l.get("urgency_assessment", "SOON"), 2) for l in leads]
    avg_urg = sum(urgencies) / len(urgencies) if urgencies else 2
    urgency = reverse_urg.get(round(avg_urg), "SOON")

    # Aggregate fit scores.
    fits = [l.get("fit_assessment", {}).get("fits", True) for l in leads]
    fit_score = sum(1 for f in fits if f) / len(fits) if fits else 0.8

    # Aggregate pain points.
    pain_points = [l.get("primary_pain_point", "") for l in leads if l.get("primary_pain_point")]
    pain = max(set(pain_points), key=pain_points.count) if pain_points else "Manual processes consuming team time."

    # Aggregate timelines.
    timelines = [l.get("typical_decision_timeline", "2-4 weeks") for l in leads if l.get("typical_decision_timeline")]
    timeline = max(set(timelines), key=timelines.count) if timelines else "2-4"
    timeline_weeks = timeline.replace("weeks", "").strip()

    # Aggregate conversation starters.
    starters = []
    for l in leads:
        for s in (l.get("conversation_starters") or []):
            starters.append({"starter": s, "example": s})
    starters = starters[:3] or [{"starter": "Address pain point", "example": "How can we help?"}]

    # Aggregate risk factors.
    risks = []
    for l in leads:
        rf = l.get("risk_factors", "")
        if isinstance(rf, str) and rf:
            risks.append({"risk": rf, "severity": "MEDIUM", "mitigation": "Proactive outreach"})
        elif isinstance(rf, list):
            risks.extend(rf)
    risks = risks[:3] or [{"risk": "Competitive evaluation", "severity": "MEDIUM", "mitigation": "Strong demo"}]

    # Aggregate next steps.
    all_next = []
    for l in leads:
        ns = l.get("next_steps", "")
        if isinstance(ns, str) and ns:
            all_next.append(ns)
        elif isinstance(ns, list):
            all_next.extend(ns)
    next_steps = all_next[:3] or ["Schedule a discovery call", "Prepare demo aligned to use case"]

    # Build probability and deal value.
    prob = round(fit_score * 0.7 + (0.3 if action == "CONTACT_NOW" else 0.15), 2)
    deal_value = "$7,500/month" if action == "CONTACT_NOW" else "$5,000/month"

    analysis["overall_assessment"] = {
        "intent_level": avg_intent,
        "intent_confidence": round(0.7 + 0.25 * (avg_intent_val / 3), 2),
        "recommended_action": action,
        "action_urgency": "WITHIN_48_HOURS" if action == "CONTACT_NOW" else "WITHIN_1_WEEK",
        "estimated_deal_probability": prob,
        "estimated_average_deal_value": deal_value,
    }
    analysis["common_characteristics"] = {
        "primary_pain_point": pain,
        "typical_workflow_impact": "Manual processes consuming significant team time.",
        "primary_motivation": "Free up team time for higher-value activities.",
    }
    analysis["urgency_assessment"] = {
        "urgency_level": urgency,
        "urgency_confidence": round(0.6 + 0.3 * (avg_urg / 3), 2),
        "decision_timeline_weeks": timeline_weeks,
        "key_urgency_signals": [l.get("primary_pain_point", "") for l in leads[:3] if l.get("primary_pain_point")],
    }
    analysis["fit_assessment"] = {
        "overall_fit_score": round(fit_score, 2),
        "fit_explanation": "Fit derived from per-lead LLM assessments aggregated to cluster level.",
        "ideal_customer_profile_alignment": {
            "company_size": "MATCH" if fit_score >= 0.7 else "PARTIAL",
            "budget_range": "MATCH" if fit_score >= 0.6 else "PARTIAL",
            "pain_point_fit": "MATCH",
            "timeline_fit": "MATCH" if urgency in ("URGENT", "SOON") else "PARTIAL",
        },
        "potential_objections": ["Competitive evaluation", "Integration concerns", "Pricing"],
    }
    analysis["conversation_strategy"] = {
        "conversation_starters": starters,
        "positioning": "Speed, simplicity, and industry-specific expertise",
    }
    analysis["risk_factors"] = risks
    analysis["next_steps"] = next_steps
    analysis["success_metrics"] = {
        "win_rate_for_this_cluster": prob,
        "average_sales_cycle_weeks": float(re.search(r"\d+", timeline_weeks).group()) if re.search(r"\d+", timeline_weeks) else 4,
    }

    # Clean up the per-lead array (not needed at cluster level).
    analysis.pop("leads", None)
    return analysis


def analyze_cluster_with_llm(cluster: dict, leads_by_id: dict, use_llm: bool | None = None) -> dict:
    """
    Analyze one cluster. If `use_llm` is True and an API key exists, call
    OpenAI. Otherwise fall back to the heuristic analysis.
    Each result carries an `analysis_cost_usd` estimate (0 for heuristics).
    """
    if use_llm is None:
        use_llm = bool(_get_api_key())

    if not use_llm:
        analysis = _heuristic_cluster_analysis(cluster)
        analysis["analysis_cost_usd"] = 0.0
        return analysis

    try:
        from openai import OpenAI

        system_prompt, user_prompt = build_cluster_analysis_prompt(cluster, leads_by_id)
        client = OpenAI(api_key=_get_api_key())
        response = client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        analysis = _extract_json(raw)
        analysis["analysis_source"] = "openai"
        analysis["analysis_cost_usd"] = ESTIMATED_COST_PER_CALL
        analysis["cluster_id"] = cluster.get("cluster_id")
        analysis["analysis_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Normalize: if the LLM returned per-lead analysis instead of cluster-level,
        # aggregate into the expected cluster-level structure.
        if "leads" in analysis and "overall_assessment" not in analysis:
            analysis = _normalize_per_lead_to_cluster(analysis)
        return analysis
    except Exception:
        # Fall back to heuristic so the pipeline never hard-fails.
        analysis = _heuristic_cluster_analysis(cluster)
        analysis["analysis_cost_usd"] = 0.0
        return analysis


def analyze_clusters(
    clusters: list[dict],
    qualified_leads: list[dict],
    use_llm: bool | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """
    Run LLM (or heuristic) analysis for every cluster.
    Returns the same clusters with `llm_analysis` attached.
    When `job_id` is given, job progress is updated after each cluster so the
    UI can show a live progress bar (70% -> 85% across all clusters).
    """
    leads_by_id = {l.get("lead_id"): l for l in qualified_leads}
    total = len(clusters)
    job = load_job(job_id) if job_id else None
    for i, cluster in enumerate(clusters, 1):
        cluster["llm_analysis"] = analyze_cluster_with_llm(cluster, leads_by_id, use_llm)
        cluster["analysis_cost_usd"] = cluster["llm_analysis"].get("analysis_cost_usd", 0.0)
        if job is not None and total > 0:
            pct = 70 + int(round(15 * i / total))
            update_job(
                job,
                progress_percent=pct,
                message=f"Analyzing cluster {i}/{total}...",
            )
    return clusters
