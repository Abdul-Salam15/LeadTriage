"""
PHASE 6: CLUSTERING (Grouping Similar Leads)

Group qualified leads by similarity patterns to reduce LLM calls.

Feature vector per lead (from Phase 5 outputs):
  1. Company size category        [0=Solo,1=Small,2=Growing,3=Established,4=Enterprise]
  2. Budget category              [0=Micro,1=Small,2=Mid,3=Upper,4=Large]
  3. Use case patterns            (use case presence vector)
  4. Industry/company type        [0=Agency,1=Service,2=Tech,3=Other]
  5. Buying stage                 [0=Early,1=Exploration,2=Active,3=Ready]
  6. Intelligence score           [0-1]
  7. Decision authority           [0-1]

Method: K-Means with cosine similarity (pure Python, no heavy deps).
Target cluster count scales with dataset size.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

COMPANY_SIZE_ENCODING = {
    "Solo/Very Small": 0,
    "Small Team": 1,
    "Growing Company": 2,
    "Established Company": 3,
    "Large Company": 4,
    "Enterprise": 4,
}

BUDGET_CATEGORY_ENCODING = {
    "MICRO": 0,
    "SMALL": 1,
    "MID_MARKET": 2,
    "UPPER_MID_MARKET": 3,
    "LARGE": 4,
    "ENTERPRISE": 4,
}

INDUSTRY_ENCODING = {
    "Agency": 0,
    "Service": 1,
    "Tech": 2,
    "Other": 3,
}

BUYING_STAGE_ENCODING = {"EARLY": 0, "EXPLORATION": 1, "ACTIVE_EVALUATION": 2, "READY_TO_BUY": 3}

# All known use-case names (for one-hot use case vector).
USE_CASE_VOCABULARY = [
    "Lead Routing",
    "Follow-up Automation",
    "Lead Enrichment",
    "Reporting",
    "CRM Sync",
    "Lead Qualification",
    "Inbox Triage",
    "Call Summaries",
    "Research & Outreach",
    "Ad Budget Pacing",
    "Copy-Paste Automation",
    "Chatbot",
]


def _industry_encoding(company_type) -> int:
    ct = str(company_type or "").lower()
    if "agency" in ct or "consult" in ct or "service" in ct:
        return INDUSTRY_ENCODING["Agency"]
    if "tech" in ct or "saas" in ct or "software" in ct:
        return INDUSTRY_ENCODING["Tech"]
    if ct in ("", "none", "null"):
        return INDUSTRY_ENCODING["Other"]
    return INDUSTRY_ENCODING["Other"]


def build_feature_vector(lead_intel: dict) -> list[float]:
    """Build the numeric feature vector for one lead from its intelligence features."""
    cleaned = lead_intel.get("cleaned_data") or {}

    company_size_cat = cleaned.get("employee_size_category") or "Unknown"
    budget_cat = (lead_intel.get("intelligence_features", {})
                  .get("budget_signals", {}).get("budget_category") or "MISSING_BUDGET")

    use_cases = lead_intel.get("intelligence_features", {}) \
        .get("use_case_signals", {}).get("extracted_use_cases") or []
    use_cases = {str(uc) for uc in use_cases}

    company_type = (cleaned.get("notes_analysis") or {}).get("extracted_company_type")
    buying_stage = (lead_intel.get("intelligence_features", {})
                    .get("competitive_position_signals", {}).get("buying_stage") or "EARLY")
    intel_score = (lead_intel.get("intelligence_features", {})
                   .get("combined_intelligence", {}).get("combined_intelligence_score") or 0.0)
    authority = (lead_intel.get("intelligence_features", {})
                 .get("authority_signals", {}).get("combined_authority_score") or 0.4)

    vec = [
        COMPANY_SIZE_ENCODING.get(company_size_cat, 0),
        BUDGET_CATEGORY_ENCODING.get(str(budget_cat).upper(), 0),
    ]
    vec += [1.0 if uc in use_cases else 0.0 for uc in USE_CASE_VOCABULARY]
    vec += [
        _industry_encoding(company_type),
        BUYING_STAGE_ENCODING.get(buying_stage, 0),
        intel_score,
        authority,
    ]
    return vec


# ---------------------------------------------------------------------------
# Vector math (pure Python)
# ---------------------------------------------------------------------------

def _magnitude(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec)) or 1e-9


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (_magnitude(a) * _magnitude(b))


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    if n == 0:
        return []
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


# ---------------------------------------------------------------------------
# K-Means (cosine-based) implementation
# ---------------------------------------------------------------------------

def _assign_to_centroids(vectors, centroids) -> list[int]:
    """Assign each vector to its nearest centroid by cosine similarity."""
    assignments = []
    for v in vectors:
        best_idx, best_sim = 0, -1.0
        for idx, c in enumerate(centroids):
            sim = cosine_similarity(v, c)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
        assignments.append(best_idx)
    return assignments


def kmeans_cosine(vectors: list[list[float]], k: int, max_iter: int = 50, seed: int = 42) -> tuple[list[int], list[list[float]]]:
    """Pure-Python k-means using cosine similarity. Returns (assignments, centroids)."""
    n = len(vectors)
    if n == 0:
        return [], []
    k = max(1, min(k, n))

    rng = random.Random(seed)
    centroids = [list(vectors[rng.randrange(n)]) for _ in range(k)]

    assignments = [0] * n
    for _ in range(max_iter):
        new_assignments = _assign_to_centroids(vectors, centroids)
        if new_assignments == assignments:
            break
        assignments = new_assignments

        # Recompute centroids.
        groups: dict[int, list[list[float]]] = defaultdict(list)
        for v, a in zip(vectors, assignments):
            groups[a].append(v)
        for idx in range(k):
            if groups[idx]:
                centroids[idx] = _mean_vector(groups[idx])
            else:
                # Re-seed empty centroid from a random vector.
                centroids[idx] = list(vectors[rng.randrange(n)])

    return assignments, centroids


def _suggested_k(n_leads: int) -> int:
    """Target 15-25 clusters for ~40 leads; scale down for smaller sets."""
    if n_leads <= 3:
        return 1
    k = min(max(1, round(n_leads * 0.5)), min(25, max(2, n_leads // 2)))
    # Ensure at most ~half the leads become clusters but at least 2.
    k = max(2, min(k, max(2, n_leads // 2)))
    return max(1, min(k, n_leads))


# ---------------------------------------------------------------------------
# Cluster summary generation
# ---------------------------------------------------------------------------

def _representative_ids(lead_ids: list[str], vectors: list[list[float]], centroid: list[float], limit: int = 3) -> list[str]:
    """Pick leads closest to the centroid as representatives."""
    sims = sorted(
        ((cosine_similarity(v, centroid), lid) for v, lid in zip(vectors, lead_ids)),
        key=lambda t: -t[0],
    )
    seen: set[str] = set()
    result: list[str] = []
    for _, lid in sims:
        if lid not in seen:
            seen.add(lid)
            result.append(lid)
            if len(result) >= limit:
                break
    return result


def _size_range(category: str) -> str:
    return {
        "Solo/Very Small": "1-5 people",
        "Small Team": "6-20 people",
        "Growing Company": "21-50 people",
        "Established Company": "51-100 people",
        "Large Company": "100-500 people",
        "Enterprise": "500+ people",
    }.get(category, "Unknown")


def generate_cluster_name(members: list[dict]) -> str:
    """Generate a descriptive cluster label from member characteristics."""
    budget_cats = set()
    use_cases: list[str] = []
    stages = set()
    company_types = set()

    for m in members:
        intel = m.get("intelligence_features", {})
        cleaned = m.get("cleaned_data") or {}
        budget_cats.add(intel.get("budget_signals", {}).get("budget_category"))
        use_cases += intel.get("use_case_signals", {}).get("extracted_use_cases") or []
        stages.add(intel.get("competitive_position_signals", {}).get("buying_stage"))
        company_types.add((cleaned.get("notes_analysis") or {}).get("extracted_company_type"))

    use_case_counter = defaultdict(int)
    for uc in use_cases:
        use_case_counter[str(uc)] += 1
    top_use_case = max(use_case_counter.items(), key=lambda t: t[1])[0] if use_case_counter else "Automation"

    if "READY_TO_BUY" in stages or "ACTIVE_EVALUATION" in stages:
        intent = "High-Intent"
    elif "EXPLORATION" in stages:
        intent = "Exploring"
    else:
        intent = "Early-Stage"

    if any("AGENCY" in str(b).upper() or "MID" in str(b).upper() for b in budget_cats if b):
        budget_tag = "Mid-Market"
    elif any("UPPER" in str(b).upper() for b in budget_cats if b):
        budget_tag = "Upper Mid-Market"
    else:
        budget_tag = "Budget-Variable"

    company_tag = "Agencies" if any("agency" in str(c).lower() for c in company_types) else "Companies"

    return f"{intent} {budget_tag} {company_tag} ({top_use_case})"


def build_cluster_object(cluster_id: str, members: list[dict]) -> dict:
    """Build the MD-format cluster object with characteristics and summaries."""
    vectors = [build_feature_vector(m) for m in members]
    centroid = _mean_vector(vectors)

    lead_ids = [m.get("lead_id") for m in members]
    names = [(m.get("cleaned_data") or {}).get("name") for m in members]

    intel_scores = [m.get("intelligence_features", {}).get("combined_intelligence", {}).get("combined_intelligence_score", 0) for m in members]
    budget_scores = [m.get("intelligence_features", {}).get("budget_signals", {}).get("budget_seriousness_score", 0) for m in members]
    timeline_scores = [m.get("intelligence_features", {}).get("timeline_signals", {}).get("combined_timeline_score", 0) for m in members]
    authority_scores = [m.get("intelligence_features", {}).get("authority_signals", {}).get("combined_authority_score", 0) for m in members]

    size_cats = {(m.get("cleaned_data") or {}).get("employee_size_category") for m in members}
    sizes = [_size_range(c) for c in size_cats if c]

    use_cases: list[str] = []
    for m in members:
        use_cases += m.get("intelligence_features", {}).get("use_case_signals", {}).get("extracted_use_cases") or []
    use_case_counter = defaultdict(int)
    for uc in use_cases:
        use_case_counter[str(uc)] += 1
    top_use_cases = [uc for uc, _ in sorted(use_case_counter.items(), key=lambda t: -t[1])]

    # Signals summary from notes analysis.
    signals_summary: list[str] = []
    all_signals = set()
    for m in members:
        for s in (m.get("cleaned_data") or {}).get("notes_analysis", {}).get("extracted_signals", []):
            all_signals.add(str(s))
    for sig in ["budget_approved", "timeline_urgent", "timeline_asap", "comparing_options"]:
        if sig in all_signals:
            signals_summary.append(sig.replace("_", " ").capitalize())

    stages = {(m.get("intelligence_features", {}).get("competitive_position_signals", {}).get("buying_stage")) for m in members}
    urgency = "URGENT" if "READY_TO_BUY" in stages else ("ACTIVE" if "ACTIVE_EVALUATION" in stages else "EXPLORING")

    def _avg(vals):
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return {
        "cluster_id": cluster_id,
        "cluster_name": generate_cluster_name(members),
        "lead_count": len(members),
        "member_lead_ids": lead_ids,
        "representative_lead_ids": _representative_ids(lead_ids, vectors, centroid, limit=3),
        "member_names": names,
        "characteristics": {
            "company_size_range": " to ".join(sorted(sizes)) if sizes else "Unknown",
            "primary_company_type": "Agencies" if any("agency" in str((m.get("cleaned_data") or {}).get("notes_analysis", {}).get("extracted_company_type")).lower() for m in members) else "Companies",
            "primary_use_case": top_use_cases[0] if top_use_cases else "General automation",
            "decision_authority": f"HIGH ({authority_scores and 'Owner/VP/Head'})" if _avg(authority_scores) >= 0.7 else "MEDIUM to HIGH",
            "evaluation_stage": sorted(str(s) for s in stages if s),
            "urgency": urgency,
        },
        "cluster_signals_summary": signals_summary,
        "avg_intelligence_score": _avg(intel_scores),
        "avg_budget_score": _avg(budget_scores),
        "avg_timeline_score": _avg(timeline_scores),
        "avg_authority_score": _avg(authority_scores),
    }


# ---------------------------------------------------------------------------
# Top-level clustering entry
# ---------------------------------------------------------------------------

def cluster_leads(qualified_leads: list[dict], k: int | None = None) -> dict:
    """
    Cluster qualified leads. `qualified_leads` must already have
    `intelligence_features` attached (run Phase 5 first).

    Returns:
      {
        "clusters": [ {cluster object}, ... ],
        "k": int,
        "assignments": { lead_id: cluster_id },
      }
    """
    n = len(qualified_leads)
    if n == 0:
        return {"clusters": [], "k": 0, "assignments": {}}

    vectors = [build_feature_vector(m) for m in qualified_leads]
    k = k or _suggested_k(n)
    assignments, centroids = kmeans_cosine(vectors, k)

    groups: dict[int, list[dict]] = defaultdict(list)
    for m, a in zip(qualified_leads, assignments):
        groups[a].append(m)

    clusters = []
    assignment_map: dict[str, str] = {}
    for idx in sorted(groups):
        members = groups[idx]
        cluster_id = f"cluster_{idx + 1:03d}"
        for m in members:
            assignment_map[m.get("lead_id")] = cluster_id
        clusters.append(build_cluster_object(cluster_id, members))

    # Sort clusters by avg intelligence score descending, then re-number so
    # cluster_001 = highest-scoring cluster, cluster_002 = second, etc.
    # This keeps the display order (by score) aligned with the cluster ids.
    clusters.sort(key=lambda c: -c["avg_intelligence_score"])

    final_assignments = {}
    for i, c in enumerate(clusters, 1):
        c["cluster_id"] = f"cluster_{i:03d}"
        for lid in c["member_lead_ids"]:
            final_assignments[lid] = c["cluster_id"]

    return {"clusters": clusters, "k": k, "assignments": final_assignments}
