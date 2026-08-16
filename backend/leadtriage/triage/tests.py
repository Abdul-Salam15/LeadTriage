"""
Phase 2 tests: column detection, fuzzy matching, and mapping confirmation.
"""

from django.test import TestCase

from triage.column_detection import (
    COLUMN_MAPPING,
    MATCH_THRESHOLD,
    MappingSummary,
    apply_user_mapping,
    detect_columns,
    match_column,
)


class ColumnDetectionTests(TestCase):
    def test_exact_match(self):
        result = match_column("lead_id")
        self.assertEqual(result.mapped_to, "lead_id")
        self.assertEqual(result.match_type, "EXACT")
        self.assertEqual(result.confidence, "HIGH")

    def test_case_insensitive_match(self):
        result = match_column("LEAD_ID")
        self.assertEqual(result.mapped_to, "lead_id")
        self.assertEqual(result.match_type, "CASE_INSENSITIVE")

    def test_fuzzy_variations_map_correctly(self):
        cases = {
            "contact_name": "name",
            "full_name": "name",
            "fname": "name",
            "person_name": "name",
            "email_address": "email",
            "contact_email": "email",
            "email_addr": "email",
            "e_mail": "email",
            "organization": "company",
            "org_name": "company",
            "firm": "company",
            "business": "company",
            "price_range": "monthly_budget",
            "budget_range": "monthly_budget",
            "monthly_spend": "monthly_budget",
            "comment": "notes",
            "conversation": "notes",
            "details": "notes",
            "follow_up": "notes",
            "remarks": "notes",
            "job_title": "title",
            "position": "title",
            "designation": "title",
            "company_size": "employees",
            "team_size": "employees",
            "headcount": "employees",
            "created": "created_date",
            "submission_date": "created_date",
        }
        for header, expected in cases.items():
            result = match_column(header)
            self.assertEqual(
                result.mapped_to,
                expected,
                f"{header!r} should map to {expected!r}, got {result.mapped_to!r} (match_type={result.match_type})",
            )

    def test_no_match_requires_confirmation(self):
        result = match_column("random_unrelated_header")
        self.assertIsNone(result.mapped_to)
        self.assertEqual(result.match_type, "NO_MATCH")
        self.assertTrue(result.requires_confirmation)

    def test_threshold_enforced(self):
        # A header with low similarity to anything must not be mapped.
        result = match_column("zzzzqqqq")
        self.assertIsNone(result.mapped_to)

    def test_detect_columns_full(self):
        headers = [
            "lead_id", "created", "name", "email", "company", "employees",
            "website", "title", "source", "monthly_budget", "notes",
        ]
        summary = detect_columns("job-1", headers)
        self.assertEqual(len(summary.mappings), 11)
        self.assertEqual(summary.unmapped, [])
        self.assertEqual(
            summary.mapped_fields,
            ["lead_id", "created_date", "name", "email", "company", "employees",
             "website", "title", "source", "monthly_budget", "notes"],
        )

    def test_unmapped_flagged(self):
        summary = detect_columns("job-1", ["name", "mystery_column_xyz", "email"])
        self.assertIn("mystery_column_xyz", summary.unmapped)
        self.assertIn("name", summary.mapped_fields)
        self.assertTrue(summary.to_dict()["needs_user_confirmation"])

    def test_apply_user_mapping_ignore(self):
        summary = detect_columns("job-1", ["name", "mystery_column_xyz", "email"])
        apply_user_mapping(summary, {"mystery_column_xyz": "__ignore__"})
        self.assertEqual(summary.unmapped, [])
        self.assertNotIn("mystery_column_xyz", summary.mapped_fields)

    def test_apply_user_mapping_metadata(self):
        summary = detect_columns("job-1", ["name", "mystery_column_xyz"])
        apply_user_mapping(summary, {"mystery_column_xyz": "__metadata__"})
        self.assertEqual(summary.unmapped, [])
        self.assertNotIn("mystery_column_xyz", summary.mapped_fields)

    def test_apply_user_mapping_manual(self):
        summary = detect_columns("job-1", ["mystery_column_xyz"])
        apply_user_mapping(summary, {"mystery_column_xyz": "notes"})
        mapping = summary.mappings[0]
        self.assertEqual(mapping.mapped_to, "notes")
        self.assertEqual(mapping.match_type, "MANUAL")

    def test_mapping_roundtrip_from_dict(self):
        summary = detect_columns("job-1", ["name", "email", "weird_col"])
        data = summary.to_dict()
        rebuilt = MappingSummary.from_dict(data)
        self.assertEqual(len(rebuilt.mappings), 3)
        self.assertEqual(rebuilt.mappings[0].header, "name")
        self.assertEqual(rebuilt.unmapped, ["weird_col"])

    def test_threshold_constant_is_over_80(self):
        # MD requires matches accepted only ABOVE 80% similarity.
        self.assertEqual(MATCH_THRESHOLD, 0.80)
        self.assertAlmostEqual(MATCH_THRESHOLD, 0.80, places=10)

    def test_canonical_fields_present(self):
        for field in [
            "lead_id", "name", "email", "company", "employees", "website",
            "title", "source", "monthly_budget", "notes", "created_date",
        ]:
            self.assertIn(field, COLUMN_MAPPING)
