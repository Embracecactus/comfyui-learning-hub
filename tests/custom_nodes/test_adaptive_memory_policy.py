import importlib.util
import pathlib
import sys
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).parents[2]
    / "custom_nodes"
    / "comfyui_adaptive_memory"
    / "adaptive_policy.py"
)
SPEC = importlib.util.spec_from_file_location("adaptive_memory_policy", MODULE_PATH)
POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY
SPEC.loader.exec_module(POLICY)


class AdaptiveH3PolicyTests(unittest.TestCase):
    def snapshot(self, *, vram=8192, free=2048, ram=32768, available=8192, streams=1):
        return POLICY.MemorySnapshot(vram, free, ram, available, streams)

    def decide(self, snapshot, **overrides):
        arguments = dict(
            snapshot=snapshot,
            token_count=12000,
            hidden_size=5376,
            ffn_hidden_size=14336,
            element_size=2,
            profile="auto_stable",
            reserve_vram_mb=1024,
            min_chunk_tokens=1024,
            max_chunk_tokens=8192,
            manual_chunk_tokens=4096,
            prefetch_mode="auto",
            model_size_mb=20000,
        )
        arguments.update(overrides)
        return POLICY.choose_h3_memory_policy(**arguments)

    def test_low_free_vram_selects_small_stable_chunk(self):
        decision = self.decide(self.snapshot(free=1800))
        self.assertEqual(decision.chunk_tokens, 1024)

    def test_more_vram_expands_chunk_without_using_gpu_name(self):
        low = self.decide(self.snapshot(vram=8192, free=2400))
        high = self.decide(self.snapshot(vram=24576, free=16000))
        self.assertGreater(high.chunk_tokens, low.chunk_tokens)
        self.assertLessEqual(high.chunk_tokens, 4096)

    def test_manual_profile_is_clamped_to_workflow_limits(self):
        decision = self.decide(
            self.snapshot(),
            profile="manual",
            manual_chunk_tokens=16384,
            max_chunk_tokens=8192,
        )
        self.assertEqual(decision.chunk_tokens, 8192)

    def test_prefetch_is_disabled_when_async_offload_is_disabled(self):
        decision = self.decide(self.snapshot(streams=0), prefetch_mode="keep")
        self.assertFalse(decision.prefetch_enabled)
        self.assertIn("no active stream", decision.prefetch_reason)

    def test_prefetch_auto_rejects_low_system_ram(self):
        decision = self.decide(self.snapshot(available=1500, streams=1))
        self.assertFalse(decision.prefetch_enabled)
        self.assertIn("system RAM", decision.prefetch_reason)


if __name__ == "__main__":
    unittest.main()
