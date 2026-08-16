"""
PHASE 2: COLUMN DETECTION & STANDARDIZATION

Adapts to different CSV structures without manual configuration.

Match strategy for each header in the uploaded CSV:
  1. Exact match against canonical names
  2. Case-insensitive match
  3. Fuzzy string matching (difflib.SequenceMatcher)
  4. Only accept matches with >80% similarity
  5. If no match / low confidence -> flag for user clarification
  6. Store the mapping for reuse in the pipeline
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# The canonical column mapping dictionary (single source of truth).
# Keys are canonical field names; values are known synonyms/variations.
COLUMN_MAPPING: dict[str, list[str]] = {
    "lead_id": ["lead_id", "id", "leadid", "lead ID", "lead_number"],
    "name": ["name", "contact_name", "full_name", "fname", "contact", "person_name"],
    "email": ["email", "email_address", "contact_email", "e_mail", "email_addr"],
    "company": ["company", "organization", "org_name", "company_name", "firm", "business"],
    "employees": ["employees", "company_size", "team_size", "headcount", "staff_count"],
    "website": ["website", "url", "company_url", "web", "domain", "web_address"],
    "title": ["title", "job_title", "position", "role", "job_role", "designation"],
    "source": ["source", "channel", "how_found", "lead_source", "acquisition_channel"],
    "monthly_budget": ["monthly_budget", "budget", "price_range", "budget_range", "monthly_spend"],
    "notes": ["notes", "comment", "conversation", "message", "details", "follow_up", "remarks"],
}

# Extra fields recognized outside the core mapping (e.g. the provided CSV
# also ships a 'created' date column). These extend, not replace, the above.
EXTRA_COLUMN_MAPPING: dict[str, list[str]] = {
    "created_date": ["created", "created_date", "date_created", "submission_date", "date"],
}

# Merge extra fields into the canonical mapping.
for _canonical, _synonyms in EXTRA_COLUMN_MAPPING.items():
    if _canonical not in COLUMN_MAPPING:
        COLUMN_MAPPING[_canonical] = []
    for _s in _synonyms:
        if _s not in COLUMN_MAPPING[_canonical]:
            COLUMN_MAPPING[_canonical].append(_s)

# All accepted header strings -> canonical field, for fast lookup.
_ALL_KNOWN_HEADERS: dict[str, str] = {}
for _canonical, _synonyms in COLUMN_MAPPING.items():
    for _syn in _synonyms:
        _ALL_KNOWN_HEADERS[_syn] = _canonical
    _ALL_KNOWN_HEADERS[_canonical] = _canonical


MATCH_THRESHOLD = 0.80  # only accept fuzzy matches above this similarity


@dataclass
class ColumnMappingResult:
    """Per-header mapping decision from Phase 2."""

    header: str
    mapped_to: str | None
    match_type: str  # EXACT | CASE_INSENSITIVE | FUZZY | NO_MATCH
    similarity: float
    confidence: str  # HIGH | MEDIUM | LOW
    requires_confirmation: bool


@dataclass
class MappingSummary:
    """Full Phase 2 output: mapping per header + list of unmapped columns."""

    job_id: str
    mappings: list[ColumnMappingResult]
    unmapped: list[str]
    mapped_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "MappingSummary":
        return cls(
            job_id=data.get("job_id", ""),
            mappings=[
                ColumnMappingResult(
                    header=m.get("header", ""),
                    mapped_to=m.get("mapped_to"),
                    match_type=m.get("match_type", "NO_MATCH"),
                    similarity=m.get("similarity", 0.0),
                    confidence=m.get("confidence", "LOW"),
                    requires_confirmation=m.get("requires_confirmation", True),
                )
                for m in data.get("mappings", [])
            ],
            unmapped=data.get("unmapped", []),
            mapped_fields=data.get("mapped_fields", []),
        )

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "mappings": [
                {
                    "header": m.header,
                    "mapped_to": m.mapped_to,
                    "match_type": m.match_type,
                    "similarity": round(m.similarity, 4),
                    "confidence": m.confidence,
                    "requires_confirmation": m.requires_confirmation,
                }
                for m in self.mappings
            ],
            "unmapped": self.unmapped,
            "mapped_fields": self.mapped_fields,
            "needs_user_confirmation": bool(self.unmapped or [m for m in self.mappings if m.requires_confirmation]),
        }


def _norm(header: str) -> str:
    """Normalize a header for matching: strip, lowercase, collapse spaces/underscores."""
    return re.sub(r"[_\s]+", "_", header.strip().lower())


def _fuzzy_score(a: str, b: str) -> float:
    """Similarity ratio between two strings using difflib.SequenceMatcher."""
    return SequenceMatcher(None, a, b).ratio()


def match_column(header: str) -> ColumnMappingResult:
    """
    Match a single header against the canonical mapping.
    Follows the exact order from the MD:
      exact -> case-insensitive -> fuzzy -> threshold check.
    Robust against None / non-string / empty inputs (Phase 13).
    """
    if header is None:
        header = ""
    if not isinstance(header, str):
        header = str(header)

    original = header.strip()

    # 1. Exact match
    if original in _ALL_KNOWN_HEADERS:
        return ColumnMappingResult(
            header=original,
            mapped_to=_ALL_KNOWN_HEADERS[original],
            match_type="EXACT",
            similarity=1.0,
            confidence="HIGH",
            requires_confirmation=False,
        )

    normalized = _norm(original)

    # 2. Case-insensitive match (normalize then lookup)
    if normalized in _ALL_KNOWN_HEADERS:
        return ColumnMappingResult(
            header=original,
            mapped_to=_ALL_KNOWN_HEADERS[normalized],
            match_type="CASE_INSENSITIVE",
            similarity=1.0,
            confidence="HIGH",
            requires_confirmation=False,
        )

    # 3. Fuzzy matching against every known synonym
    best_canonical = None
    best_score = 0.0
    for _canonical, _synonyms in COLUMN_MAPPING.items():
        for _syn in _synonyms:
            score = max(
                _fuzzy_score(normalized, _norm(_syn)),
                _fuzzy_score(normalized, _norm(_canonical)),
            )
            if score > best_score:
                best_score = score
                best_canonical = _canonical

    # 4. Threshold check (>80%)
    if best_canonical is not None and best_score > MATCH_THRESHOLD:
        match_type = "FUZZY"
        confidence = "MEDIUM" if best_score < 0.90 else "HIGH"
        return ColumnMappingResult(
            header=original,
            mapped_to=best_canonical,
            match_type=match_type,
            similarity=best_score,
            confidence=confidence,
            requires_confirmation=confidence == "MEDIUM",
        )

    # 5. No match -> needs user clarification
    return ColumnMappingResult(
        header=original,
        mapped_to=None,
        match_type="NO_MATCH",
        similarity=best_score,
        confidence="LOW",
        requires_confirmation=True,
    )


def detect_columns(job_id: str, headers: list[str]) -> MappingSummary:
    """Map every detected header to a canonical field, if possible."""
    mappings: list[ColumnMappingResult] = []
    unmapped: list[str] = []

    for header in headers:
        if not header or not str(header).strip():
            continue
        result = match_column(header)
        mappings.append(result)
        if result.mapped_to is None:
            unmapped.append(header)

    summary = MappingSummary(
        job_id=job_id,
        mappings=mappings,
        unmapped=unmapped,
        mapped_fields=[m.mapped_to for m in mappings if m.mapped_to],
    )
    return summary


def apply_user_mapping(summary: MappingSummary, user_mapping: dict[str, str]) -> MappingSummary:
    """
    Apply a user override for unmapped / low-confidence columns.

    user_mapping: {header: "canonical_field" | "__ignore__" | "__metadata__"}
      - A canonical field name -> map the header to it
      - "__ignore__" -> drop the column
      - "__metadata__" -> keep as metadata (untransformed reference column)
    """
    for mapping in summary.mappings:
        override = user_mapping.get(mapping.header)
        if override is None:
            continue
        if override in ("__ignore__", "__metadata__"):
            mapping.mapped_to = override
            mapping.match_type = "MANUAL"
            mapping.confidence = "HIGH"
            mapping.requires_confirmation = False
        else:
            mapping.mapped_to = override
            mapping.match_type = "MANUAL"
            mapping.similarity = 1.0
            mapping.confidence = "HIGH"
            mapping.requires_confirmation = False

    summary.unmapped = [
        m.header for m in summary.mappings if m.mapped_to is None
    ]
    summary.mapped_fields = [
        m.mapped_to for m in summary.mappings if m.mapped_to and m.mapped_to not in ("__ignore__", "__metadata__")
    ]
    return summary
