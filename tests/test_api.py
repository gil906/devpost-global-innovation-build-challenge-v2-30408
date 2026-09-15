import copy
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import Server
from store import MAX_PER_SESSION, RETENTION_SECONDS, Store, StoreFull
from test_planner import demo


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = Path(os.environ.get("APP_DATA_DIR", ".runtime"))
        runtime.mkdir(parents=True, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="api-test-", dir=runtime)
        cls.server = Server(("0.0.0.0", 8764), cls.directory.name)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.directory.cleanup()

    def call(self, method, path, body=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", 8764, timeout=10)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        payload = raw if raw is not None else json.dumps(body) if body is not None else None
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, data

    def session(self):
        status, headers, _ = self.call("GET", "/api/scenarios")
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0]

    def test_health_and_static_assets(self):
        status, headers, body = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/", "/app.js", "/style.css", "/icon.svg"):
            with self.subTest(path=path):
                status, headers, body = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertGreater(len(body), 100)
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])

    def test_complete_plan_and_csv(self):
        status, _, body = self.call("GET", "/api/demo")
        self.assertEqual(status, 200)
        scenario = json.loads(body)
        status, _, body = self.call("POST", "/api/plan", scenario)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["summary"]["allocated"], 230)
        status, headers, body = self.call("POST", "/api/export/csv", scenario)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(len(body.decode().splitlines()), 7)

    def test_persistent_snapshots_are_isolated_and_deletable(self):
        cookie, outsider = self.session(), self.session()
        scenario = demo()
        scenario["name"] = "Snapshot <untrusted>"
        status, _, body = self.call("POST", "/api/scenarios", scenario, {"Cookie": cookie})
        self.assertEqual(status, 201)
        identifier = json.loads(body)["id"]
        path = f"/api/scenarios/{identifier}"
        status, _, body = self.call("GET", "/api/scenarios", headers={"Cookie": cookie})
        self.assertEqual(json.loads(body)["items"][0]["name"], scenario["name"])
        status, _, body = self.call("GET", path, headers={"Cookie": cookie})
        self.assertEqual(json.loads(body), scenario)
        # A new Store instance reads the same committed SQLite database.
        stored = Store(self.directory.name)
        with stored.connect() as connection:
            self.assertIsNotNone(connection.execute("SELECT scenario FROM scenarios WHERE id = ?", (identifier,)).fetchone())
        for method in ("GET", "DELETE"):
            self.assertEqual(self.call(method, path, headers={"Cookie": outsider})[0], 404)
        self.assertEqual(self.call("DELETE", path, headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.call("GET", path, headers={"Cookie": cookie})[0], 404)

    def test_errors_are_explicit_and_do_not_mutate(self):
        scenario = demo()
        scenario["donors"][0]["quantity"] = -5
        for path in ("/api/plan", "/api/scenarios", "/api/export/csv"):
            status, _, body = self.call("POST", path, scenario)
            self.assertEqual(status, 422)
            self.assertIn("quantity", json.loads(body)["error"])
        self.assertEqual(self.call("POST", "/api/plan", raw="{broken")[0], 400)
        self.assertEqual(self.call("POST", "/api/plan", raw="[" * 2000 + "]" * 2000)[0], 400)
        self.assertEqual(self.call("POST", "/api/plan", raw="x", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/api/plan", raw=" " * (128 * 1024 + 1))[0], 413)
        self.assertEqual(self.call("POST", "/api/plan", demo(), {"Transfer-Encoding": "chunked"})[0], 400)

    def test_nonfinite_and_very_large_numbers_return_validation_errors(self):
        for value in (float("nan"), float("inf"), 10 ** 400, True):
            scenario = demo()
            scenario["speed_kph"] = value
            self.assertEqual(self.call("POST", "/api/plan", scenario)[0], 422)

    def test_cross_origin_requests_are_blocked(self):
        for path, method in (("/api/plan", "POST"), ("/api/scenarios", "GET")):
            self.assertEqual(self.call(method, path, demo() if method == "POST" else None,
                                       {"Origin": "https://unrelated.invalid"})[0], 403)
        self.assertEqual(self.call("POST", "/api/plan", demo(), {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.call("POST", "/api/plan", demo(), {"Origin": "http://[bad"})[0], 403)
        self.assertEqual(self.call("POST", "/api/plan", demo(), {"Origin": "http://127.0.0.1:8764"})[0], 200)

    def test_static_allowlist_prevents_file_access(self):
        for path in ("/.env", "/store.py", "/../app.py", "/%2e%2e/app.py", "/.runtime/commontable.sqlite3"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 404)


class StoreTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(os.environ.get("APP_DATA_DIR", ".runtime"))
        runtime.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="store-test-", dir=runtime)
        self.store = Store(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_count_limits_and_rollback(self):
        for _ in range(MAX_PER_SESSION):
            self.store.save("owner", demo())
        with self.assertRaises(StoreFull):
            self.store.save("owner", demo())
        self.assertEqual(len(self.store.list("owner")), MAX_PER_SESSION)
        self.store.save("other-owner", demo())
        self.assertEqual(len(self.store.list("other-owner")), 1)

    def test_expired_snapshots_are_inaccessible_and_pruned(self):
        saved = self.store.save("owner", demo())
        with self.store.connect() as connection:
            connection.execute("UPDATE scenarios SET created_at = ?", (int(time.time()) - RETENTION_SECONDS - 1,))
        self.assertEqual(self.store.list("owner"), [])
        self.assertIsNone(self.store.get("owner", saved["id"]))
        self.store.save("owner", demo())
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0], 1)

    def test_stored_scenario_is_a_snapshot_not_a_live_reference(self):
        scenario = demo()
        original = copy.deepcopy(scenario)
        saved = self.store.save("owner", scenario)
        scenario["donors"][0]["quantity"] = 999
        reopened = Store(self.directory.name)
        self.assertEqual(reopened.get("owner", saved["id"]), original)
        self.assertFalse(reopened.delete("other-owner", saved["id"]))


if __name__ == "__main__":
    unittest.main()
