"""
Tests for Phase 12 endpoints covering Phases 5-8 output:
leads list/detail, clusters list/detail, CSV & JSON export.
"""

import io
import json
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "triage" / "sample_messy_leads.csv"


def _setup_job(client):
    """Upload + confirm mapping + process, returning the job_id."""
    content = SAMPLE_CSV.read_text(encoding="utf-8")
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = "sample_messy_leads.csv"

    resp = client.post(reverse("api:leads-upload"), {"file": buf}, format="multipart")
    job_id = resp.json()["job_id"]
    client.post(
        reverse("api:confirm-mapping", args=[job_id]),
        data=json.dumps({"mapping": {}}),
        content_type="application/json",
    )
    process = client.post(
        reverse("api:process-job", args=[job_id]),
        data=json.dumps({"use_llm": False}),
        content_type="application/json",
    )
    assert process.status_code == 200, process.content
    return job_id, process.json()


class PhaseEightApiTests(TestCase):
    def test_leads_list(self):
        job_id, report = _setup_job(self.client)
        resp = self.client.get(reverse("api:leads-list", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], report["summary"]["qualified"])
        # Default sort by score descending.
        scores = [l["scoring"]["final_score"] for l in body["leads"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_leads_list_tier_filter(self):
        job_id, _ = _setup_job(self.client)
        resp = self.client.get(reverse("api:leads-list", args=[job_id]), {"tier": "TIER1"})
        body = resp.json()
        self.assertTrue(all(l["scoring"]["tier"] == "TIER1" for l in body["leads"]))
        self.assertGreaterEqual(body["total"], 1)

    def test_lead_detail(self):
        job_id, report = _setup_job(self.client)
        first = report["qualified"][0]
        resp = self.client.get(reverse("api:lead-detail", args=[job_id, first["lead_id"]]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["lead_id"], first["lead_id"])
        self.assertIn("intelligence_features", body)
        self.assertIn("cluster_assignment", body)
        self.assertIn("scoring", body)
        self.assertIn("sales_strategy", body)

    def test_lead_detail_not_found(self):
        job_id, _ = _setup_job(self.client)
        resp = self.client.get(reverse("api:lead-detail", args=[job_id, "LEAD_999999"]))
        self.assertEqual(resp.status_code, 404)

    def test_clusters_list(self):
        job_id, report = _setup_job(self.client)
        resp = self.client.get(reverse("api:clusters-list", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        clusters = resp.json()["clusters"]
        self.assertEqual(len(clusters), report["summary"]["clusters_created"])
        for c in clusters:
            self.assertIn("cluster_id", c)
            self.assertIn("llm_analysis", c)
            self.assertIn("member_lead_ids", c)
            self.assertIn("representative_lead_ids", c)

    def test_cluster_detail(self):
        job_id, report = _setup_job(self.client)
        cluster_id = report["clusters"][0]["cluster_id"]
        resp = self.client.get(reverse("api:cluster-detail", args=[job_id, cluster_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["cluster_id"], cluster_id)

    def test_export_csv(self):
        job_id, _ = _setup_job(self.client)
        resp = self.client.get(reverse("api:export-csv", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        lines = resp.content.decode("utf-8").strip().splitlines()
        # Header + at least one data row.
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("contact_email", lines[0])

    def test_export_json(self):
        job_id, _ = _setup_job(self.client)
        resp = self.client.get(reverse("api:export-json", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp["Content-Type"])
        payload = json.loads(resp.content)
        self.assertIn("export_metadata", payload)
        self.assertIn("cluster_analyses", payload)
        self.assertIn("leads", payload)
        self.assertGreaterEqual(len(payload["leads"]), 1)

    def test_endpoints_require_processed_job(self):
        content = SAMPLE_CSV.read_text(encoding="utf-8")
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = "sample.csv"
        resp = self.client.post(reverse("api:leads-upload"), {"file": buf}, format="multipart")
        job_id = resp.json()["job_id"]
        # Not processed yet -> 400.
        resp = self.client.get(reverse("api:leads-list", args=[job_id]))
        self.assertEqual(resp.status_code, 400)

    def test_lead_status_get_defaults_null(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        resp = self.client.get(reverse("api:lead-status", args=[job_id, lead_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], None)

    def test_lead_status_set_and_get(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        resp = self.client.post(
            reverse("api:lead-status", args=[job_id, lead_id]),
            data=json.dumps({"status": "CONTACTED"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "CONTACTED")
        # Persists and survives reload.
        got = self.client.get(reverse("api:lead-status", args=[job_id, lead_id]))
        self.assertEqual(got.json()["status"], "CONTACTED")

    def test_lead_status_clear_with_null(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        self.client.post(
            reverse("api:lead-status", args=[job_id, lead_id]),
            data=json.dumps({"status": "SKIPPED"}),
            content_type="application/json",
        )
        resp = self.client.post(
            reverse("api:lead-status", args=[job_id, lead_id]),
            data=json.dumps({"status": None}),
            content_type="application/json",
        )
        self.assertEqual(resp.json()["status"], None)

    def test_lead_status_invalid_rejected(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        resp = self.client.post(
            reverse("api:lead-status", args=[job_id, lead_id]),
            data=json.dumps({"status": "NOT_A_STATUS"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_lead_statuses_map(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        self.client.post(
            reverse("api:lead-status", args=[job_id, lead_id]),
            data=json.dumps({"status": "CONTACTED"}),
            content_type="application/json",
        )
        resp = self.client.get(reverse("api:lead-statuses", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["statuses"].get(lead_id), "CONTACTED")

    def test_lead_status_not_found(self):
        job_id, _ = _setup_job(self.client)
        resp = self.client.post(
            reverse("api:lead-status", args=[job_id, "LEAD_999999"]),
            data=json.dumps({"status": "SKIPPED"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_lead_override_set_and_get(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        resp = self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "name", "value": "Gbenga"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["overrides"].get("name"), "Gbenga")
        got = self.client.get(reverse("api:lead-override", args=[job_id, lead_id]))
        self.assertEqual(got.json()["overrides"].get("name"), "Gbenga")

    def test_lead_override_invalid_field_rejected(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        resp = self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "not_a_field", "value": "x"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_lead_override_clear_with_null(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "title", "value": "CEO"}),
            content_type="application/json",
        )
        resp = self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "title", "value": None}),
            content_type="application/json",
        )
        self.assertEqual(resp.json()["overrides"], {})

    def test_lead_override_applied_on_rerun(self):
        """Override saved then pipeline re-run reflects the change in cleaned data."""
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "name", "value": "Gbenga"}),
            content_type="application/json",
        )
        process = self.client.post(
            reverse("api:process-job", args=[job_id]),
            data=json.dumps({"use_llm": False}),
            content_type="application/json",
        )
        self.assertEqual(process.status_code, 200)
        lead = next(l for l in process.json()["qualified"] if l.get("lead_id") == lead_id)
        self.assertEqual(lead["cleaned_data"]["name"], "Gbenga")
        self.assertEqual(lead["cleaned_data"]["name_data_quality"], "USER_OVERRIDE")

    def test_lead_override_map(self):
        job_id, report = _setup_job(self.client)
        lead_id = report["qualified"][0]["lead_id"]
        self.client.post(
            reverse("api:lead-override", args=[job_id, lead_id]),
            data=json.dumps({"field": "company", "value": "Acme"}),
            content_type="application/json",
        )
        resp = self.client.get(reverse("api:lead-overrides", args=[job_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["overrides"].get(lead_id, {}).get("company"), "Acme")
