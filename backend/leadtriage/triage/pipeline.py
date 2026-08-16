"""
PIPELINE ORCHESTRATOR

Ties Phases 1-8 together into a single runnable flow for one job:

  Phase 1: Upload & validate (already done in upload_service)
  Phase 2: Column detection (already done in column_detection)
  Phase 3: Data cleaning & standardization (per-row)
  Phase 4: Disqualification layer
  Phase 5: Intelligence features (pre-LLM signals)
  Phase 6: Clustering (group similar qualified leads)
  Phase 7: LLM analysis (cluster representatives)
  Phase 8: Apply cluster insights + individual scoring

This module reads the stored job, applies the confirmed mapping to each
row, cleans every field, runs the disqualifier, and persists results.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from triage.cleaner import (
    clean_budget,
    clean_company,
    clean_date,
    clean_email,
    clean_employees,
    clean_lead_id,
    clean_name,
    clean_notes,
    clean_source,
    clean_title,
    clean_website,
    company_slug,
)
from triage.clustering import cluster_leads
from triage.disqualifier import disqualify_batch
from triage.intelligence import extract_intelligence_batch
from triage.llm_analysis import analyze_clusters
from triage.scoring import apply_cluster_insights, rank_leads, recommended_immediate_outreach, tier_summary
from triage.upload_service import load_job, save_job, update_job, uploaded_path, load_overrides

# Canonical fields a user may override after cleaning (Fix 3).
OVERRIDABLE_FIELDS = {
    "name", "email", "company", "employees", "website", "title", "source",
    "monthly_budget", "notes",
}


@dataclass
class PipelineReport:
    job_id: str
    leads: list = field(default_factory=list)
    qualified: list = field(default_factory=list)
    disqualified: list = field(default_factory=list)
    low_priority: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    column_mapping: dict = field(default_factory=dict)
    clusters: list = field(default_factory=list)
    clustering: dict = field(default_factory=dict)
    llm_calls_made: int = 0
    processing_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "summary": self.summary,
            "column_mapping": self.column_mapping,
            "qualified": self.qualified,
            "disqualified": self.disqualified,
            "low_priority": self.low_priority,
            "clusters": self.clusters,
            "clustering": self.clustering,
            "llm_calls_made": self.llm_calls_made,
            "processing_duration_seconds": self.processing_duration_seconds,
            "leads": self.leads,
        }


# ---------------------------------------------------------------------------
# Field cleaners keyed by canonical column name.
# Every cleaner takes (raw_value, context) and returns a dict.
# ---------------------------------------------------------------------------


def _clean_lead_id(raw, ctx):
    return clean_lead_id(raw, ctx.get("seen_ids"))


def _clean_company(raw, ctx):
    result = clean_company(raw, ctx.get("email_domain"))
    seen = ctx.get("seen_companies")
    company = result.get("company")
    if seen is not None and company:
        slug = company_slug(company)
        if slug in seen:
            result["company_duplicate_of"] = seen[slug]
        else:
            seen[slug] = company
    return result


def _clean_website(raw, ctx):
    return clean_website(raw, ctx.get("email_domain"))


CLEANERS = {
    "lead_id": _clean_lead_id,
    "created_date": lambda raw, ctx: clean_date(raw),
    "name": lambda raw, ctx: clean_name(raw),
    "email": lambda raw, ctx: clean_email(raw),
    "company": _clean_company,
    "employees": lambda raw, ctx: clean_employees(raw),
    "website": _clean_website,
    "title": lambda raw, ctx: clean_title(raw),
    "source": lambda raw, ctx: clean_source(raw),
    "monthly_budget": lambda raw, ctx: clean_budget(raw),
    "notes": lambda raw, ctx: clean_notes(raw),
}

# Canonical fields whose raw value is preserved alongside the cleaned output.
RAW_PRESERVED = {
    "lead_id": "lead_id_original",
    "created_date": "created_date_original",
    "name": "name_original",
    "email": "email_original",
    "company": "company_original",
    "employees": "employees_original",
    "website": "website_original",
    "title": "title_original",
    "source": "source_original",
    "monthly_budget": "budget_monthly_original",
    "notes": "notes_original",
}


def _read_rows(job_id: str) -> tuple[list, dict]:
    """Read the stored CSV and return (rows, metadata)."""
    path = uploaded_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded file for job {job_id} not found.")

    raw = path.read_bytes()
    # Decode using the encoding detected during upload.
    encoding = "utf-8"
    text = raw.decode(encoding, errors="replace")
    text = text.lstrip("\ufeff")

    try:
        import csv as _csv
        dialect = _csv.Sniffer().sniff(text[:65536], delimiters=",;\t")
    except _csv.Error:
        dialect = _csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    headers = [h.strip() for h in rows[0]] if rows else []
    data_rows = rows[1:]
    return data_rows, {"headers": headers, "encoding": encoding}


def _build_row_mapping(confirmed: dict, detected: dict, headers: list[str]) -> dict:
    """
    Build {header: canonical_field} for every column, honoring user overrides.
    Overrides: mapping to "__ignore__" drops the column; "__metadata__"
    keeps it raw under metadata.
    """
    mapping: dict[str, str] = {}
    for m in detected.get("mappings", []):
        header = m.get("header")
        mapped = m.get("mapped_to")
        # User override takes precedence.
        if confirmed and header in confirmed:
            mapped = confirmed[header]
        mapping[header] = mapped
    return mapping


def run_pipeline(job_id: str, use_llm: bool | None = None) -> PipelineReport:
    """Execute Phases 2-8 for an uploaded job and persist the report."""
    import time

    start = time.monotonic()
    job = load_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Job {job_id} not found.")

    detected = (job.mapping or {}).get("detected", {})
    confirmed = (job.mapping or {}).get("confirmed", {})

    data_rows, meta = _read_rows(job_id)
    headers = meta["headers"]
    row_mapping = _build_row_mapping(confirmed, detected, headers)

    # Phase 13: detect canonical fields that have no mapped header at all.
    mapped_canonical = {c for c in row_mapping.values() if c not in ("__ignore__", "__metadata__", None)}
    missing_fields = sorted(set(CLEANERS.keys()) - mapped_canonical)

    # Track seen lead ids (duplicates) and companies (dedup) across rows.
    seen_ids = set()
    seen_companies = {}

    cleaned_leads: list[dict] = []
    for row in data_rows:
        raw_row = dict(zip(headers, row))
        cleaned, context = _clean_row(raw_row, row_mapping, seen_ids, seen_companies)
        cleaned["missing_fields"] = missing_fields
        cleaned_leads.append(cleaned)

    # If no lead_id column was mapped, generate synthetic IDs so every lead
    # has a unique identifier (avoids all representatives collapsing to one).
    has_lead_id = "lead_id" in mapped_canonical
    if not has_lead_id:
        for i, lead in enumerate(cleaned_leads, 1):
            lead["lead_id"] = f"L-{i}"
    else:
        # Also fill in any leads that still have None lead_id (empty source values).
        seq = len(cleaned_leads)
        for i, lead in enumerate(cleaned_leads):
            if not lead.get("lead_id"):
                seq += 1
                lead["lead_id"] = f"L-{seq}"

    # Apply user field overrides (Fix 3) before disqualification so they flow
    # through intelligence extraction, clustering, and scoring.
    overrides_map = load_overrides(job_id)
    for lead in cleaned_leads:
        _apply_overrides(lead, overrides_map.get(lead.get("lead_id"), {}))

    # Phase 4: disqualification.
    result = disqualify_batch(cleaned_leads)
    qualified = result["qualified"]

    # Phase 5: intelligence features for qualified leads.
    update_job(job, status="processing", progress_percent=35, message="Extracting intelligence signals...")
    qualified = extract_intelligence_batch(qualified)

    # Phase 6: clustering.
    update_job(job, status="processing", progress_percent=50, message="Clustering similar leads...")
    clustering = cluster_leads(qualified)
    clusters = clustering["clusters"]

    # Phase 7: LLM analysis per cluster (heuristic fallback if no key).
    update_job(job, status="processing", progress_percent=70, message="Analyzing cluster representatives...")
    clusters = analyze_clusters(clusters, qualified, use_llm=use_llm, job_id=job_id)

    # Estimate OpenAI cost from per-cluster analysis costs (0 for heuristics).
    processing_cost_usd = round(sum(
        (c.get("llm_analysis") or {}).get("analysis_cost_usd") or 0
        for c in clusters
    ), 4)

    # Phase 8: apply insights + score + rank.
    update_job(job, status="processing", progress_percent=85, message="Scoring and ranking leads...")
    qualified = apply_cluster_insights(qualified, clusters, clustering["assignments"])
    qualified = rank_leads(qualified)

    # Phase 9: tier summary.
    tiers = tier_summary(qualified)

    duration = round(time.monotonic() - start, 2)

    report = PipelineReport(
        job_id=job_id,
        leads=cleaned_leads,
        qualified=qualified,
        disqualified=result["disqualified"],
        low_priority=result["low_priority"],
        summary={
            **result["summary"],
            "clusters_created": len(clusters),
            "llm_calls_made": len(clusters),
            "processing_cost_usd": processing_cost_usd,
            "processing_duration_seconds": duration,
            "tier_summary": tiers,
            "recommended_immediate_outreach": recommended_immediate_outreach(qualified),
            "missing_fields": missing_fields,
            "unmapped_columns": [m.get("header") for m in detected.get("mappings", [])
                                 if m.get("mapped_to") in (None, "NO_MATCH")],
        },
        column_mapping=row_mapping,
        clusters=clusters,
        clustering=clustering,
        llm_calls_made=len(clusters),
        processing_duration_seconds=duration,
    )

    job.results = report.to_dict()
    job.status = "completed"
    job.progress_percent = 100
    job.message = f"Processing complete: {len(cleaned_leads)} leads analyzed, {len(clusters)} clusters formed."
    save_job(job)

    return report


def _clean_row(raw_row: dict, row_mapping: dict, seen_ids: set, seen_companies: dict | None = None) -> tuple[dict, dict]:
    """
    Clean a single raw row using the field cleaners.
    Returns (cleaned_data, context).
    """
    if seen_companies is None:
        seen_companies = {}
    # Compute email domain first for cross-field references.
    raw_email = raw_row.get(_header_for(row_mapping, "email")) or ""
    email_domain = None
    if raw_email:
        cleaned_email = clean_email(raw_email)
        email_domain = cleaned_email.get("email_domain")

    context = {"seen_ids": seen_ids, "seen_companies": seen_companies, "email_domain": email_domain}

    cleaned: dict = {}
    metadata: dict = {}

    # Apply each canonical cleaner.
    for header, canonical in row_mapping.items():
        raw_value = raw_row.get(header, "")
        if canonical in ("__ignore__", None):
            continue
        if canonical == "__metadata__":
            metadata[header] = raw_value
            continue

        cleaner_fn = CLEANERS.get(canonical)
        if cleaner_fn is None:
            metadata[header] = raw_value
            continue

        if canonical == "notes":
            notes_result = cleaner_fn(raw_value, context)
            cleaned["notes_analysis"] = notes_result
            cleaned["notes_cleaned"] = notes_result.get("notes", "")
            # Keep raw notes too.
            cleaned["notes_raw"] = raw_value
        else:
            result = cleaner_fn(raw_value, context)
            cleaned.update(result)

    # Cross-field: if company missing, infer from email domain via cleaner output.
    # The company cleaner already handles this when email_domain is in context.

    cleaned["metadata"] = metadata
    return cleaned, context


def _header_for(row_mapping: dict, canonical: str) -> str | None:
    """Find the CSV header that maps to a canonical field."""
    for header, c in row_mapping.items():
        if c == canonical:
            return header
    return None


def _apply_overrides(cleaned: dict, overrides: dict) -> None:
    """
    Apply user field overrides (Fix 3) to a cleaned lead by re-running the
    field cleaner on the override value. Re-running the cleaner keeps derived
    metadata consistent (e.g. budget_category, employee_size_category).
    Overridden fields are flagged with data_quality = "USER_OVERRIDE".
    """
    for field, value in overrides.items():
        if field not in OVERRIDABLE_FIELDS:
            continue
        cleaner_fn = CLEANERS.get(field)
        if cleaner_fn is None:
            continue
        if field == "notes":
            notes_result = cleaner_fn(value, {})
            cleaned["notes_analysis"] = notes_result
            cleaned["notes_cleaned"] = notes_result.get("notes", "")
            cleaned["notes_raw"] = value
            continue
        result = cleaner_fn(value, {})
        for key, val in result.items():
            if key.endswith("_data_quality"):
                result[key] = "USER_OVERRIDE"
        cleaned.update(result)
