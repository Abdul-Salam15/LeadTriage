"""
Phase 4 tests: disqualification rules 1-6.
Each test mirrors a rule from the MD.
"""

from django.test import SimpleTestCase

from triage.disqualifier import disqualify_batch, evaluate_lead


def make_lead(notes_text, title="Owner", budget=None, title_score=0.95):
    return {
        "lead_id": "LEAD_TEST",
        "name": "Test",
        "title_decision_authority_score": title_score,
        "budget_monthly": budget,
        "notes_analysis": {
            "notes_cleaned": notes_text,
            "flagged_as": [],
        },
    }


class DisqualifierTests(SimpleTestCase):
    def test_rule1_spam(self):
        notes = {
            "notes_cleaned": "You have WON $1,000,000!!! Click here to claim.",
            "flagged_as": ["SPAM"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R1")
        self.assertEqual(r["recommendation"], "Remove from pipeline")

    def test_rule1_duplicate(self):
        notes = {
            "notes_cleaned": "(duplicate submission) We're a SEO agency.",
            "flagged_as": ["DUPLICATE"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R1")

    def test_rule2_not_buyer(self):
        notes = {
            "notes_cleaned": "Not looking to buy — I'm a developer looking for a role.",
            "flagged_as": ["NOT_BUYER"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R2")

    def test_rule2_wrong_fit(self):
        notes = {
            "notes_cleaned": "Offering offshore dev team at $5/hr.",
            "flagged_as": ["WRONG_FIT"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R2")

    def test_rule3_competitor(self):
        notes = {
            "notes_cleaned": "I actually run a competing automation agency.",
            "flagged_as": ["COMPETITOR"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R3")

    def test_rule4_low_priority(self):
        # Student (authority 0), no budget -> LOW_PRIORITY
        lead = make_lead("hi! CS student looking to learn", title_score=0.0, budget=None)
        notes = {"notes_cleaned": "hi! CS student looking to learn", "flagged_as": []}
        r = evaluate_lead(lead, notes)
        self.assertEqual(r["status"], "LOW_PRIORITY")
        self.assertEqual(r["applied_rule"], "R4")

    def test_rule4_authority_override(self):
        # authority 0, no budget, but says "I make the call" -> not low priority
        lead = make_lead("I make the call here.", title_score=0.0, budget=None)
        notes = {"notes_cleaned": "I make the call here.", "flagged_as": []}
        r = evaluate_lead(lead, notes)
        self.assertEqual(r["status"], "QUALIFIED")

    def test_rule5_vc_intro(self):
        notes = {
            "notes_cleaned": "VC here — wanting to intro you to a few portfolio companies. Not a direct buyer.",
            "flagged_as": ["NOT_DECISION_MAKER"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R5")

    def test_rule6_academic(self):
        notes = {
            "notes_cleaned": "Doing a university project on AI agencies, can I interview your founder?",
            "flagged_as": ["NOT_DECISION_MAKER"],
        }
        r = evaluate_lead(make_lead(""), notes)
        self.assertEqual(r["status"], "DISQUALIFIED")
        self.assertEqual(r["applied_rule"], "R6")

    def test_qualified_lead(self):
        lead = make_lead(
            "Budget approved, want to start ASAP. I make the call.",
            title="CEO",
            budget=6000,
        )
        notes = {
            "notes_cleaned": "Budget approved, want to start ASAP. I make the call.",
            "flagged_as": [],
        }
        r = evaluate_lead(lead, notes)
        self.assertEqual(r["status"], "QUALIFIED")

    def test_batch(self):
        leads = [
            make_lead("Budget approved, want to start."),
            make_lead("Not looking to buy.") | {"notes_analysis": {"notes_cleaned": "Not looking to buy.", "flagged_as": ["NOT_BUYER"]}},
            make_lead("hi! student, learning :)", title_score=0.0, budget=None) | {"notes_analysis": {"notes_cleaned": "hi! student, learning :)", "flagged_as": ["NOT_DECISION_MAKER"]}},
        ]
        result = disqualify_batch(leads)
        self.assertEqual(result["summary"]["qualified"], 1)
        self.assertEqual(result["summary"]["disqualified"], 1)
        self.assertEqual(result["summary"]["low_priority"], 1)
