"""
API endpoints for the lead triage system.

Phase 1:
  POST /api/v1/leads/upload  -> upload CSV, get job_id + preview
  GET  /api/v1/jobs/{job_id} -> get processing status / preview / results
"""

import csv
import io
import json

from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from triage import upload_service
from triage.column_detection import MappingSummary, apply_user_mapping, detect_columns
from triage.pipeline import OVERRIDABLE_FIELDS, run_pipeline
from triage.upload_service import (
    UploadValidationError,
    load_job,
    load_lead_statuses,
    load_overrides,
    save_job,
    set_lead_status,
    set_override,
    update_job,
    uploaded_path,
)

TIER_ACTION = {
    "TIER1": "CONTACT_NOW",
    "TIER2": "CONTACT_THIS_WEEK",
    "TIER3": "NURTURE_CAMPAIGN",
    "TIER4": "MONITOR_AND_REVISIT",
    "TIER5": "ARCHIVE_EDUCATIONAL",
}


@api_view(["POST"])
def leads_upload(request):
    """Accept a multipart CSV upload, validate it, and return a job_id + preview."""
    file_object = request.FILES.get("file")
    if file_object is None:
        return Response(
            {"error": "No file provided. Expected multipart field 'file'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Respect Django's per-request upload cap (50MB) as a backstop.
    if file_object.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return Response(
            {"error": f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        preview = upload_service.process_upload(file_object)
    except UploadValidationError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Run Phase 2 column detection immediately and attach to the response.
    summary = detect_columns(preview.job_id, preview.detected_columns)
    job = load_job(preview.job_id)
    job = update_job(job, mapping={"detected": summary.to_dict(), "confirmed": None})

    return Response(
        {
            "job_id": preview.job_id,
            "status": preview.status,
            "message": preview.message,
            "estimated_time_seconds": preview.estimated_time_seconds,
            "preview": {
                "filename": preview.filename,
                "size_bytes": preview.size_bytes,
                "size_mb": round(preview.size_bytes / 1024 / 1024, 2),
                "row_count": preview.row_count,
                "detected_columns": preview.detected_columns,
                "encoding": preview.encoding,
                "sample_rows": preview.sample_rows,
            },
            "column_mapping": summary.to_dict(),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def confirm_mapping(request, job_id):
    """
    Confirm or override the detected column mapping for a job.

    Body: {"mapping": {header: canonical_field | "__ignore__" | "__metadata__"}}
    """
    job = load_job(job_id)
    if job is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    detected = (job.mapping or {}).get("detected")
    if detected is None:
        return Response(
            {"error": "No detected mapping for this job. Re-upload the file."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    body = request.data or {}
    user_mapping = body.get("mapping") or {}
    if not isinstance(user_mapping, dict):
        return Response({"error": "'mapping' must be an object."}, status=status.HTTP_400_BAD_REQUEST)

    summary = MappingSummary.from_dict(detected)
    apply_user_mapping(summary, user_mapping)

    update_job(job, status="mapping_confirmed", progress_percent=15,
               message="Column mapping confirmed.", mapping={"detected": summary.to_dict(), "confirmed": user_mapping})

    return Response(summary.to_dict(), status=status.HTTP_200_OK)


@api_view(["POST"])
def process_job(request, job_id):
    """
    Run the Phase 3 cleaning + Phase 4 disqualification pipeline for a job.
    Requires that the column mapping has been confirmed.

    Body: {"use_llm": true|false}. When false (or key missing), cluster
    analysis falls back to heuristics for a faster, zero-cost run.
    """
    job = load_job(job_id)
    if job is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    if job.status not in ("mapping_confirmed", "completed"):
        return Response(
            {"error": "Column mapping must be confirmed before processing."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    body = request.data or {}
    use_llm = body.get("use_llm")
    if use_llm is not None and not isinstance(use_llm, bool):
        return Response({"error": "'use_llm' must be a boolean."}, status=status.HTTP_400_BAD_REQUEST)

    update_job(job, status="processing", progress_percent=20, message="Cleaning data...")

    try:
        report = run_pipeline(job_id, use_llm=use_llm)
    except FileNotFoundError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

    return Response(report.to_dict(), status=status.HTTP_200_OK)


@api_view(["GET"])
def job_results(request, job_id):
    """Return the full processing report for a completed job."""
    job = load_job(job_id)
    if job is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(job.results, status=status.HTTP_200_OK)


@api_view(["GET"])
def job_detail(request, job_id):
    """Return the current state of a processing job."""
    job = load_job(job_id)
    if job is None:
        return Response(
            {"error": f"Job {job_id} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(job.to_dict())


# ---------------------------------------------------------------------------
# Phase 12 endpoints relevant to Phases 5-8 (leads, clusters, exports)
# ---------------------------------------------------------------------------

def _results_or_404(request, job_id):
    """Fetch results payload or return a 404/400 response."""
    job = load_job(job_id)
    if job is None:
        return None, Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)
    if not job.results:
        return None, Response(
            {"error": "Job has not been processed yet. Confirm mapping and call process first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return job.results, None


def _filter_leads(results: dict, tier: str | None = None, sort: str | None = None):
    leads = list(results.get("qualified") or [])
    if tier:
        leads = [l for l in leads if (l.get("scoring") or {}).get("tier") == tier.upper()]
    if sort == "recency":
        leads = sorted(leads, key=lambda l: (l.get("cleaned_data") or {}).get("days_since_created") or 999)
    elif sort == "budget":
        leads = sorted(leads, key=lambda l: -(l.get("cleaned_data") or {}).get("budget_monthly") or 0)
    else:
        leads = sorted(leads, key=lambda l: (l.get("scoring") or {}).get("final_score", 0), reverse=True)
    return leads


@api_view(["GET"])
def leads_list(request, job_id):
    """List ranked qualified leads for a job with tier/sort/pagination."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err

    tier = request.query_params.get("tier")
    sort = request.query_params.get("sort")
    try:
        limit = int(request.query_params.get("limit", 20))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        limit, offset = 20, 0

    leads = _filter_leads(results, tier, sort)
    total = len(leads)
    page = leads[offset:offset + limit]

    return Response(
        {
            "leads": page,
            "total": total,
            "count": len(page),
            "has_more": offset + len(page) < total,
            "tier": tier,
            "sort": sort,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def lead_detail(request, job_id, lead_id):
    """Return the full detailed analysis for a single qualified lead."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err
    for lead in results.get("qualified") or []:
        if lead.get("lead_id") == lead_id:
            return Response(lead, status=status.HTTP_200_OK)
    return Response({"error": f"Lead {lead_id} not found in qualified results."}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
def lead_statuses(request, job_id):
    """Return the full lead status map for a job (SKIPPED / CONTACTED / QUALIFIED)."""
    if load_job(job_id) is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"statuses": load_lead_statuses(job_id)}, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
def lead_status(request, job_id, lead_id):
    """
    Get or set the action status of a single qualified lead.
    GET  -> {"lead_id": ..., "status": "SKIPPED"|"CONTACTED"|"QUALIFIED"|null}
    POST -> {"status": "SKIPPED"|"CONTACTED"|"QUALIFIED"} (null clears the status)
    """
    if load_job(job_id) is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    results, err = _results_or_404(request, job_id)
    if err:
        return err
    if not any(l.get("lead_id") == lead_id for l in results.get("qualified") or []):
        return Response({"error": f"Lead {lead_id} not found in qualified results."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        current = load_lead_statuses(job_id).get(lead_id)
        return Response({"lead_id": lead_id, "status": current}, status=status.HTTP_200_OK)

    body = request.data or {}
    new_status = body.get("status")
    if new_status is not None and not isinstance(new_status, str):
        return Response({"error": "'status' must be a string or null."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        statuses = set_lead_status(job_id, lead_id, new_status)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"lead_id": lead_id, "status": statuses.get(lead_id), "statuses": statuses}, status=status.HTTP_200_OK)


@api_view(["GET"])
def lead_overrides(request, job_id):
    """Return the full field-override map for a job: {lead_id: {field: value}}."""
    if load_job(job_id) is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"overrides": load_overrides(job_id)}, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
def lead_override(request, job_id, lead_id):
    """
    Get or set a single lead's field overrides.
    GET  -> {"lead_id": ..., "overrides": {field: value}}
    POST -> {"field": "name", "value": "..."}  (value null clears the override)

    Overrides are re-applied on the next pipeline run via Phase 3 cleaning.
    """
    if load_job(job_id) is None:
        return Response({"error": f"Job {job_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    results, err = _results_or_404(request, job_id)
    if err:
        return err
    if not any(l.get("lead_id") == lead_id for l in results.get("qualified") or []):
        return Response({"error": f"Lead {lead_id} not found in qualified results."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        current = load_overrides(job_id).get(lead_id, {})
        return Response({"lead_id": lead_id, "overrides": current}, status=status.HTTP_200_OK)

    body = request.data or {}
    field = body.get("field")
    if not isinstance(field, str) or field not in OVERRIDABLE_FIELDS:
        return Response(
            {"error": f"'field' must be one of {sorted(OVERRIDABLE_FIELDS)}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    value = body.get("value")
    if value is not None and not isinstance(value, (str, int, float)):
        return Response({"error": "'value' must be a string or number (or null to clear)."}, status=status.HTTP_400_BAD_REQUEST)
    overrides = set_override(job_id, lead_id, field, value)
    return Response(
        {"lead_id": lead_id, "overrides": overrides.get(lead_id, {})},
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def clusters_list(request, job_id):
    """Return summary of all clusters for a job."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err
    return Response({"clusters": results.get("clusters") or []}, status=status.HTTP_200_OK)


@api_view(["GET"])
def cluster_detail(request, job_id, cluster_id):
    """Return detailed cluster analysis (Phase 6-7)."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err
    for cluster in results.get("clusters") or []:
        if cluster.get("cluster_id") == cluster_id:
            return Response(cluster, status=status.HTTP_200_OK)
    return Response({"error": f"Cluster {cluster_id} not found."}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
def export_csv(request, job_id):
    """Download executive summary CSV for a job."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err

    tier = request.query_params.get("tier")
    sort = request.query_params.get("sort")
    leads = _filter_leads(results, tier, sort)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "rank", "lead_id", "contact_email", "name", "company", "title", "budget", "score",
        "tier", "recommendation", "intent_level", "primary_need", "timeline",
        "authority_score", "next_action", "talking_point", "contact_method",
        "days_since_contact",
    ])
    for lead in leads:
        cleaned = lead.get("cleaned_data") or {}
        intel = lead.get("intelligence_features", {})
        scoring = lead.get("scoring", {})
        analysis = lead.get("analysis_summary", {})
        lead_id = lead.get("lead_id") or ""
        budget = cleaned.get("budget_monthly")
        budget_str = f"${int(budget):,}/mo" if budget else "N/A"
        days = cleaned.get("days_since_created")
        use_cases = intel.get("use_case_signals", {}).get("extracted_use_cases") or []
        primary_need = use_cases[0] if use_cases else "General automation"
        timeline = intel.get("timeline_signals", {}).get("timeline_urgency_level")
        talking = (lead.get("sales_strategy") or {}).get("conversation_starters") or []
        writer.writerow([
            lead.get("rank"),
            lead_id,
            cleaned.get("email"),
            cleaned.get("name"),
            cleaned.get("company"),
            cleaned.get("title"),
            budget_str,
            scoring.get("final_score"),
            scoring.get("tier"),
            analysis.get("recommendation"),
            analysis.get("intent_level"),
            primary_need,
            timeline,
            cleaned.get("title_decision_authority_score"),
            (TIER_ACTION.get(scoring.get("tier")) if scoring.get("tier") else analysis.get("recommendation")),
            talking[0] if talking else "",
            "Phone" if scoring.get("tier") in ("TIER1", "TIER2") else "Email",
            days,
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="executive_summary_{job_id}.csv"'
    return response


@api_view(["GET"])
def export_json(request, job_id):
    """Download full detailed JSON analysis for a job."""
    results, err = _results_or_404(request, job_id)
    if err:
        return err

    tiers = (results.get("summary") or {}).get("tier_summary") or {}
    budget_t1 = sum(
        (l.get("cleaned_data") or {}).get("budget_monthly") or 0
        for l in (results.get("qualified") or [])
        if (l.get("scoring") or {}).get("tier") == "TIER1"
    )
    total_budget = sum(
        (l.get("cleaned_data") or {}).get("budget_monthly") or 0
        for l in (results.get("qualified") or [])
    )

    payload = {
        "export_metadata": {
            "export_date": results.get("processing_duration_seconds"),
            "total_leads_uploaded": (results.get("summary") or {}).get("total"),
            "total_leads_qualified": (results.get("summary") or {}).get("qualified"),
            "total_leads_disqualified": (results.get("summary") or {}).get("disqualified"),
            "total_leads_low_priority": (results.get("summary") or {}).get("low_priority"),
            "processing_duration_seconds": results.get("processing_duration_seconds"),
            "clusters_created": (results.get("summary") or {}).get("clusters_created"),
            "llm_calls_made": results.get("llm_calls_made"),
            "processing_cost_usd": (results.get("summary") or {}).get("processing_cost_usd"),
            "analysis_version": "2.0",
        },
        "cluster_analyses": results.get("clusters") or [],
        "leads": results.get("qualified") or [],
        "tier_summary": tiers,
        "summary_statistics": {
            "recommended_immediate_outreach_count": (results.get("summary") or {}).get("recommended_immediate_outreach", 0),
            "total_pipeline_value_all_tiers": total_budget,
            "total_pipeline_value_tier1_only": budget_t1,
            "avg_score_tier1": tiers.get("TIER1", {}).get("avg_score"),
            "avg_score_tier2": tiers.get("TIER2", {}).get("avg_score"),
            "avg_score_tier3": tiers.get("TIER3", {}).get("avg_score"),
            "avg_score_tier4": tiers.get("TIER4", {}).get("avg_score"),
            "avg_score_tier5": tiers.get("TIER5", {}).get("avg_score"),
        },
    }

    response = HttpResponse(json.dumps(payload, indent=2, default=str), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="detailed_analysis_{job_id}.json"'
    return response
