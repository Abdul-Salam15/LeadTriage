"""
PHASE 1: UPLOAD & INITIAL VALIDATION

Handles the CSV upload lifecycle:
  1. File type validation (CSV only)
  2. File size check (MAX_UPLOAD_SIZE_MB)
  3. Encoding detection (UTF-8, ISO-8859-1, etc.)
  4. Column header detection (first row)
  5. Preview generation (file size, row count, detected columns)
  6. Store file temporarily under a UUID-based filename
  7. Return job_id for tracking + estimated processing time
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chardet
from django.conf import settings


class UploadValidationError(Exception):
    """Raised when the uploaded file fails validation rules."""


@dataclass
class UploadPreview:
    """Phase 1 output: everything the frontend needs to render the preview."""

    job_id: str
    filename: str
    size_bytes: int
    row_count: int
    detected_columns: list
    encoding: str
    dialect: dict
    sample_rows: list
    estimated_time_seconds: int
    uploaded_at: str
    status: str = "awaiting_column_mapping"
    message: str = "File accepted. Please confirm or adjust the column mapping."


@dataclass
class UploadJob:
    """Serializable job state persisted to disk as JSON."""

    job_id: str
    status: str
    progress_percent: int
    message: str
    timestamp: str
    upload: dict = field(default_factory=dict)
    mapping: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "message": self.message,
            "timestamp": self.timestamp,
            "upload": self.upload,
            "mapping": self.mapping,
            "results": self.results,
        }


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def uploaded_path(job_id: str) -> Path:
    return settings.TEMP_UPLOAD_DIR / f"{job_id}.csv"


def job_path(job_id: str) -> Path:
    return settings.TEMP_JOB_DIR / f"{job_id}.json"


def lead_status_path(job_id: str) -> Path:
    """Per-job lead status store: {lead_id: "SKIPPED"|"CONTACTED"|"QUALIFIED"}."""
    return settings.TEMP_JOB_DIR / f"{job_id}_lead_status.json"


VALID_LEAD_STATUSES = {"SKIPPED", "CONTACTED", "QUALIFIED"}


def load_lead_statuses(job_id: str) -> dict:
    """Return the lead status map for a job (empty dict if none yet)."""
    path = lead_status_path(job_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_lead_statuses(job_id: str, statuses: dict) -> dict:
    """Persist a lead status map, keeping only valid statuses."""
    ensure_dirs()
    cleaned = {
        lead_id: status
        for lead_id, status in statuses.items()
        if status in VALID_LEAD_STATUSES
    }
    lead_status_path(job_id).write_text(
        json.dumps(cleaned, indent=2), encoding="utf-8"
    )
    return cleaned


def set_lead_status(job_id: str, lead_id: str, status: str | None) -> dict:
    """Set (or clear, when status is None) a single lead's status."""
    statuses = load_lead_statuses(job_id)
    if status is None:
        statuses.pop(lead_id, None)
    elif status in VALID_LEAD_STATUSES:
        statuses[lead_id] = status
    else:
        raise ValueError(f"Invalid lead status '{status}'. Must be one of {sorted(VALID_LEAD_STATUSES)}.")
    return save_lead_statuses(job_id, statuses)


def overrides_path(job_id: str) -> Path:
    """Per-job field override store: {lead_id: {field: value}}."""
    return settings.TEMP_JOB_DIR / f"{job_id}_overrides.json"


def load_overrides(job_id: str) -> dict:
    """Return the field override map for a job (empty dict if none yet)."""
    path = overrides_path(job_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_overrides(job_id: str, overrides: dict) -> dict:
    """Persist the full override map for a job."""
    ensure_dirs()
    overrides_path(job_id).write_text(
        json.dumps(overrides, indent=2), encoding="utf-8"
    )
    return overrides


def set_override(job_id: str, lead_id: str, field: str, value) -> dict:
    """Set (or clear, when value is None) a single field override for a lead."""
    overrides = load_overrides(job_id)
    lead_overrides = dict(overrides.get(lead_id, {}))
    if value is None:
        lead_overrides.pop(field, None)
    else:
        lead_overrides[field] = value
    if lead_overrides:
        overrides[lead_id] = lead_overrides
    else:
        overrides.pop(lead_id, None)
    return save_overrides(job_id, overrides)


def ensure_dirs() -> None:
    settings.TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.TEMP_JOB_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Job state persistence (simple JSON-based store for now)
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_job(job: UploadJob) -> None:
    ensure_dirs()
    job.timestamp = _now()
    job_path(job.job_id).write_text(
        json.dumps(job.to_dict(), indent=2), encoding="utf-8"
    )


def load_job(job_id: str) -> UploadJob | None:
    path = job_path(job_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return UploadJob(
        job_id=data["job_id"],
        status=data["status"],
        progress_percent=data["progress_percent"],
        message=data["message"],
        timestamp=data["timestamp"],
        upload=data.get("upload", {}),
        mapping=data.get("mapping", {}),
        results=data.get("results", {}),
    )


def update_job(job: UploadJob, **changes) -> UploadJob:
    for key, value in changes.items():
        setattr(job, key, value)
    save_job(job)
    return job


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_file(file_object, size_bytes: int | None = None) -> None:
    """Validate file type + size before anything else."""
    size = size_bytes if size_bytes is not None else file_object.size
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if size > max_bytes:
        raise UploadValidationError(
            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit "
            f"({size / 1024 / 1024:.1f}MB)."
        )

    name = getattr(file_object, "name", "") or ""
    ext = Path(name).suffix.lower()
    if ext and ext != ".csv":
        raise UploadValidationError(
            f"Unsupported file type '{ext}'. Please upload a CSV file."
        )

    # Peek at the first non-empty bytes to reject binary content.
    head = _peek_bytes(file_object)
    if b"\x00" in head[:4096] and not _looks_like_text(head):
        raise UploadValidationError(
            "File appears to be binary, not a CSV text file."
        )


def _peek_bytes(file_object) -> bytes:
    file_object.seek(0)
    data = file_object.read(65536)
    file_object.seek(0)
    return data


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: many newline bytes or mostly printable ASCII => text."""
    if not data:
        return True
    non_printable = sum(1 for b in data if b < 9 or (b > 13 and b < 32))
    return non_printable / len(data) < 0.05


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

def detect_encoding(raw: bytes) -> tuple[str, float]:
    """Detect encoding using chardet, defaulting to UTF-8."""
    if not raw:
        return "utf-8", 1.0
    result = chardet.detect(raw)
    encoding = result.get("encoding") or "utf-8"
    confidence = result.get("confidence") or 0.0
    return encoding, round(confidence, 3)


def decode_text(raw: bytes, encoding: str) -> str:
    """Decode raw bytes, falling back gracefully on Unicode errors."""
    for candidate in (encoding, "utf-8", "ISO-8859-1"):
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Header + row parsing
# ---------------------------------------------------------------------------

def parse_csv(text: str) -> tuple[list, list, dict]:
    """
    Parse CSV text into (headers, sample_rows, dialect).
    Uses Sniffer when possible; falls back to a sensible default.
    Dialect also captures the per-file column count (not raw dialect
    object, which isn't JSON-serializable).
    """
    text = text.lstrip("\ufeff")  # strip BOM if present
    dialect_kwargs = {
        "delimiter": ",",
        "quotechar": '"',
        "skipinitialspace": False,
        "lineterminator": "\r\n",
    }
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t")
        dialect_kwargs = {
            "delimiter": dialect.delimiter,
            "quotechar": dialect.quotechar,
            "skipinitialspace": dialect.skipinitialspace,
            "lineterminator": dialect.lineterminator,
        }
    except csv.Error:
        pass

    reader = csv.reader(io.StringIO(text), **dialect_kwargs)
    rows = [row for row in reader]
    rows = [r for r in rows if any(cell.strip() for cell in r)]

    headers = [h.strip() for h in rows[0]] if rows else []
    sample_rows = rows[1:6]

    metadata = {
        "delimiter": dialect_kwargs["delimiter"],
        "quotechar": dialect_kwargs["quotechar"],
        "skipinitialspace": dialect_kwargs["skipinitialspace"],
        "lineterminator": dialect_kwargs["lineterminator"],
        "column_count": len(headers),
        "row_count_including_header": len(rows),
    }
    return headers, sample_rows, metadata


def estimate_processing_time(row_count: int) -> int:
    """Rough estimate: ~0.35s per lead (cleaning + signal extraction)."""
    return max(5, math.ceil(row_count * 0.35))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_upload(file_object) -> UploadPreview:
    """
    Validate + analyze an uploaded CSV and persist the initial job state.

    Returns an UploadPreview with everything Phase 1 promises.
    """
    ensure_dirs()
    validate_file(file_object)

    # Read the FULL file (not just the 64KB peek used for validation) so the
    # preview row_count / size and parsing reflect the entire upload.
    file_object.seek(0)
    raw = file_object.read()
    file_object.seek(0)
    encoding, confidence = detect_encoding(raw)
    text = decode_text(raw, encoding)
    headers, sample_rows, dialect = parse_csv(text)

    if not headers:
        raise UploadValidationError("CSV appears to be empty (no header row found).")

    job_id = str(uuid.uuid4())

    # Persist the raw file under its UUID name for downstream phases.
    file_object.seek(0)
    dest = uploaded_path(job_id)
    with open(dest, "wb") as fh:
        shutil.copyfileobj(file_object, fh)

    row_count = dialect["row_count_including_header"] - 1 if dialect["row_count_including_header"] else 0

    preview = UploadPreview(
        job_id=job_id,
        filename=getattr(file_object, "name", "upload.csv"),
        size_bytes=len(raw) if raw else 0,
        row_count=max(0, row_count),
        detected_columns=headers,
        encoding=encoding,
        dialect=dialect,
        sample_rows=sample_rows,
        estimated_time_seconds=estimate_processing_time(max(0, row_count)),
        uploaded_at=_now(),
    )

    job = UploadJob(
        job_id=job_id,
        status="awaiting_column_mapping",
        progress_percent=5,
        message="File accepted. Please confirm or adjust the column mapping.",
        timestamp=_now(),
        upload={
            "filename": preview.filename,
            "size_bytes": preview.size_bytes,
            "size_mb": round(preview.size_bytes / 1024 / 1024, 2),
            "row_count": preview.row_count,
            "detected_columns": preview.detected_columns,
            "encoding": preview.encoding,
            "encoding_confidence": confidence,
            "dialect": preview.dialect,
            "sample_rows": preview.sample_rows,
            "estimated_time_seconds": preview.estimated_time_seconds,
            "uploaded_at": preview.uploaded_at,
        },
    )
    save_job(job)

    return preview
