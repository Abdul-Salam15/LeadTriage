"""
Phase 3.1-3.5 tests: lead_id, dates, names, emails, companies.
Each test mirrors the exact input/output examples in the MD.
"""

from datetime import date

from django.test import SimpleTestCase

from triage.cleaner.companies import clean_company
from triage.cleaner.dates import clean_date
from triage.cleaner.emails import clean_email
from triage.cleaner.lead_id import clean_lead_id
from triage.cleaner.names import clean_name


class LeadIdTests(SimpleTestCase):
    def test_l_1369(self):
        result = clean_lead_id("L-1369")
        self.assertEqual(result["lead_id"], "L-1369")
        self.assertFalse(result["lead_id_is_duplicate"])
        self.assertEqual(result["lead_id_data_quality"], "NORMALIZED")

    def test_numeric_1341(self):
        result = clean_lead_id("1341")
        self.assertEqual(result["lead_id"], "L-1341")
        self.assertEqual(result["lead_id_data_quality"], "EXACT")

    def test_dup_suffix(self):
        result = clean_lead_id("L-1205-dup")
        self.assertEqual(result["lead_id"], "L-1205")
        self.assertTrue(result["lead_id_is_duplicate"])
        self.assertEqual(result["lead_id_flag"], "DUPLICATE")

    def test_1137(self):
        result = clean_lead_id("1137")
        self.assertEqual(result["lead_id"], "L-1137")

    def test_empty(self):
        result = clean_lead_id("")
        self.assertIsNone(result["lead_id"])
        self.assertEqual(result["lead_id_flag"], "MISSING_LEAD_ID")

    def test_duplicate_in_file(self):
        seen = set()
        r1 = clean_lead_id("L-1369", seen)
        r2 = clean_lead_id("1369", seen)
        self.assertFalse(r1["lead_id_is_duplicate"])
        self.assertTrue(r2["lead_id_is_duplicate"])


class DateTests(SimpleTestCase):
    def test_us_format(self):
        result = clean_date("06/28/2024")
        self.assertEqual(result["created_date"], "2024-06-28")
        self.assertEqual(result["created_date_format_detected"], "MM/DD/YYYY")
        self.assertFalse(result["created_date_is_ambiguous"])

    def test_iso_format(self):
        result = clean_date("2024-06-08")
        self.assertEqual(result["created_date"], "2024-06-08")
        self.assertEqual(result["created_date_format_detected"], "YYYY-MM-DD")

    def test_month_name(self):
        result = clean_date("Jun 7 2024")
        self.assertEqual(result["created_date"], "2024-06-07")

    def test_ambiguous_dash(self):
        result = clean_date("04-06-2024")
        self.assertTrue(result["created_date_is_ambiguous"])
        self.assertIsNone(result["created_date"])

    def test_short_format(self):
        result = clean_date("6/1/24")
        self.assertEqual(result["created_date"], "2024-06-01")

    def test_dd_mm_format(self):
        result = clean_date("19-06-2024")
        self.assertEqual(result["created_date"], "2024-06-19")

    def test_empty(self):
        result = clean_date("")
        self.assertIsNone(result["created_date"])
        self.assertEqual(result["created_date_flag"], "MISSING_DATE")

    def test_recency_fresh(self):
        result = clean_date(date.today().isoformat())
        self.assertEqual(result["recency_category"], "FRESH")

    def test_out_of_range(self):
        result = clean_date("1985-01-01")
        self.assertEqual(result["created_date_flag"], "OUT_OF_RANGE_DATE")


class NameTests(SimpleTestCase):
    def test_gbenga(self):
        result = clean_name("Gbenga")
        self.assertEqual(result["name"], "Gbenga")
        self.assertTrue(result["name_appears_valid"])

    def test_initial_removed(self):
        result = clean_name("Lola W.")
        self.assertEqual(result["name"], "Lola")

    def test_initial_removed_grace(self):
        result = clean_name("Grace N.")
        self.assertEqual(result["name"], "Grace")

    def test_lowercase_title_cased(self):
        self.assertEqual(clean_name("josh")["name"], "Josh")
        self.assertEqual(clean_name("deji")["name"], "Deji")

    def test_nneka(self):
        self.assertEqual(clean_name("Nneka")["name"], "Nneka")

    def test_empty(self):
        result = clean_name("")
        self.assertTrue(result["name_is_missing"])

    def test_full_name_first_extracted(self):
        result = clean_name("john smith")
        self.assertEqual(result["name"], "John")


class EmailTests(SimpleTestCase):
    def test_valid(self):
        result = clean_email("gbenga@luxauto.io")
        self.assertEqual(result["email"], "gbenga@luxauto.io")
        self.assertTrue(result["email_is_valid"])
        self.assertEqual(result["email_domain"], "luxauto.io")

    def test_empty(self):
        result = clean_email("")
        self.assertIsNone(result["email"])
        self.assertEqual(result["email_flag"], "MISSING_EMAIL")

    def test_disposable(self):
        result = clean_email("tempmail@tempmail.com")
        self.assertTrue(result["email_is_disposable"])
        self.assertEqual(result["email_flag"], "DISPOSABLE_EMAIL")

    def test_personal_account(self):
        result = clean_email("john@gmail.com")
        self.assertTrue(result["email_is_valid"])
        self.assertTrue(result["email_is_personal_account"])

    def test_markdown_link_wrapped(self):
        result = clean_email("[hanao@apexsend.co](mailto:hanao@apexsend.co)")
        self.assertEqual(result["email"], "hanao@apexsend.co")
        self.assertTrue(result["email_is_valid"])

    def test_obfuscated_at(self):
        result = clean_email("sara[at]upshiftmasons.io")
        self.assertEqual(result["email"], "sara@upshiftmasons.io")

    def test_typo_fixed(self):
        result = clean_email("john@gmail.om")
        self.assertEqual(result["email"], "john@gmail.com")
        self.assertEqual(result["email_flag"], "TYPO_FIXED")

    def test_invalid(self):
        result = clean_email("not-an-email")
        self.assertFalse(result["email_is_valid"])
        self.assertEqual(result["email_flag"], "INVALID_EMAIL")


class CompanyTests(SimpleTestCase):
    def test_luxauto(self):
        result = clean_company("LuxAuto")
        self.assertEqual(result["company"], "Luxauto")
        self.assertFalse(result["company_is_solo_operator"])

    def test_performengine(self):
        self.assertEqual(clean_company("PerformEngine")["company"], "Performengine")

    def test_acme(self):
        self.assertEqual(clean_company("ACME")["company"], "Acme")

    def test_suffix_removed(self):
        result = clean_company("LuxAuto.io")
        self.assertEqual(result["company"], "Luxauto")

    def test_apexsend_co(self):
        result = clean_company("apexsend.co")
        self.assertEqual(result["company"], "Apexsend")

    def test_solo_operator(self):
        result = clean_company("Freelance")
        self.assertTrue(result["company_is_solo_operator"])
        self.assertEqual(result["company_flag"], "SOLO_OPERATOR")

    def test_empty_infers_from_email(self):
        result = clean_company("", email_domain="john@acme.com")
        self.assertFalse(result["company_is_missing"])
        self.assertEqual(result["company"], "Acme")
        self.assertEqual(result["company_flag"], "INFERRED_FROM_EMAIL")

    def test_empty_no_email(self):
        result = clean_company("")
        self.assertTrue(result["company_is_missing"])

    def test_inc_ltd_suffix(self):
        result = clean_company("Acme Inc.")
        self.assertEqual(result["company"], "Acme")

    def test_company_slug_collapses_variants(self):
        from triage.cleaner import company_slug

        self.assertEqual(company_slug("Lux Auto"), "luxauto")
        self.assertEqual(company_slug("LuxAuto"), "luxauto")
        self.assertEqual(company_slug("Lux-Auto"), "luxauto")
        self.assertEqual(company_slug("Lux Auto Inc."), "luxauto")
        self.assertEqual(company_slug("ApexSend.co"), "apexsend")
        self.assertIsNone(company_slug(""))
        self.assertIsNone(company_slug(None))

    def test_company_slug_present_in_result(self):
        result = clean_company("Lux Auto")
        self.assertEqual(result["company_slug"], "luxauto")

    def test_company_slug_absent_for_missing(self):
        result = clean_company("")
        self.assertIsNone(result["company_slug"])
