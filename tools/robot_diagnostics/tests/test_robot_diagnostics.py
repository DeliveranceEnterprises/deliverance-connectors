from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from robot_diagnostics.common import classify_validation_status, sanitize_text
from robot_diagnostics.inorbit import parse_describe_robots
from robot_diagnostics.main import write_csv, write_json, write_markdown
from robot_diagnostics.providers import allybot


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def assert_no_sensitive_patterns(testcase: unittest.TestCase, text: str) -> None:
    patterns = {
        "IPv4 address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "websocket app URL": r"fleetapi/websocketapp/[^/\s]+/[^/\s]+",
        "api key assignment": r"(?i)api[_-]?key\s*[=:]\s*[A-Za-z0-9_-]{8,}",
        "password assignment": r"(?i)password\s*[=:]\s*[A-Za-z0-9_-]{8,}",
        "token assignment": r"(?i)token\s*[=:]\s*[A-Za-z0-9_-]{8,}",
        "long hex id": r"\b[a-fA-F0-9]{24,}\b",
        "mac-like fleet id": r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b",
    }
    for label, pattern in patterns.items():
        testcase.assertIsNone(re.search(pattern, text), f"Found sensitive-looking {label}")


class DiagnosticsTests(unittest.TestCase):
    def test_parse_inorbit_describe_robots(self) -> None:
        output = """Name                            ID                    Agent           Online    Last seen
allybot-cleaner-1                allybot-cleaner-1     2.0.1.edgesdk_py   True      2026-05-19T10:47:55.546000
"""

        robots = parse_describe_robots(output)

        self.assertIn("allybot-cleaner-1", robots)
        self.assertTrue(robots["allybot-cleaner-1"]["online"])
        self.assertEqual(robots["allybot-cleaner-1"]["agent_version"], "2.0.1.edgesdk_py")

    def test_sanitize_text_redacts_common_secrets(self) -> None:
        message = (
            "ws://host/fleetapi/websocketapp/openid123/token456 "
            "token=abc api_key:xyz password=secret Authorization:Bearer raw"
        )

        clean = sanitize_text(message)

        self.assertNotIn("openid123", clean)
        self.assertNotIn("token456", clean)
        self.assertNotIn("abc", clean)
        self.assertNotIn("xyz", clean)
        self.assertNotIn("secret", clean)
        self.assertIn("<redacted>", clean)

    def test_classify_validation_status(self) -> None:
        self.assertEqual(classify_validation_status({}), "yaml_only")
        self.assertEqual(classify_validation_status({"validated": "pending_credentials"}), "pending_credentials")
        self.assertEqual(classify_validation_status({"device_status_present": True}), "source_partial")
        self.assertEqual(
            classify_validation_status({"device_status_present": True, "active_map_present": True}),
            "source_ok",
        )
        self.assertEqual(
            classify_validation_status({"exists_in_inorbit": True, "online": True}),
            "inorbit_ok",
        )
        self.assertEqual(
            classify_validation_status(
                {"device_status_present": True, "active_map_present": True, "exists_in_inorbit": True, "online": True}
            ),
            "full_flow_ok",
        )

    def test_export_markdown_csv_json_drops_raw_fleet_id(self) -> None:
        rows = [
            {
                "robot_id": "allybot-cleaner-1",
                "provider": "Allybot",
                "fleet_robot_id": "full-secret-fleet-id",
                "fleet_robot_id_masked": "full-s...eet-id",
                "validated": "source_ok",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            md_path = tmp_path / "inventory.md"
            csv_path = tmp_path / "inventory.csv"
            json_path = tmp_path / "inventory.json"

            write_markdown(md_path, rows)
            write_csv(csv_path, rows)
            write_json(json_path, rows)

            self.assertNotIn("full-secret-fleet-id", md_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[0]["fleet_robot_id_masked"], "full-s...eet-id")
            json_rows = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("fleet_robot_id", json_rows[0])

    def test_versionable_examples_are_fictitious_and_sanitized(self) -> None:
        sample_md = PACKAGE_ROOT / "examples" / "sample_inventory.md"
        sample_json = PACKAGE_ROOT / "examples" / "sample_inventory.json"

        self.assertTrue(sample_md.exists())
        self.assertTrue(sample_json.exists())
        self.assertNotIn("/outputs/", str(sample_md))
        self.assertNotIn("/outputs/", str(sample_json))

        sample_text = sample_md.read_text(encoding="utf-8") + "\n" + sample_json.read_text(encoding="utf-8")
        assert_no_sensitive_patterns(self, sample_text)
        self.assertIn("demo-allybot-1", sample_text)
        self.assertIn("demo-keenon-1", sample_text)
        self.assertIn("demo-autoxing-1", sample_text)
        self.assertNotIn("allybot-cleaner-1", sample_text)
        self.assertNotIn("DELIVERANCE", sample_text)

    def test_sanitized_report_has_no_obvious_secrets(self) -> None:
        report = PACKAGE_ROOT / "reports" / "allybot_validation_summary.md"

        self.assertTrue(report.exists())
        report_text = report.read_text(encoding="utf-8")
        assert_no_sensitive_patterns(self, report_text)
        self.assertIn("allybot-cleaner-1", report_text)
        self.assertIn("full_flow_ok", report_text)
        self.assertNotIn("fleet_robot_id", report_text)


class AllybotWsFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_ws_failure_does_not_abort_inventory(self) -> None:
        class FakeClient:
            def __init__(self, config: dict[str, object]) -> None:
                self.openid = "open123"
                self.mobile_token = "token456"
                self.rest_token = None

            async def login(self) -> None:
                return None

            async def close(self) -> None:
                return None

            async def get_device_status(self, fleet_robot_id: str) -> dict[str, object]:
                return {"battery": 1.0, "work_status": "Charging", "haveTaskRunning": False}

            async def get_active_map(self, fleet_robot_id: str) -> dict[str, object]:
                return {"mapinfo": {"id": "map-1", "name": "DELIVERANCE"}, "image_url": "https://example.invalid/map.png"}

        async def failing_ws(*args: object, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("failed ws://host/fleetapi/websocketapp/open123/token456?token=abc")

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            config_dir = repo_root / "allybot_connector" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / ".env.local").write_text("", encoding="utf-8")
            (config_dir / "my_fleet.local.yaml").write_text(
                """
connector_config:
  base_url: "http://example.invalid"
  username: "user"
  password: "pass"
fleet:
  - robot_id: "allybot-cleaner-1"
    fleet_robot_id: "fleet-robot-1"
""",
                encoding="utf-8",
            )

            original_client = allybot.AllybotReadOnlyClient
            original_ws = allybot.sample_ws
            allybot.AllybotReadOnlyClient = FakeClient  # type: ignore[assignment]
            allybot.sample_ws = failing_ws  # type: ignore[assignment]
            try:
                rows = await allybot.diagnose(repo_root, "allybot-cleaner-1", False, 1)
            finally:
                allybot.AllybotReadOnlyClient = original_client  # type: ignore[assignment]
                allybot.sample_ws = original_ws  # type: ignore[assignment]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ws"], "failed")
        self.assertIn("websocket failed", rows[0]["observations"])
        self.assertNotIn("open123", rows[0]["observations"])
        self.assertNotIn("token456", rows[0]["observations"])
        self.assertNotIn("abc", rows[0]["observations"])


if __name__ == "__main__":
    unittest.main()
