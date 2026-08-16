"""
PHASE 13: GENERALIZATION & ROBUSTNESS TESTS

Covers the 8 MD testing scenarios (different column names, date formats,
budget formats, missing columns, non-English notes, data quality variance,
company size variations, email variations) plus robustness features
(error handling, validation flags, quality reports).
"""

from django.test import SimpleTestCase

from triage import column_detection as cd
from triage.cleaner import (
    clean_budget,
    clean_date,
    clean_email,
    clean_employees,
    clean_notes,
    clean_title,
    clean_website,
)


class DifferentColumnNames(SimpleTestCase):
    """Scenario 1: fuzzy-matched aliases normalize without manual config."""

    def test_email_address_variants(self):
        for header in ("email_address", "emailAddr", "E-mail", "contact_email"):
            result = cd.match_column(header)
            self.assertEqual(result.mapped_to, "email", header)
            self.assertIn(result.match_type, ("EXACT", "CASE_INSENSITIVE", "FUZZY"))

    def test_full_pipeline_mapping_accepts_aliases(self):
        headers = ["lead_id", "created_date", "full_name", "email_address",
                   "org_name", "team_size", "website", "designation", "monthly_spend", "notes"]
        summary = cd.detect_columns("job-x", headers)
        mapped = {m.mapped_to for m in summary.mappings}
        for field in ("name", "email", "company", "employees", "title", "monthly_budget"):
            self.assertIn(field, mapped)
        self.assertFalse(summary.to_dict()["needs_user_confirmation"])


class DifferentDateFormats(SimpleTestCase):
    """Scenario 2: mixed MM/DD/YYYY, DD-MM-YYYY, YYYY-MM-DD all -> ISO."""

    def test_us_format(self):
        result = clean_date("06/28/2024")
        self.assertEqual(result["created_date"], "2024-06-28")

    def test_iso_format(self):
        result = clean_date("2024-06-08")
        self.assertEqual(result["created_date"], "2024-06-08")

    def test_dd_mm_yyyy_high_day(self):
        # Day > 12 disambiguates to DD-MM.
        result = clean_date("19-06-2024")
        self.assertEqual(result["created_date"], "2024-06-19")
        self.assertFalse(result["created_date_is_ambiguous"])

    def test_dd_mm_yyyy_dots(self):
        result = clean_date("28.06.2024")
        self.assertEqual(result["created_date"], "2024-06-28")

    def test_month_name_formats(self):
        for raw in ("Jun 7 2024", "7 Jun 2024", "June 7, 2024"):
            result = clean_date(raw)
            self.assertEqual(result["created_date"], "2024-06-07", raw)


class DifferentBudgetFormats(SimpleTestCase):
    """Scenario 3: all normalized to numeric monthly with a category."""

    def test_plain_number(self):
        result = clean_budget("5000")
        self.assertEqual(result["budget_monthly"], 5000)
        self.assertEqual(result["budget_category"], "MID_MARKET")

    def test_dollar_k_abbreviation(self):
        result = clean_budget("$5k")
        self.assertEqual(result["budget_monthly"], 5000)

    def test_range(self):
        result = clean_budget("5k-7k")
        self.assertEqual(result["budget_is_range"], True)
        self.assertEqual(result["budget_min"], 5000)
        self.assertEqual(result["budget_max"], 7000)

    def test_formatted_per_month(self):
        result = clean_budget("$5,000/month")
        self.assertEqual(result["budget_monthly"], 5000)

    def test_slash_per_month(self):
        result = clean_budget("5000/mo")
        self.assertEqual(result["budget_monthly"], 5000)

    def test_tbd_not_disclosed(self):
        result = clean_budget("TBD")
        self.assertEqual(result["budget_monthly"], None)
        self.assertEqual(result["budget_flag"], "BUDGET_NOT_DISCLOSED")


class MissingColumns(SimpleTestCase):
    """Scenario 4: missing columns are flagged, processing continues."""

    def test_website_and_title_missing_flagged(self):
        headers = ["lead_id", "email", "name", "company", "notes"]
        summary = cd.detect_columns("job-x", headers)
        mapped = {m.mapped_to for m in summary.mappings}
        self.assertNotIn("website", mapped)
        self.assertNotIn("title", mapped)

    def test_cleaners_handle_none_gracefully(self):
        # Cleaners must never raise on missing/None values.
        self.assertEqual(clean_website(None)["website"], None)
        self.assertEqual(clean_title(None)["title"], None)
        self.assertEqual(clean_email(None)["email"], None)


class DifferentLanguagesInNotes(SimpleTestCase):
    """Scenario 5: English processed, non-English flagged, signals still extracted."""

    def test_pidgin_english_processed(self):
        result = clean_notes("Oga we go dey pay for this kind thing, budget dey ready")
        self.assertFalse(result["notes_is_non_english"])
        self.assertEqual(result["notes_language"], "ENGLISH")

    def test_french_flagged(self):
        result = clean_notes("Bonjour, nous voulons automatiser notre prospection, merci beaucoup pour votre solution de triage.")
        self.assertTrue(result["notes_is_non_english"])
        self.assertEqual(result["notes_language"], "FRENCH")

    def test_cyrillic_flagged(self):
        result = clean_notes("Здравствуйте, нам нужна автоматизация лидов, у нас есть бюджет.")
        self.assertTrue(result["notes_is_non_english"])
        self.assertNotEqual(result["notes_language"], "ENGLISH")

    def test_signals_still_extracted_from_english_markers(self):
        result = clean_notes("Budget approved, keen to start ASAP, we chase follow-ups manually.")
        self.assertIn("budget_approved", result["extracted_signals"])
        self.assertIn("timeline_asap", result["extracted_signals"])


class DataQualityVariations(SimpleTestCase):
    """Scenario 6: clean vs messy data -> consistent field-level flags."""

    def test_clean_data_no_flags(self):
        email = clean_email("gbenga@luxauto.io")
        self.assertTrue(email["email_is_valid"])
        self.assertIsNone(email["email_flag"])

    def test_messy_data_flags(self):
        email = clean_email("  Gbenga @luxauto..io  ")
        self.assertFalse(email["email_is_valid"])
        self.assertEqual(email["email_flag"], "INVALID_EMAIL")

    def test_empty_data_missing_flags(self):
        self.assertEqual(clean_email("")["email_flag"], "MISSING_EMAIL")
        self.assertEqual(clean_date("")["created_date_flag"], "MISSING_DATE")
        self.assertEqual(clean_budget("")["budget_flag"], "MISSING_BUDGET")
        self.assertEqual(clean_notes("")["notes_flag"], "MISSING_NOTES")


class CompanySizeVariations(SimpleTestCase):
    """Scenario 7: '1-5', '5-10', '10', '10+', '~10', '-' all standardized."""

    def test_range(self):
        result = clean_employees("1-5")
        self.assertEqual(result["employees"], 3)
        self.assertEqual(result["employees_data_quality"], "RANGE")

    def test_range_five_ten(self):
        result = clean_employees("5-10")
        self.assertEqual(result["employees"], 7)

    def test_exact(self):
        result = clean_employees("10")
        self.assertEqual(result["employees"], 10)
        self.assertEqual(result["employees_data_quality"], "EXACT")

    def test_min(self):
        result = clean_employees("10+")
        self.assertEqual(result["employees"], 10)
        self.assertEqual(result["employees_data_quality"], "APPROXIMATE_MIN")

    def test_approximate(self):
        result = clean_employees("~10")
        self.assertEqual(result["employees"], 10)
        self.assertEqual(result["employees_data_quality"], "APPROXIMATE")

    def test_dash_unknown(self):
        result = clean_employees("-")
        self.assertEqual(result["employees"], None)
        self.assertEqual(result["employees_is_missing"], True)


class EmailAddressVariations(SimpleTestCase):
    """Scenario 8: markdown links, uppercase, 'john @company.com' normalized."""

    def test_markdown_link(self):
        result = clean_email("[john@company.com](mailto:john@company.com)")
        self.assertEqual(result["email"], "john@company.com")
        self.assertTrue(result["email_is_valid"])

    def test_uppercase(self):
        result = clean_email("JOHN@COMPANY.COM")
        self.assertEqual(result["email"], "john@company.com")
        self.assertTrue(result["email_is_valid"])

    def test_internal_spaces_before_at(self):
        # 'john @company.com' is invalid but must not crash.
        result = clean_email("john @company.com")
        self.assertFalse(result["email_is_valid"])
        self.assertIn(result["email_flag"], ("INVALID_EMAIL", "INVALID_DOMAIN"))

    def test_typo_correction(self):
        result = clean_email("john@gmail.om")
        self.assertEqual(result["email"], "john@gmail.com")
        self.assertEqual(result["email_flag"], "TYPO_FIXED")


class Robustness(SimpleTestCase):
    """Phase 13 robustness features."""

    def test_cleaners_never_crash_on_bad_types(self):
        for fn in (clean_budget, clean_date, clean_email, clean_employees, clean_notes,
                   clean_title, clean_website):
            for bad in (None, "", "   ", "@@@", "\x00\x01 garbage \x00", 12345, ["x"]):
                try:
                    fn(bad)
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"{fn.__name__}({bad!r}) raised {exc!r}")

    def test_column_detection_never_crashes_on_weird_headers(self):
        weird = ["!!!!", "", " ", "123", "ünïcødé 漢字", "*" * 50, None]
        for header in weird:
            try:
                cd.match_column(header)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"match_column({header!r}) raised {exc!r}")

    def test_unmapped_requires_confirmation(self):
        summary = cd.detect_columns("job-x", ["name", "weird_header_xyz"])
        self.assertTrue(summary.to_dict()["needs_user_confirmation"])
        self.assertIn("weird_header_xyz", summary.unmapped)

    def test_user_override_manual_mapping(self):
        summary = cd.detect_columns("job-x", ["custom_field"])
        cd.apply_user_mapping(summary, {"custom_field": "notes"})
        self.assertEqual(summary.mappings[0].mapped_to, "notes")
        self.assertEqual(summary.mappings[0].match_type, "MANUAL")
