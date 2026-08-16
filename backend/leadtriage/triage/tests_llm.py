"""
Test the OpenAI LLM call path (Phase 7) with a mocked OpenAI client,
plus prompt construction.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from triage.llm_analysis import (
    build_cluster_analysis_prompt,
    _extract_json,
    analyze_cluster_with_llm,
    _get_model,
    _get_api_key,
    ESTIMATED_COST_PER_CALL,
)


def _cluster():
    return {
        "cluster_id": "cluster_001",
        "cluster_name": "High-Intent Agencies",
        "member_lead_ids": ["LEAD_001168", "LEAD_001337"],
        "representative_lead_ids": ["LEAD_001168"],
        "avg_intelligence_score": 0.84,
        "avg_timeline_score": 0.88,
        "avg_authority_score": 0.90,
        "avg_budget_score": 0.78,
        "characteristics": {"primary_use_case": "Lead routing"},
        "cluster_signals_summary": ["Budget approved"],
    }


class LLMPromptTests(SimpleTestCase):
    def test_build_prompt_includes_samples(self):
        lead = {
            "lead_id": "LEAD_001168",
            "cleaned_data": {
                "name": "Ola",
                "company": "Pipegtm",
                "employees": 26,
                "title": "VP Growth",
                "email": "ola@pipegtm.co",
                "budget_monthly": 6000,
                "source": "LINKEDIN",
                "notes_analysis": {"notes": "Budget approved, wants to start ASAP."},
            },
            "intelligence_features": {},
        }
        sys_p, user_p = build_cluster_analysis_prompt(_cluster(), {"LEAD_001168": lead})
        self.assertIn("LEAD SAMPLE 1", user_p)
        self.assertIn("Pipegtm", user_p)
        self.assertIn("intent_level", user_p)
        self.assertIn("valid JSON", user_p)

    def test_budget_range_display(self):
        lead = {
            "lead_id": "LEAD_001168",
            "cleaned_data": {
                "budget_monthly": 7000,
                "budget_is_range": True,
                "budget_min": 6000,
                "budget_max": 8000,
            },
            "intelligence_features": {},
        }
        from triage.llm_analysis import _lead_sample
        sample = _lead_sample(lead)
        self.assertEqual(sample["Budget"], "$6,000/mo")


class LLMOpenAICallTests(SimpleTestCase):
    @patch("triage.llm_analysis._get_api_key", return_value="sk-test")
    @patch("triage.llm_analysis._get_model", return_value="gpt-4o-mini")
    def test_openai_call_path(self, mock_model, mock_key):
        mock_message = MagicMock()
        mock_message.content = json.dumps({
            "overall_assessment": {
                "cluster_name": "High-Intent Agencies",
                "intent_level": "HIGH",
                "intent_confidence": 0.95,
                "recommended_action": "CONTACT_NOW",
                "estimated_deal_probability": 0.80,
            },
            "common_characteristics": {"primary_pain_point": "Manual routing"},
            "urgency_assessment": {"urgency_level": "URGENT", "decision_timeline_weeks": "2-4"},
            "fit_assessment": {"overall_fit_score": 0.9},
            "conversation_strategy": {"conversation_starters": [{"starter": "X", "example": "Y"}]},
            "risk_factors": [{"risk": "Competition", "severity": "MEDIUM", "mitigation": "Demo"}],
            "next_steps": ["Call"],
        })

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=mock_message)]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        with patch("openai.OpenAI", return_value=mock_client):
            result = analyze_cluster_with_llm(_cluster(), {}, use_llm=True)

        self.assertEqual(result["analysis_source"], "openai")
        self.assertEqual(result["overall_assessment"]["intent_level"], "HIGH")
        self.assertEqual(result["overall_assessment"]["recommended_action"], "CONTACT_NOW")
        self.assertEqual(result["cluster_id"], "cluster_001")
        mock_client.chat.completions.create.assert_called_once()

    @patch("triage.llm_analysis._get_api_key", return_value="sk-test")
    def test_openai_failure_falls_back(self, mock_key):
        """If OpenAI raises, we should gracefully fall back to heuristic."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")

        with patch("openai.OpenAI", return_value=mock_client):
            result = analyze_cluster_with_llm(_cluster(), {}, use_llm=True)

        self.assertEqual(result["analysis_source"], "heuristic")
        self.assertEqual(result["analysis_cost_usd"], 0.0)

    def test_heuristic_analysis_carries_zero_cost(self):
        from triage.llm_analysis import _heuristic_cluster_analysis
        result = analyze_cluster_with_llm(_cluster(), {}, use_llm=False)
        self.assertEqual(result["analysis_source"], "heuristic")
        self.assertEqual(result["analysis_cost_usd"], 0.0)

    def test_openai_analysis_carries_per_call_cost(self):
        mock_message = MagicMock()
        mock_message.content = json.dumps({"overall_assessment": {"intent_level": "HIGH"}})
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=mock_message)]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        with patch("openai.OpenAI", return_value=mock_client):
            result = analyze_cluster_with_llm(_cluster(), {}, use_llm=True)

        self.assertEqual(result["analysis_source"], "openai")
        self.assertEqual(result["analysis_cost_usd"], ESTIMATED_COST_PER_CALL)

    def test_extract_json_strips_markdown(self):
        raw = '```json\n{"a": [1, 2, 3]}\n```'
        self.assertEqual(_extract_json(raw), {"a": [1, 2, 3]})

    def test_heuristic_low_intent_timeline_12_plus_does_not_crash(self):
        """Regression: avg_intel < 0.35 sets timeline '12+' which used to crash
        float('12+'). Must produce a numeric average_sales_cycle_weeks."""
        from triage.llm_analysis import _heuristic_cluster_analysis
        cluster = dict(_cluster())
        cluster["avg_intelligence_score"] = 0.20
        cluster["avg_timeline_score"] = 0.15
        result = _heuristic_cluster_analysis(cluster)
        self.assertEqual(result["overall_assessment"]["intent_level"], "NEGATIVE")
        self.assertEqual(result["urgency_assessment"]["decision_timeline_weeks"], "12+")
        self.assertEqual(result["success_metrics"]["average_sales_cycle_weeks"], 12.0)

    def test_heuristic_all_tiers_parse_cycle_weeks(self):
        from triage.llm_analysis import _heuristic_cluster_analysis
        for avg_intel in (0.75, 0.60, 0.40, 0.10):
            cluster = dict(_cluster())
            cluster["avg_intelligence_score"] = avg_intel
            cluster["avg_timeline_score"] = 0.5
            result = _heuristic_cluster_analysis(cluster)
            weeks = result["success_metrics"]["average_sales_cycle_weeks"]
            self.assertIsInstance(weeks, float)
            self.assertGreater(weeks, 0)

    def test_normalize_per_lead_to_cluster(self):
        """If LLM returns per-lead analysis (leads array), it gets normalized."""
        from triage.llm_analysis import _normalize_per_lead_to_cluster
        per_lead = {
            "leads": [
                {
                    "lead_id": "L1",
                    "intent_level": {"classification": "HIGH", "confidence": 0.9},
                    "primary_pain_point": "Manual lead routing",
                    "urgency_assessment": "URGENT",
                    "fit_assessment": {"fits": True, "reason": "Match"},
                    "recommended_action": "CONTACT_NOW",
                    "conversation_starters": ["Talk about automation"],
                    "risk_factors": "Budget concerns",
                    "typical_decision_timeline": "2-4 weeks",
                    "next_steps": "Schedule demo",
                },
                {
                    "lead_id": "L2",
                    "intent_level": {"classification": "MEDIUM", "confidence": 0.7},
                    "primary_pain_point": "Slow follow-ups",
                    "urgency_assessment": "SOON",
                    "fit_assessment": {"fits": True, "reason": "Match"},
                    "recommended_action": "CONTACT_NOW",
                    "conversation_starters": ["Discuss speed"],
                    "risk_factors": "Competition",
                    "typical_decision_timeline": "3-5 weeks",
                    "next_steps": "Send proposal",
                },
            ],
            "analysis_source": "openai",
        }
        result = _normalize_per_lead_to_cluster(per_lead)
        self.assertNotIn("leads", result)
        self.assertIn("overall_assessment", result)
        self.assertIn("urgency_assessment", result)
        self.assertIn("fit_assessment", result)
        self.assertIn("common_characteristics", result)
        self.assertIn("conversation_strategy", result)
        self.assertIn("risk_factors", result)
        self.assertIn("next_steps", result)
        self.assertIn("success_metrics", result)
        self.assertIn(result["overall_assessment"]["intent_level"], ("HIGH", "MEDIUM"))
        self.assertIn(result["overall_assessment"]["recommended_action"], ("CONTACT_NOW", "NURTURE"))
        self.assertIn(result["urgency_assessment"]["urgency_level"], ("URGENT", "SOON"))
        self.assertIsInstance(result["risk_factors"], list)
        self.assertIsInstance(result["next_steps"], list)

    def test_normalize_per_lead_missing_fields_ok(self):
        """Normalization handles missing fields gracefully."""
        from triage.llm_analysis import _normalize_per_lead_to_cluster
        sparse = {
            "leads": [
                {"lead_id": "L1"},
                {"lead_id": "L2", "intent_level": {"classification": "LOW"}},
            ],
        }
        result = _normalize_per_lead_to_cluster(sparse)
        self.assertIn("overall_assessment", result)
        self.assertIn("success_metrics", result)
