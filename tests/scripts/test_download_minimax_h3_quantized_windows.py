import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "download_minimax_h3_quantized_windows.cmd"
)


class MiniMaxH3DownloadScriptTests(unittest.TestCase):
    def test_default_model_root_is_user_independent(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'set "MODEL_ROOT=%LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Shared\\models"',
            text,
        )
        self.assertNotIn(r"C:\Users\lijian", text)

    def test_resume_restarts_curl_in_an_outer_loop(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(":download_retry", text)
        self.assertIn("goto :download_retry", text)
        self.assertIn("-C -", text)
        self.assertNotIn("--retry 20", text)
        self.assertNotIn("--retry-all-errors", text)

    def test_only_exact_zero_curl_exit_is_success(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if "!CURL_EXIT!"=="0" goto :download_complete', text)
        self.assertNotIn("if not errorlevel 1 goto :download_complete", text)

    def test_retry_budget_is_configurable_and_redirect_safe(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'if not defined H3_MAX_DOWNLOAD_ATTEMPTS set "H3_MAX_DOWNLOAD_ATTEMPTS=100"',
            text,
        )
        self.assertIn("GEQ !H3_MAX_DOWNLOAD_ATTEMPTS!", text)
        self.assertIn("ping.exe -n 6 127.0.0.1 >nul", text)
        self.assertNotIn("timeout /t 5", text)

    def test_each_model_has_a_single_writer_lock(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('set "LOCK_DIR=%FINAL_FILE%.download.lock"', text)
        self.assertIn('mkdir "!LOCK_DIR!"', text)
        self.assertIn("Another downloader already owns", text)

    def test_partial_file_is_size_checked_before_final_rename(self):
        text = SCRIPT.read_text(encoding="utf-8")
        size_check = text.index('if not "!ACTUAL_SIZE!"=="!EXPECTED_SIZE!"')
        final_move = text.index('move /Y "%FINAL_FILE%.download" "%FINAL_FILE%"')
        self.assertLess(size_check, final_move)


if __name__ == "__main__":
    unittest.main()
