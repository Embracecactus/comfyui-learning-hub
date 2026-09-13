import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RunningHubH3T2VTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import runninghub_h3_t2v as runner

        cls.runner = runner

    def test_payload_declares_prompt_only_2k_profile(self):
        model = {"_params_by_key": {
            "prompt": {},
            "resolution": {"options": [{"value": "2K"}]},
            "duration": {"options": [{"value": "5"}]},
            "ratio": {"options": [{"value": "16:9"}]},
        }}
        payload = self.runner.build_payload(model, "一只猫在屋顶上行走")
        self.assertEqual(payload, {
            "prompt": "一只猫在屋顶上行走",
            "resolution": "2K",
            "duration": "5",
            "ratio": "16:9",
        })

    def test_dry_run_does_not_need_api_key_or_network(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = self.runner.main([
                "--dry-run", "--prompt", "一个玻璃球落入平静水面，电影感慢镜头"
            ])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["endpoint"], "minimax/hailuo-h3/text-to-video")
        self.assertEqual(result["payload"]["resolution"], "2K")
        self.assertEqual(result["payload"]["duration"], "5")
        self.assertEqual(result["generation"], "not_submitted")

    def test_redact_removes_credentials_without_changing_prompt(self):
        value = self.runner.redact({
            "apiKey": "secret-value",
            "Authorization": "Bearer sk-test-1234567890123456",
            "prompt": "保留这段提示词",
        })
        self.assertEqual(value["apiKey"], "[REDACTED]")
        self.assertEqual(value["Authorization"], "[REDACTED]")
        self.assertEqual(value["prompt"], "保留这段提示词")

    def test_billing_is_unknown_when_final_response_has_no_usage(self):
        value = self.runner.billing_fields(
            {"estimatedPrice": 12.3, "currency": "CNY"},
            {"status": "SUCCESS", "results": []},
        )
        self.assertEqual(value["estimate"], 12.3)
        self.assertEqual(value["estimate_currency"], "CNY")
        self.assertIsNone(value["actual_observed"])
        self.assertEqual(value["settlement_status"], "unknown_pending_account_bill")

    def test_cost_csv_has_stable_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "costs.csv"
            self.runner.append_cost_csv(path, {"run_id": "r1", "status": "MEDIA_VALIDATED"})
            self.runner.append_cost_csv(path, {"run_id": "r2", "status": "FAILED"})
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split(",")[0], "run_id")
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
