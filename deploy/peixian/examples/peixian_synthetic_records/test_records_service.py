from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("peixian_synthetic_records_service", ROOT / "records_service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class RecordsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.key_path = Path(cls.temp.name) / "records.key"
        cls.key = "synthetic-records-test-key-0001"
        cls.key_path.write_text(cls.key, encoding="utf-8")
        cls.previous = os.environ.get("PEIXIAN_RECORDS_KEY_FILE")
        os.environ["PEIXIAN_RECORDS_KEY_FILE"] = str(cls.key_path)
        cls.server = service.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        if cls.previous is None:
            os.environ.pop("PEIXIAN_RECORDS_KEY_FILE", None)
        else:
            os.environ["PEIXIAN_RECORDS_KEY_FILE"] = cls.previous
        cls.temp.cleanup()

    def request(self, method, path, body=None, authorization=True, content_type="application/json"):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": content_type}
        if authorization:
            headers["Authorization"] = "Bearer " + self.key
        request = Request(self.base + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health_requires_the_fixed_service_key(self):
        self.assertEqual(self.request("GET", "/health", authorization=False), (401, {"error": "unauthorized"}))
        self.assertEqual(self.request("GET", "/health", authorization=True), (200, {"ok": True, "synthetic": True}))

    def test_every_module_returns_a_complete_synthetic_snapshot(self):
        required = {"schema_version", "synthetic", "module", "snapshot_id", "scope", "data_status", "records", "returned_count", "total_count", "has_more", "missing_sources", "errors", "rule_version", "rule_status"}
        for module in service.MODULES:
            with self.subTest(module=module):
                status, response = self.request("POST", "/v1/demo/records/query", {"module": module})
                self.assertEqual(status, 200)
                self.assertTrue(required.issubset(response))
                self.assertTrue(response["synthetic"])
                self.assertEqual(response["module"], module)
                self.assertEqual(response["data_status"], "complete")
                self.assertFalse(response["has_more"])
                self.assertEqual(response["returned_count"], len(response["records"]))
                self.assertEqual(response["total_count"], len(response["records"]))
                self.assertNotIn("scenario", response)
                for record in response["records"]:
                    self.assertTrue(record["record_id"].startswith("DEMO-"))
                    self.assertTrue({"record_id", "source_type", "group_ref", "member_ref"}.issubset(record))

    def test_only_the_exact_query_contract_is_accepted(self):
        invalid = (
            {},
            {"module": "unknown"},
            {"module": "funds", "scenario": "normal"},
            {"module": "funds", "page": 1},
            {"module": "funds", "time_range": "2026"},
            {"module": "funds", "limit": 1},
        )
        for request in invalid:
            with self.subTest(request=request):
                self.assertEqual(self.request("POST", "/v1/demo/records/query", request), (400, {"error": "invalid_request"}))
        self.assertEqual(self.request("POST", "/wrong", {"module": "funds"}), (404, {"error": "not_found"}))
        self.assertEqual(self.request("GET", "/v1/demo/records/query"), (404, {"error": "not_found"}))
        self.assertEqual(self.request("PUT", "/v1/demo/records/query", {"module": "funds"}), (405, {"error": "method_not_allowed"}))

    def test_malformed_or_non_json_requests_fail_without_detail(self):
        self.assertEqual(self.request("POST", "/v1/demo/records/query", {"module": "funds"}, content_type="text/plain"), (400, {"error": "invalid_request"}))
        oversized = {"module": "funds", "padding": "x" * service.MAX_BODY_BYTES}
        self.assertEqual(self.request("POST", "/v1/demo/records/query", oversized), (400, {"error": "invalid_request"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
