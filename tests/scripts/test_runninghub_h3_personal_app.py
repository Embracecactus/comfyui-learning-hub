import contextlib
import io
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import runninghub_h3_personal_app as app  # noqa: E402


class RunningHubH3PersonalAppTests(unittest.TestCase):
    def test_prompt_only_profile_is_2k_and_5_seconds(self):
        nodes = app.build_node_info("一只猫走过雨后的城市屋顶")
        self.assertEqual(
            nodes,
            [
                {"nodeId": "18", "fieldName": "prompt", "fieldValue": "一只猫走过雨后的城市屋顶", "description": "prompt"},
                {"nodeId": "20", "fieldName": "value", "fieldValue": "5", "description": "duration(s)"},
                {"nodeId": "23", "fieldName": "custom_width", "fieldValue": "2560", "description": "custom_width"},
                {"nodeId": "23", "fieldName": "custom_height", "fieldValue": "1440", "description": "custom_height"},
            ],
        )

    def test_dry_run_does_not_need_key_or_network(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = app.main(["--dry-run", "--prompt", "玻璃球落入水面，电影感慢镜头"])
        self.assertEqual(status, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["webappId"], app.APP_ID)
        self.assertEqual(value["resolution"], {"label": "2K", "width": 2560, "height": 1440})
        self.assertEqual(value["generation"], "not_submitted")

    def test_cost_is_unknown_when_legacy_response_has_no_usage(self):
        value = app.cost_from_legacy({"code": 0, "data": []})
        self.assertIsNone(value["consume_coins"])
        self.assertIsNone(value["third_party_consume_money"])
        self.assertEqual(value["settlement_status"], "unknown_pending_account_bill")

    def test_cost_extracts_actual_fields(self):
        value = app.cost_from_legacy({
            "code": 0,
            "data": [{
                "fileUrl": "https://example.invalid/a.mp4",
                "taskCostTime": 123,
                "consumeCoins": 17,
                "consumeMoney": None,
                "thirdPartyConsumeMoney": "3.85",
            }],
        })
        self.assertEqual(value["task_cost_time"], 123)
        self.assertEqual(value["consume_coins"], 17)
        self.assertEqual(value["third_party_consume_money"], "3.85")
        self.assertEqual(value["actual_source"], "task/openapi/outputs")

    def test_redacts_wss_auth_from_saved_response(self):
        value = app.redact("wss://example.invalid/ws?Rh-Comfy-Auth=secret%3D%3D")
        self.assertIn("Rh-Comfy-Auth=[REDACTED]", value)
        self.assertNotIn("secret", value)


if __name__ == "__main__":
    unittest.main()
