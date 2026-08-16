"""
Tests for Phase 5 (intelligence features), Phase 6 (clustering),
Phase 7 (LLM analysis fallback), and Phase 8 (scoring).
"""

import json

from django.test import SimpleTestCase

from triage.clustering import build_feature_vector, cluster_leads, kmeans_cosine
from triage.intelligence import (
    authority_signals,
    budget_signals,
    combined_intelligence_score,
    company_fit_signals,
    competitive_position_signals,
    extract_intelligence,
    notes_quality_signals,
    timeline_signals,
    use_case_clarity_signals,
)
from triage.llm_analysis import _extract_json, analyze_cluster_with_llm
from triage.scoring import apply_cluster_insights, rank_leads, score_lead, tier_summary


def make_qualified_lead(overrides=None, notes=None):
    base = {
        "lead_id": "LEAD_001168",
        "name": "Ola",
        "email": "ola@pipegtm.co",
        "company": "Pipegtm",
        "title": "VP Growth",
        "title_decision_authority_score": 0.85,
        "title_decision_authority_level": "HIGH",
        "employees": 26,
        "employee_size_category": "Growing Company",
        "budget_monthly": 6000,
        "budget_is_disclosed": True,
        "budget_category": "MID_MARKET",
        "budget_data_quality": "EXACT",
        "budget_seriousness_score": 0.75,
        "source": "LINKEDIN",
        "source_quality_score": 0.80,
        "days_since_created": 2,
        "recency_category": "FRESH",
        "notes_analysis": {
            "notes": notes or "We're a agency, 26 people. Chasing follow-ups is eating our week. Budget approved, wants to start ASAP.",
            "extracted_signals": ["budget_approved", "timeline_asap", "i_make_the_call"],
            "extracted_use_cases": ["Follow-up Automation", "CRM Sync"],
            "extracted_pain_points": ["manual work", "time wasted"],
            "extracted_tools": ["Email", "WhatsApp"],
            "extracted_company_type": "Influencer Marketing Agency",
            "notes_length_words": 30,
            "notes_engagement_level": "HIGH",
            "notes_specificity": "HIGH",
            "notes_sentiment": "POSITIVE",
            "notes_quality_score": 0.85,
        },
    }
    if overrides:
        base.update(overrides)
    return base


class IntelligenceFeatureTests(SimpleTestCase):
    def test_budget_signals(self):
        lead = make_qualified_lead()
        s = budget_signals(lead, max_budget=15000)
        self.assertTrue(s["has_budget_mentioned"])
        self.assertEqual(s["budget_value"], 6000)
        self.assertEqual(s["budget_category"], "MID_MARKET")
        self.assertEqual(s["budget_confidence"], "HIGH")
        self.assertEqual(s["budget_seriousness_score"], 0.75)
        # normalized = 6000/15000 = 0.4
        self.assertAlmostEqual(s["budget_signals_feature_vector"][1], 0.4, places=3)

    def test_budget_signals_missing(self):
        lead = make_qualified_lead({"budget_monthly": None, "budget_is_disclosed": False})
        s = budget_signals(lead)
        self.assertFalse(s["has_budget_mentioned"])

    def test_timeline_signals_urgent(self):
        lead = make_qualified_lead()
        s = timeline_signals(lead)
        self.assertEqual(s["timeline_urgency_level"], "URGENT")
        self.assertEqual(s["urgency_score"], 0.90)
        self.assertEqual(s["recency_score"], 0.95)
        self.assertGreaterEqual(s["combined_timeline_score"], 0.9)

    def test_timeline_signals_flexible(self):
        lead = make_qualified_lead(
            notes="Just curious about automation, exploring options. Not sure what we need."
        )
        s = timeline_signals(lead)
        self.assertEqual(s["timeline_urgency_level"], "FLEXIBLE")

    def test_authority_signals(self):
        lead = make_qualified_lead()
        s = authority_signals(lead)
        self.assertEqual(s["title_authority_score"], 0.85)
        self.assertTrue(s["notes_mention_authority"])  # i_make_the_call signal
        self.assertEqual(s["authority_confidence"], "HIGH")

    def test_use_case_clarity(self):
        lead = make_qualified_lead()
        s = use_case_clarity_signals(lead)
        self.assertEqual(s["use_case_specificity"], "CRYSTAL_CLEAR")
        self.assertGreaterEqual(s["clarity_score"], 0.5)

    def test_competitive_position_ready(self):
        lead = make_qualified_lead()
        s = competitive_position_signals(lead)
        self.assertEqual(s["buying_stage"], "READY_TO_BUY")

    def test_competitive_position_comparing(self):
        lead = make_qualified_lead(
            notes="Comparing a few options for automating lead routing.",
            overrides={
                "notes_analysis": {
                    "notes": "Comparing a few options for automating lead routing.",
                    "extracted_signals": ["comparing_options"],
                    "extracted_use_cases": ["Lead Routing"],
                    "extracted_pain_points": ["manual work"],
                    "extracted_tools": [],
                    "extracted_company_type": "Agency",
                    "notes_length_words": 10,
                    "notes_engagement_level": "LOW",
                    "notes_specificity": "MEDIUM",
                    "notes_sentiment": "NEUTRAL",
                    "notes_quality_score": 0.4,
                }
            },
        )
        s = competitive_position_signals(lead)
        self.assertEqual(s["buying_stage"], "ACTIVE_EVALUATION")

    def test_company_fit(self):
        lead = make_qualified_lead()
        s = company_fit_signals(lead)
        self.assertEqual(s["company_size"], 26)
        # 6000/26 = ~230 per employee -> high fit
        self.assertGreaterEqual(s["budget_size_fit"], 0.7)
        self.assertEqual(s["company_type"], "Influencer Marketing Agency")
        self.assertGreaterEqual(s["industry_fit"], 0.8)

    def test_notes_quality(self):
        lead = make_qualified_lead()
        s = notes_quality_signals(lead)
        self.assertEqual(s["word_count"], 30)
        self.assertEqual(s["engagement_level"], "HIGH")
        self.assertIn("Email", s["tools_mentioned"])
        self.assertGreaterEqual(s["quality_score"], 0.8)

    def test_combined_intelligence(self):
        lead = make_qualified_lead()
        intel = extract_intelligence(lead)
        combined = combined_intelligence_score(intel)
        self.assertGreaterEqual(combined["combined_intelligence_score"], 0.7)
        self.assertIn("budget_score", combined["intelligence_score_components"])

    def test_extract_intelligence_batch_max_budget(self):
        # batch normalization should scale budget by max in dataset
        leads = [make_qualified_lead({"lead_id": "LEAD_A", "budget_monthly": 3000}),
                 make_qualified_lead({"lead_id": "LEAD_B", "budget_monthly": 12000})]
        from triage.intelligence import extract_intelligence_batch
        result = extract_intelligence_batch(leads)
        # normalized = 12000/12000 = 1.0
        self.assertAlmostEqual(
            result[1]["intelligence_features"]["budget_signals"]["budget_signals_feature_vector"][1], 1.0, places=3
        )


class ClusteringTests(SimpleTestCase):
    def test_kmeans_runs(self):
        vectors = [
            [0, 0, 1.0, 0.5, 0.2, 0.8, 0.9],
            [0, 0, 1.0, 0.5, 0.2, 0.8, 0.9],
            [3, 4, 0.0, 0.1, 3.0, 0.3, 0.2],
            [3, 4, 0.0, 0.1, 3.0, 0.3, 0.2],
        ]
        assignments, centroids = kmeans_cosine(vectors, k=2)
        self.assertEqual(len(assignments), 4)
        self.assertEqual(len(centroids), 2)

    def test_cluster_leads_single_group(self):
        leads = [
            {"lead_id": "LEAD_001168", "cleaned_data": make_qualified_lead(),
             "intelligence_features": extract_intelligence(make_qualified_lead())},
            {"lead_id": "LEAD_001337", "cleaned_data": make_qualified_lead({"lead_id": "LEAD_001337", "budget_monthly": 15000}),
             "intelligence_features": extract_intelligence(make_qualified_lead({"budget_monthly": 15000}))},
        ]
        result = cluster_leads(leads, k=1)
        self.assertEqual(result["k"], 1)
        self.assertEqual(len(result["clusters"]), 1)
        cluster = result["clusters"][0]
        self.assertEqual(len(cluster["member_lead_ids"]), 2)
        self.assertEqual(len(cluster["representative_lead_ids"]), 2)
        self.assertIn("cluster_name", cluster)

    def test_cluster_ids_renumbered_by_score(self):
        """Cluster ids must be re-numbered so cluster_001 = highest score,
        and assignments match the re-numbered ids."""
        leads = []
        # Three distinct budget tiers, two leads each -> k=3 cleanly forms
        # three clusters so the re-numbering invariant is fully exercised.
        for i, budget in enumerate([1000, 1000, 8000, 8000, 30000, 30000]):
            base = make_qualified_lead({
                "lead_id": f"LEAD_{i:04d}",
                "company": f"Co{i}",
                "budget_monthly": budget,
            })
            leads.append({
                "lead_id": f"LEAD_{i:04d}",
                "cleaned_data": base,
                "intelligence_features": extract_intelligence(base),
            })
        result = cluster_leads(leads, k=3)
        clusters = result["clusters"]
        self.assertGreaterEqual(len(clusters), 2)
        # Sorted by score descending.
        scores = [c["avg_intelligence_score"] for c in clusters]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Ids sequential starting at cluster_001.
        self.assertEqual(
            [c["cluster_id"] for c in clusters],
            [f"cluster_{i:03d}" for i in range(1, len(clusters) + 1)],
        )
        # Assignments map to re-numbered ids.
        for c in clusters:
            for lid in c["member_lead_ids"]:
                self.assertEqual(result["assignments"][lid], c["cluster_id"])

    def test_build_feature_vector_shape(self):
        lead = make_qualified_lead()
        intel = extract_intelligence(lead)
        vec = build_feature_vector({"cleaned_data": lead, "intelligence_features": intel})
        # 2 (size, budget) + 12 use cases + 1 industry + 1 stage + intel + authority
        self.assertEqual(len(vec), 2 + 12 + 1 + 1 + 1 + 1)


class LLMAnalysisTests(SimpleTestCase):
    def test_extract_json_plain(self):
        self.assertEqual(_extract_json('{"a": 1}'), {"a": 1})

    def test_extract_json_fenced(self):
        raw = '```json\n{"intent": "HIGH"}\n```'
        self.assertEqual(_extract_json(raw), {"intent": "HIGH"})

    def test_extract_json_noisy(self):
        raw = 'Here is the analysis:\n{"fit": 0.88, "notes": "done"}\nHope this helps.'
        self.assertEqual(_extract_json(raw)["fit"], 0.88)

    def test_heuristic_analysis(self):
        cluster = {
            "cluster_id": "cluster_001",
            "cluster_name": "High-Intent Agencies",
            "member_lead_ids": ["LEAD_001168"],
            "representative_lead_ids": ["LEAD_001168"],
            "avg_intelligence_score": 0.84,
            "avg_timeline_score": 0.88,
            "avg_authority_score": 0.90,
            "avg_budget_score": 0.78,
            "characteristics": {"primary_use_case": "Lead routing"},
            "cluster_signals_summary": ["Budget approved"],
        }
        analysis = analyze_cluster_with_llm(cluster, {}, use_llm=False)
        self.assertEqual(analysis["overall_assessment"]["intent_level"], "HIGH")
        self.assertEqual(analysis["overall_assessment"]["recommended_action"], "CONTACT_NOW")
        self.assertEqual(analysis["analysis_source"], "heuristic")
        self.assertEqual(analysis["urgency_assessment"]["urgency_level"], "URGENT")

    def test_heuristic_intent_from_intel_not_timeline(self):
        # High intel but stale timeline -> still HIGH intent (urgency separate).
        cluster = {
            "cluster_id": "cluster_001",
            "cluster_name": "High-Intent Agencies",
            "member_lead_ids": ["LEAD_001168"],
            "representative_lead_ids": ["LEAD_001168"],
            "avg_intelligence_score": 0.80,
            "avg_timeline_score": 0.30,
            "avg_authority_score": 0.90,
            "avg_budget_score": 0.78,
            "characteristics": {"primary_use_case": "Lead routing"},
            "cluster_signals_summary": ["Budget approved"],
        }
        analysis = analyze_cluster_with_llm(cluster, {}, use_llm=False)
        self.assertEqual(analysis["overall_assessment"]["intent_level"], "HIGH")
        self.assertEqual(analysis["overall_assessment"]["recommended_action"], "CONTACT_NOW")
        self.assertEqual(analysis["urgency_assessment"]["urgency_level"], "FLEXIBLE")


class ScoringTests(SimpleTestCase):
    def _cluster(self):
        return {
            "cluster_id": "cluster_001",
            "cluster_name": "High-Intent Agencies",
            "member_lead_ids": ["LEAD_001168"],
            "avg_intelligence_score": 0.84,
            "avg_budget_score": 0.78,
            "avg_timeline_score": 0.88,
            "avg_authority_score": 0.90,
            "llm_analysis": {
                "overall_assessment": {
                    "intent_level": "HIGH",
                    "intent_confidence": 0.95,
                    "recommended_action": "CONTACT_NOW",
                    "estimated_deal_probability": 0.75,
                },
                "common_characteristics": {"primary_pain_point": "Manual routing"},
                "urgency_assessment": {"urgency_level": "URGENT", "decision_timeline_weeks": "2-4"},
                "fit_assessment": {"fit_explanation": "Excellent fit"},
                "conversation_strategy": {"conversation_starters": [{"starter": "Pain", "example": "Say pain"}]},
                "risk_factors": [{"risk": "Competition"}],
                "next_steps": ["Call"],
            },
        }

    def test_score_lead_tier1(self):
        lead = {"lead_id": "LEAD_001168", "cleaned_data": make_qualified_lead(),
                "intelligence_features": extract_intelligence(make_qualified_lead())}
        scoring = score_lead(lead, self._cluster())
        self.assertEqual(scoring["tier"], "TIER1")
        self.assertGreaterEqual(scoring["final_score"], 85)
        self.assertIn("budget_adjustment", scoring["individual_adjustments"])
        self.assertLessEqual(scoring["final_score"], 100)

    def test_score_lead_tier5(self):
        weak_cluster = {
            "cluster_id": "cluster_003",
            "cluster_name": "Low-Priority / Educational",
            "member_lead_ids": ["LEAD_001168"],
            "avg_intelligence_score": 0.25,
            "avg_budget_score": 0.15,
            "avg_timeline_score": 0.20,
            "avg_authority_score": 0.10,
            "llm_analysis": {
                "overall_assessment": {
                    "intent_level": "LOW",
                    "intent_confidence": 0.5,
                    "recommended_action": "NURTURE",
                    "estimated_deal_probability": 0.10,
                },
                "common_characteristics": {"primary_pain_point": "Learning"},
                "urgency_assessment": {"urgency_level": "LOW", "decision_timeline_weeks": "12+"},
                "fit_assessment": {"fit_explanation": "Poor fit"},
                "conversation_strategy": {"conversation_starters": []},
                "risk_factors": [],
                "next_steps": [],
            },
        }
        low_lead = make_qualified_lead({
            "budget_monthly": None,
            "budget_is_disclosed": False,
            "title_decision_authority_score": 0.0,
            "days_since_created": 120,
            "recency_category": "STALE",
            "notes_analysis": {
                "notes": "Hi, just learning about automation tools, not sure what we need yet.",
                "extracted_signals": [],
                "extracted_use_cases": [],
                "extracted_pain_points": [],
                "extracted_tools": [],
                "extracted_company_type": None,
                "notes_length_words": 12,
                "notes_engagement_level": "LOW",
                "notes_specificity": "LOW",
                "notes_sentiment": "NEUTRAL",
                "notes_quality_score": 0.2,
            },
        })
        lead = {"lead_id": "LEAD_001168", "cleaned_data": low_lead,
                "intelligence_features": extract_intelligence(low_lead)}
        scoring = score_lead(lead, weak_cluster)
        self.assertEqual(scoring["tier"], "TIER5")
        self.assertLessEqual(scoring["final_score"], 39)

    def test_apply_cluster_insights_and_rank(self):
        lead1 = {"lead_id": "LEAD_001168", "cleaned_data": make_qualified_lead(),
                 "intelligence_features": extract_intelligence(make_qualified_lead())}
        lead2 = {"lead_id": "LEAD_001337", "cleaned_data": make_qualified_lead({"budget_monthly": 15000}),
                 "intelligence_features": extract_intelligence(make_qualified_lead({"budget_monthly": 15000}))}
        cluster = self._cluster()
        cluster["member_lead_ids"] = ["LEAD_001168", "LEAD_001337"]
        cluster["avg_intelligence_score"] = 0.8
        assignments = {"LEAD_001168": "cluster_001", "LEAD_001337": "cluster_001"}

        apply_cluster_insights([lead1, lead2], [cluster], assignments)
        ranked = rank_leads([lead1, lead2])

        self.assertIn("cluster_assignment", ranked[0])
        self.assertEqual(ranked[0]["cluster_assignment"]["cluster_id"], "cluster_001")
        self.assertIn("scoring", ranked[0])
        self.assertIn("analysis_summary", ranked[0])
        self.assertIn("sales_strategy", ranked[0])
        self.assertIn("rank", ranked[0])

    def test_tier_summary(self):
        cluster = self._cluster()
        cluster["member_lead_ids"] = ["LEAD_001168", "LEAD_001337"]
        cluster["avg_intelligence_score"] = 0.8
        assignments = {"LEAD_001168": "cluster_001", "LEAD_001337": "cluster_001"}

        lead1 = {"lead_id": "LEAD_001168", "cleaned_data": make_qualified_lead(),
                 "intelligence_features": extract_intelligence(make_qualified_lead())}
        lead2 = {"lead_id": "LEAD_001337", "cleaned_data": make_qualified_lead({"budget_monthly": 15000}),
                 "intelligence_features": extract_intelligence(make_qualified_lead({"budget_monthly": 15000}))}
        apply_cluster_insights([lead1, lead2], [cluster], assignments)
        rank_leads([lead1, lead2])

        summary = tier_summary([lead1, lead2])
        self.assertIn("TIER1", summary)
        self.assertEqual(summary["TIER1"]["count"], 2)
        self.assertIn("avg_score", summary["TIER1"])
        self.assertIn("total_pipeline_value_monthly", summary["TIER1"])
        self.assertEqual(summary["TIER1"]["action"], "CONTACT WITHIN 48 HOURS")
        self.assertGreaterEqual(summary["TIER1"]["total_pipeline_value_monthly"], 20000)
