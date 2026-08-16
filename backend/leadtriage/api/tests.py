"""
Phase 1 smoke tests: upload + job status endpoints.
"""

import io
import json

from django.test import TestCase
from django.urls import reverse

from triage.upload_service import load_job


class UploadEndpointTests(TestCase):
    def _make_csv(self, content: str, name: str = "leads.csv") -> io.BytesIO:
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = name
        return buf

    def test_upload_valid_csv_returns_job(self):
        csv_content = (
            "lead_id,created,name,email,company,employees,website,title,source,monthly_budget,notes\r\n"
            "L-1369,06/28/2024,Gbenga,gbenga@luxauto.io,LuxAuto,,luxauto.io,,webform,,Not looking to buy\r\n"
            "L-1168,2024-06-08,Ola,ola@pipegtm.co,PipeGTM,,pipegtm.co,VP Growth,linkedin,$6k/mo,Want it automated\r\n"
        )
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv(csv_content)},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "awaiting_column_mapping")
        self.assertEqual(data["preview"]["row_count"], 2)
        self.assertEqual(
            data["preview"]["detected_columns"][0],
            "lead_id",
        )
        self.assertIn("job_id", data)

        job = load_job(data["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "awaiting_column_mapping")

    def test_upload_rejects_non_csv_extension(self):
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv("a,b\n1,2\n", name="data.txt")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_binary_content(self):
        binary = io.BytesIO(b"\x00\x01\x02\xff\xfe\xfd" * 1000)
        binary.name = "leads.csv"
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": binary},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_missing_file(self):
        response = self.client.post(reverse("api:leads-upload"))
        self.assertEqual(response.status_code, 400)

    def test_job_detail_returns_state(self):
        csv_content = "name,email\nGbenga,g@x.com\n"
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv(csv_content)},
            format="multipart",
        )
        job_id = response.json()["job_id"]

        detail = self.client.get(reverse("api:job-detail", args=[job_id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job_id"], job_id)

    def test_job_detail_404(self):
        detail = self.client.get(reverse("api:job-detail", args=["missing-job"]))
        self.assertEqual(detail.status_code, 404)

    def test_upload_returns_column_mapping(self):
        csv_content = "lead_id,created,name,email\nL-1,06/28/2024,Gbenga,g@x.com\n"
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv(csv_content)},
            format="multipart",
        )
        data = response.json()
        mapping = data["column_mapping"]
        by_header = {m["header"]: m for m in mapping["mappings"]}
        self.assertEqual(by_header["lead_id"]["mapped_to"], "lead_id")
        self.assertEqual(by_header["created"]["mapped_to"], "created_date")

    def test_confirm_mapping(self):
        csv_content = "name,email,mystery_col\nGbenga,g@x.com,foo\n"
        response = self.client.post(
            reverse("api:leads-upload"),
            {"file": self._make_csv(csv_content)},
            format="multipart",
        )
        job_id = response.json()["job_id"]

        confirm = self.client.post(
            reverse("api:confirm-mapping", args=[job_id]),
            data=json.dumps({"mapping": {"mystery_col": "__ignore__"}}),
            content_type="application/json",
        )
        self.assertEqual(confirm.status_code, 200)
        body = confirm.json()
        self.assertEqual(body["unmapped"], [])
        self.assertNotIn("mystery_col", body["mapped_fields"])

        job = load_job(job_id)
        self.assertEqual(job.status, "mapping_confirmed")
