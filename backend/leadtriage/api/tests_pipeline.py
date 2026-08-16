"""
End-to-end pipeline test: upload -> detect columns -> confirm mapping
-> process (Phase 3 clean + Phase 4 disqualify) -> verify results.
"""

import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from triage.upload_service import load_job

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "triage" / "sample_messy_leads.csv"


class PipelineEndToEndTests(TestCase):
    def _make_csv(self, name="sample_messy_leads.csv") -> io.BytesIO:
        content = SAMPLE_CSV.read_text(encoding="utf-8")
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = name
        return buf

    def test_full_pipeline(self):
        # Phase 1: upload
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        job_id = data["job_id"]
        self.assertEqual(data["preview"]["row_count"], 15)

        # Phase 2: mapping auto-detected, confirm as-is
        confirm = self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["unmapped"], [])

        # Phase 3+4: process (heuristics — deterministic, no live LLM calls).
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 200)
        report = process.json()

        summary = report["summary"]
        self.assertEqual(summary["total"], 15)
        self.assertGreaterEqual(summary["qualified"], 5)
        self.assertGreaterEqual(summary["disqualified"], 4)
        self.assertGreaterEqual(summary["low_priority"], 1)

        # Verify a known spam lead is disqualified.
        disq_ids = [d.get("lead_id") for d in report["disqualified"]]
        self.assertIn("L-1029", disq_ids)

        # Verify a high-intent lead is qualified.
        qual_ids = [q.get("lead_id") for q in report["qualified"]]
        self.assertIn("L-1168", qual_ids)

        # Verify the VC intro lead is disqualified with the R5 reason.
        vc = next(d for d in report["disqualified"] if d.get("lead_id") == "L-1326")
        self.assertEqual(vc["disqualification_reason"], "VC/Portfolio company intro, not direct buyer")

        # Verify the junior marketer falls to low priority (R4).
        low_ids = [d.get("lead_id") for d in report["low_priority"]]
        self.assertIn("L-1388", low_ids)

        # Spot check cleaned data on the qualified Ola lead.
        ola = next(q for q in report["qualified"] if q.get("lead_id") == "L-1168")
        cleaned = ola["cleaned_data"]
        self.assertEqual(cleaned["name"], "Ola")
        self.assertEqual(cleaned["company"], "Pipegtm")
        self.assertEqual(cleaned["title"], "VP")
        self.assertEqual(cleaned["budget_monthly"], 6000)
        self.assertEqual(cleaned["source"], "LINKEDIN")
        self.assertEqual(cleaned["email"], "ola@pipegtm.co")
        self.assertIn("budget_approved", cleaned["notes_analysis"]["extracted_signals"])

        # Phase 5: intelligence features attached.
        intel = ola["intelligence_features"]
        self.assertIn("budget_signals", intel)
        self.assertIn("combined_intelligence", intel)
        self.assertTrue(intel["budget_signals"]["has_budget_mentioned"])

        # Phase 6: clusters created.
        self.assertGreaterEqual(summary["clusters_created"], 1)
        self.assertEqual(report["llm_calls_made"], summary["clusters_created"])
        for cluster in report["clusters"]:
            self.assertIn("cluster_id", cluster)
            self.assertIn("representative_lead_ids", cluster)

        # LLM cost: heuristic path made no real OpenAI calls, so cost is zero.
        self.assertIn("processing_cost_usd", summary)
        self.assertEqual(summary["processing_cost_usd"], 0)

        # Phase 7: LLM (heuristic) analysis attached to clusters.
        self.assertIn("llm_analysis", report["clusters"][0])
        self.assertEqual(report["clusters"][0]["llm_analysis"]["analysis_source"], "heuristic")

        # Phase 8: cluster assignment + scoring + rank on each lead.
        for lead in report["qualified"]:
            self.assertIn("cluster_assignment", lead)
            self.assertIn("scoring", lead)
            self.assertIn("rank", lead)
            self.assertIn("analysis_summary", lead)
            self.assertIn("sales_strategy", lead)
            self.assertLessEqual(lead["scoring"]["final_score"], 100)
        # Scores sorted descending by rank.
        scores = [l["scoring"]["final_score"] for l in report["qualified"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_company_dedup_flags_variants(self):
        """'LuxAuto' and 'Lux Auto' share a slug; the later row is flagged."""
        rows = [
            ["lead_id", "created_date", "name", "email", "company", "employees", "website", "title", "source", "monthly_budget", "notes"],
            ["L-9001", "2024-01-10", "Jane", "jane@luxauto.io", "LuxAuto", "50", "luxauto.io", "Marketing Manager", "LinkedIn", "8000", "High budget, ready to buy"],
            ["L-9002", "2024-01-11", "Bob", "bob@luxauto.com", "Lux Auto", "60", "luxauto.com", "Sales VP", "Referral", "5000", "Interested in a demo"],
        ]
        csv_bytes = io.BytesIO(("\n".join(",".join(r) for r in rows)).encode("utf-8"))
        csv_bytes.name = "dedup.csv"

        resp = self.client.post(reverse("api:leads-upload"), {"file": csv_bytes}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        job_id = resp.json()["job_id"]
        confirm = self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        self.assertEqual(confirm.status_code, 200)
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 200)
        report = process.json()

        by_id = {}
        for group in ("qualified", "disqualified", "low_priority"):
            for lead in report.get(group, []):
                by_id[lead["lead_id"]] = lead["cleaned_data"]

        jane = by_id["L-9001"]
        bob = by_id["L-9002"]
        self.assertEqual(jane["company_slug"], "luxauto")
        self.assertNotIn("company_duplicate_of", jane)
        self.assertEqual(bob["company_slug"], "luxauto")
        self.assertEqual(bob["company_duplicate_of"], jane["company"])

    def test_process_requires_confirmation(self):
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        process = self.client.post(reverse("api:process-job", args=[job_id]))
        self.assertEqual(process.status_code, 400)

    def test_process_use_llm_false_forces_heuristics(self):
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 200)
        for cluster in process.json()["clusters"]:
            self.assertEqual(cluster["llm_analysis"]["analysis_source"], "heuristic")

    def test_process_use_llm_must_be_boolean(self):
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": "yes"}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 400)

    def test_results_endpoint(self):
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )

        results = self.client.get(reverse("api:job-results", args=[job_id]))
        self.assertEqual(results.status_code, 200)
        body = results.json()
        self.assertEqual(body["summary"]["total"], 15)

    def _upload_and_process(self, csv_bytes, name="leads.csv"):
        buf = io.BytesIO(csv_bytes)
        buf.name = name
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": buf},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 200)
        return process.json()

    def test_missing_columns_flagged_end_to_end(self):
        """Phase 13: CSV without website/title -> missing_fields flagged, processing continues."""
        csv_bytes = (
            "lead_id,created,name,email,company,employees,source,monthly_budget,notes\n"
            "L1,2024-06-08,Ola,ola@pipegtm.co,PipeGTM,26,linkedin,$6k/mo,"
            "Budget approved, wants to start ASAP.\n"
        ).encode("utf-8")
        report = self._upload_and_process(csv_bytes, name="no_website_title.csv")
        self.assertEqual(report["summary"]["total"], 1)
        self.assertIn("website", report["summary"]["missing_fields"])
        self.assertIn("title", report["summary"]["missing_fields"])
        # Pipeline still produced a qualified lead.
        self.assertEqual(report["summary"]["qualified"], 1)
        lead = report["qualified"][0]
        self.assertEqual(lead["cleaned_data"]["name"], "Ola")
        self.assertIn("missing_fields", lead["cleaned_data"])
        self.assertIn("website", lead["cleaned_data"]["missing_fields"])

    def test_non_english_notes_flagged_end_to_end(self):
        """Phase 13: non-English notes flagged but still processed."""
        csv_bytes = (
            'lead_id,created,name,email,company,employees,title,source,monthly_budget,website,notes\n'
            'L2,2024-06-08,Jean,jean@mediacorp.fr,MediaCorp,40,CMO,linkedin,$8k/mo,mediacorp.fr,'
            '"Bonjour, nous voulons automatiser notre prospection, merci beaucoup."\n'
        ).encode("utf-8")
        report = self._upload_and_process(csv_bytes, name="french.csv")
        self.assertEqual(report["summary"]["total"], 1)
        lead = report["qualified"][0]
        notes = lead["cleaned_data"]["notes_analysis"]
        self.assertTrue(notes["notes_is_non_english"])
        self.assertEqual(notes["notes_language"], "FRENCH")
        # Still qualified (non-English alone is not a disqualifier).
        self.assertEqual(report["summary"]["qualified"], 1)

    def test_export_json_has_summary_statistics(self):
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        exported = self.client.get(reverse("api:export-json", args=[job_id]))
        self.assertEqual(exported.status_code, 200)
        body = json.loads(exported.content)
        self.assertIn("export_metadata", body)
        self.assertIn("summary_statistics", body)
        self.assertIn("tier_summary", body)
        self.assertIn("total_pipeline_value_tier1_only", body["summary_statistics"])
        # LLM cost surfaces in the export metadata.
        self.assertIn("processing_cost_usd", body["export_metadata"])
        self.assertEqual(body["export_metadata"]["processing_cost_usd"], 0)

    def test_upload_preview_counts_full_file_over_64kb(self):
        """Regression: files larger than the 64KB peek were counted only from
        the first chunk, so row_count was wrong (e.g. 318 vs 519)."""
        header = "lead_id,created,name,email,company,employees,website,title,source,monthly_budget,notes\n"
        row = "L1,2024-06-08,Ola,ola@pipegtm.co,PipeGTM,26,pipegtm.co,VP Growth,linkedin,$6k/mo,Budget approved.\n"
        # ~800 rows well over 64KB total.
        content = header + row * 800
        self.assertGreater(len(content.encode("utf-8")), 65536)
        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": io.BytesIO(content.encode("utf-8"))},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["preview"]["row_count"], 800)

    def test_pipeline_computes_positive_llm_cost_when_openai_used(self):
        """When clusters are analyzed by OpenAI, processing_cost_usd > 0."""
        def fake_analyze(clusters, qualified, use_llm=None, job_id=None):
            for cluster in clusters:
                cluster["llm_analysis"] = {
                    "analysis_source": "openai",
                    "analysis_cost_usd": 0.002,
                    "overall_assessment": {
                        "intent_level": "HIGH",
                        "intent_confidence": 0.9,
                        "recommended_action": "CONTACT_NOW",
                        "estimated_deal_probability": 0.7,
                        "estimated_average_deal_value": "$7,500/month",
                    },
                    "common_characteristics": {"primary_pain_point": "Manual routing"},
                    "urgency_assessment": {"urgency_level": "URGENT", "decision_timeline_weeks": "2-4"},
                    "fit_assessment": {"overall_fit_score": 0.85},
                    "conversation_strategy": {"conversation_starters": []},
                    "risk_factors": [],
                    "next_steps": ["Call"],
                    "success_metrics": {"win_rate_for_this_cluster": 0.7, "average_sales_cycle_weeks": 3},
                }
            return clusters

        resp = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv()},
            format="multipart",
        )
        job_id = resp.json()["job_id"]
        self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {}}),
            content_type="application/json",
        )
        with patch("triage.pipeline.analyze_clusters", side_effect=fake_analyze):
            process = self.client.post(
                reverse("api:process-job", args=[job_id]),
                data=json.dumps({"use_llm": True}),
                content_type="application/json",
            )
        self.assertEqual(process.status_code, 200)
        summary = process.json()["summary"]
        self.assertGreater(summary["processing_cost_usd"], 0)
        self.assertEqual(summary["llm_calls_made"], summary["clusters_created"])

    def test_pipeline_completes_with_low_intent_cluster(self):
        """Regression: a dataset with a LOW-intent cluster (timeline '12+')
        must not crash in Phase 7 heuristic analysis."""
        header = "lead_id,created,name,email,company,employees,website,title,source,monthly_budget,notes\n"
        row = ("L{id},2024-06-08,Person{id},p{id}@co.com,Co{id},5,co{id}.com,,webform,,\""
               "small local business, not an agency, wants a cheap chatbot. budget way below range.\"\n")
        content = header + "".join(row.format(id=i) for i in range(120))
        report = self._upload_and_process(content.encode("utf-8"), name="low_intent.csv")
        self.assertGreaterEqual(report["summary"]["total"], 100)
        self.assertGreaterEqual(report["summary"]["clusters_created"], 1)
        # No cluster analysis should carry an unparseable sales cycle.
        for cluster in report["clusters"]:
            sm = cluster["llm_analysis"]["success_metrics"]
            self.assertIsNotNone(sm["average_sales_cycle_weeks"])
            self.assertGreater(sm["average_sales_cycle_weeks"], 0)
