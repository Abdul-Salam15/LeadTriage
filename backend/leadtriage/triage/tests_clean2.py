"""
Phase 3.6-3.11 tests: employees, titles, websites, sources, budgets, notes.
Each test mirrors the exact input/output examples in the MD.
"""

from django.test import SimpleTestCase

from triage.cleaner.budgets import clean_budget
from triage.cleaner.employees import clean_employees, size_category
from triage.cleaner.notes import clean_notes
from triage.cleaner.sources import clean_source
from triage.cleaner.titles import clean_title
from triage.cleaner.websites import clean_website


class EmployeeTests(SimpleTestCase):
    def test_20(self):
        r = clean_employees("20")
        self.assertEqual(r["employees"], 20)
        self.assertEqual(r["employees_data_quality"], "EXACT")
        self.assertEqual(r["employee_size_category"], "Small Team")

    def test_26_people(self):
        r = clean_employees("26 people")
        self.assertEqual(r["employees"], 26)
        self.assertEqual(r["employee_size_category"], "Growing Company")

    def test_empty(self):
        r = clean_employees("")
        self.assertTrue(r["employees_is_missing"])

    def test_range(self):
        r = clean_employees("35-55")
        self.assertTrue(r["employees_is_range"])
        self.assertEqual(r["employees_min"], 35)
        self.assertEqual(r["employees_max"], 55)
        self.assertEqual(r["employees"], 45)

    def test_min_19(self):
        r = clean_employees("19+")
        self.assertEqual(r["employees"], 19)
        self.assertEqual(r["employees_data_quality"], "APPROXIMATE_MIN")

    def test_one(self):
        r = clean_employees("1")
        self.assertEqual(r["employee_size_category"], "Solo/Very Small")

    def test_approx_43(self):
        r = clean_employees("~43")
        self.assertEqual(r["employees"], 43)
        self.assertTrue(r["employees_is_approximate"])

    def test_68(self):
        r = clean_employees("68")
        self.assertEqual(r["employee_size_category"], "Established Company")

    def test_70_plus(self):
        r = clean_employees("70+")
        self.assertEqual(r["employees"], 70)
        self.assertEqual(r["employee_size_category"], "Established Company")

    def test_9(self):
        r = clean_employees("9")
        self.assertEqual(r["employee_size_category"], "Small Team")

    def test_4_plus(self):
        r = clean_employees("4+")
        self.assertEqual(r["employees"], 4)
        self.assertEqual(r["employee_size_category"], "Solo/Very Small")

    def test_size_categories(self):
        self.assertEqual(size_category(3), "Solo/Very Small")
        self.assertEqual(size_category(10), "Small Team")
        self.assertEqual(size_category(30), "Growing Company")
        self.assertEqual(size_category(75), "Established Company")
        self.assertEqual(size_category(200), "Large Company")
        self.assertEqual(size_category(1000), "Enterprise")


class TitleTests(SimpleTestCase):
    def test_head_of_ops(self):
        r = clean_title("Head of Ops")
        self.assertEqual(r["title_category"], "OPERATIONAL")
        self.assertEqual(r["title_decision_authority_score"], 0.85)
        self.assertEqual(r["title_decision_authority_level"], "HIGH")

    def test_vp_growth(self):
        r = clean_title("VP Growth")
        self.assertEqual(r["title"], "VP")
        self.assertEqual(r["title_category"], "C-SUITE")
        self.assertEqual(r["title_decision_authority_score"], 0.85)

    def test_student(self):
        r = clean_title("Student")
        self.assertEqual(r["title_category"], "NOT_DECISION_MAKER")
        self.assertEqual(r["title_decision_authority_score"], 0.0)
        self.assertEqual(r["title_decision_authority_level"], "NONE")

    def test_developer(self):
        r = clean_title("Developer")
        self.assertEqual(r["title_category"], "INDIVIDUAL_CONTRIBUTOR")
        self.assertEqual(r["title_decision_authority_score"], 0.30)
        self.assertEqual(r["title_decision_authority_level"], "LOW")

    def test_owner(self):
        r = clean_title("Owner")
        self.assertEqual(r["title_category"], "OWNERSHIP")
        self.assertEqual(r["title_decision_authority_score"], 0.95)

    def test_founder(self):
        r = clean_title("Founder")
        self.assertEqual(r["title_decision_authority_score"], 0.95)

    def test_empty(self):
        r = clean_title("")
        self.assertTrue(r["title_is_missing"])
        self.assertEqual(r["title_decision_authority_score"], 0.40)

    def test_partner(self):
        r = clean_title("Partner")
        self.assertEqual(r["title_decision_authority_score"], 0.85)

    def test_ceo(self):
        r = clean_title("CEO")
        self.assertEqual(r["title"], "CEO")
        self.assertEqual(r["title_decision_authority_score"], 0.95)

    def test_recruiter(self):
        r = clean_title("Recruiter")
        self.assertEqual(r["title_decision_authority_score"], 0.0)
        self.assertEqual(r["title_decision_authority_level"], "NONE")


class WebsiteTests(SimpleTestCase):
    def test_bare_domain(self):
        r = clean_website("luxauto.io")
        self.assertEqual(r["website"], "luxauto.io")
        self.assertTrue(r["website_is_valid"])

    def test_www(self):
        r = clean_website("www.luxauto.io")
        self.assertEqual(r["website"], "luxauto.io")
        self.assertTrue(r["website_is_valid"])

    def test_http(self):
        r = clean_website("http://upshiftloop.agency")
        self.assertEqual(r["website"], "upshiftloop.agency")

    def test_https(self):
        r = clean_website("https://performmedia.io")
        self.assertEqual(r["website"], "performmedia.io")

    def test_empty(self):
        r = clean_website("")
        self.assertTrue(r["website_is_missing"])

    def test_matches_email_domain(self):
        r = clean_website("luxauto.io", email_domain="luxauto.io")
        self.assertTrue(r["website_matches_email_domain"])

    def test_mismatch(self):
        r = clean_website("other.com", email_domain="luxauto.io")
        self.assertFalse(r["website_matches_email_domain"])
        self.assertEqual(r["website_flag"], "DOMAIN_MISMATCH")


class SourceTests(SimpleTestCase):
    def test_webform(self):
        r = clean_source("webform")
        self.assertEqual(r["source"], "WEBFORM")
        self.assertEqual(r["source_quality_score"], 0.60)

    def test_linkedin(self):
        r = clean_source("linkedin")
        self.assertEqual(r["source"], "LINKEDIN")
        self.assertEqual(r["source_quality_score"], 0.80)

    def test_event(self):
        r = clean_source("event")
        self.assertEqual(r["source"], "EVENT")
        self.assertEqual(r["source_quality_score"], 0.70)

    def test_referral(self):
        r = clean_source("referral")
        self.assertEqual(r["source"], "REFERRAL")
        self.assertEqual(r["source_quality_score"], 0.90)

    def test_cold_reply(self):
        r = clean_source("cold reply")
        self.assertEqual(r["source"], "COLD_OUTREACH")
        self.assertEqual(r["source_quality_score"], 0.50)

    def test_empty(self):
        r = clean_source("")
        self.assertEqual(r["source"], "UNKNOWN")
        self.assertEqual(r["source_quality_score"], 0.45)


class BudgetTests(SimpleTestCase):
    def test_5000_mo(self):
        r = clean_budget("5,000/mo")
        self.assertEqual(r["budget_monthly"], 5000)
        self.assertEqual(r["budget_category"], "MID_MARKET")
        self.assertEqual(r["budget_seriousness_score"], 0.75)

    def test_6k_mo(self):
        r = clean_budget("$6k/mo")
        self.assertEqual(r["budget_monthly"], 6000)
        self.assertEqual(r["budget_category"], "MID_MARKET")
        self.assertEqual(r["budget_seriousness_score"], 0.75)

    def test_range_6_8k(self):
        r = clean_budget("$6-8k")
        self.assertTrue(r["budget_is_range"])
        self.assertEqual(r["budget_min"], 6000)
        self.assertEqual(r["budget_max"], 8000)
        self.assertEqual(r["budget_monthly"], 7000)

    def test_zero(self):
        r = clean_budget("0")
        self.assertEqual(r["budget_monthly"], 0)
        self.assertEqual(r["budget_category"], "NO_BUDGET")
        self.assertEqual(r["budget_seriousness_score"], 0.2)

    def test_15k(self):
        r = clean_budget("15k/mo")
        self.assertEqual(r["budget_monthly"], 15000)
        self.assertEqual(r["budget_category"], "UPPER_MID_MARKET")
        self.assertEqual(r["budget_seriousness_score"], 0.85)

    def test_7k(self):
        r = clean_budget("$7k")
        self.assertEqual(r["budget_monthly"], 7000)
        self.assertEqual(r["budget_category"], "MID_MARKET")

    def test_range_5k_7k(self):
        r = clean_budget("5k-7k")
        self.assertEqual(r["budget_min"], 5000)
        self.assertEqual(r["budget_max"], 7000)
        self.assertEqual(r["budget_monthly"], 6000)

    def test_tbd(self):
        r = clean_budget("TBD")
        self.assertEqual(r["budget_flag"], "BUDGET_NOT_DISCLOSED")
        self.assertEqual(r["budget_seriousness_score"], 0.4)

    def test_empty(self):
        r = clean_budget("")
        self.assertEqual(r["budget_flag"], "MISSING_BUDGET")
        self.assertEqual(r["budget_seriousness_score"], 0.3)

    def test_500(self):
        r = clean_budget("500")
        self.assertEqual(r["budget_monthly"], 500)
        self.assertEqual(r["budget_category"], "MICRO")
        self.assertEqual(r["budget_seriousness_score"], 0.2)

    def test_8k(self):
        r = clean_budget("8k")
        self.assertEqual(r["budget_monthly"], 8000)
        self.assertEqual(r["budget_category"], "MID_MARKET")

    def test_18k(self):
        r = clean_budget("18k")
        self.assertEqual(r["budget_monthly"], 18000)
        self.assertEqual(r["budget_category"], "UPPER_MID_MARKET")
        self.assertEqual(r["budget_seriousness_score"], 0.85)

    def test_8000_mo(self):
        r = clean_budget("$8,000/mo")
        self.assertEqual(r["budget_monthly"], 8000)
        self.assertEqual(r["budget_category"], "MID_MARKET")

    def test_depends(self):
        r = clean_budget("depends")
        self.assertEqual(r["budget_flag"], "BUDGET_VARIABLE")


class NotesTests(SimpleTestCase):
    HIGH_INTENT = (
        "We're a influencer marketing agency, 26 people. "
        "Chasing follow-ups across email and whatsapp is eating our week. "
        "Want it automated end to end. Budget approved, wants to start ASAP."
    )

    def test_high_intent(self):
        r = clean_notes(self.HIGH_INTENT)
        # 29 words -> MEDIUM per the MD engagement rule (<20 LOW, 20-50 MEDIUM, 50+ HIGH)
        self.assertEqual(r["notes_engagement_level"], "MEDIUM")
        self.assertEqual(r["notes_sentiment"], "POSITIVE")
        self.assertEqual(r["notes_specificity"], "HIGH")
        self.assertIn("budget_approved", r["extracted_signals"])
        self.assertIn("timeline_urgent", r["extracted_signals"])
        self.assertEqual(r["extracted_company_type"], "Influencer Marketing Agency")
        self.assertIn("Follow-up Automation", r["extracted_use_cases"])
        self.assertTrue(r["notes_indicates_buyer"])
        self.assertEqual(r["flagged_as"], [])

    def test_not_buyer(self):
        r = clean_notes("Not looking to buy — I'm a developer looking for a role. Attaching my CV.")
        self.assertEqual(r["flagged_as"], ["NOT_BUYER"])
        self.assertFalse(r["notes_indicates_buyer"])
        self.assertEqual(r["notes_engagement_level"], "LOW")

    def test_spam(self):
        r = clean_notes("You have WON $1,000,000!!! Click here to claim.")
        self.assertIn("SPAM", r["flagged_as"])
        self.assertTrue(r["notes_is_spam"])
        self.assertTrue(r["notes_is_suspicious"])
        self.assertEqual(r["notes_sentiment"], "SUSPICIOUS")
        self.assertEqual(r["notes_quality_score"], 0.0)
        self.assertFalse(r["notes_indicates_buyer"])

    def test_vc_intro(self):
        r = clean_notes("VC here — wanting to intro you to a few portfolio companies. Not a direct buyer.")
        self.assertIn("NOT_DECISION_MAKER", r["flagged_as"])
        self.assertFalse(r["notes_indicates_buyer"])

    def test_competitor(self):
        r = clean_notes("I actually run a competing automation agency, just seeing how you package your offer. Not a buyer.")
        self.assertIn("COMPETITOR", r["flagged_as"])

    def test_duplicate_submission(self):
        r = clean_notes("(duplicate submission) We're a SEO agency. Want to add an AI service line.")
        self.assertIn("DUPLICATE", r["flagged_as"])
        self.assertTrue(r["notes_is_suspicious"])

    def test_student(self):
        r = clean_notes("hi! CS student, i love what you do. could you send a free template or resources? not looking to buy, just learning :)")
        self.assertIn("NOT_DECISION_MAKER", r["flagged_as"])

    def test_empty(self):
        r = clean_notes("")
        self.assertTrue(r["notes_is_missing"])
        self.assertEqual(r["notes_quality_score"], 0.0)

    def test_tools_extracted(self):
        r = clean_notes("Moving leads between apollo and the crm by hand is eating our week. Budget approved.")
        self.assertIn("Apollo", r["extracted_tools"])
        self.assertIn("CRM", r["extracted_tools"])
        self.assertIn("CRM Sync", r["extracted_use_cases"])

    def test_team_size_extracted(self):
        r = clean_notes(self.HIGH_INTENT)
        self.assertEqual(r["extracted_team_size"], 26)

    def test_paragraph_count_multiline(self):
        r = clean_notes(
            "We're an SEO agency.\n\nBudget is approved and we want to start asap.\n"
            "Please loop in the team on the call."
        )
        self.assertEqual(r["notes_paragraph_count"], 3)

    def test_paragraph_count_single_line(self):
        r = clean_notes(self.HIGH_INTENT)
        self.assertEqual(r["notes_paragraph_count"], 1)

    def test_paragraph_count_empty(self):
        r = clean_notes("")
        self.assertEqual(r["notes_paragraph_count"], 0)
