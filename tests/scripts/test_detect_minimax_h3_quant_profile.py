import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "detect_minimax_h3_quant_profile.py"
SPEC = importlib.util.spec_from_file_location("detect_minimax_h3_quant_profile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class QuantizedProfileRecommendationTest(unittest.TestCase):
    def test_blackwell_8gb_uses_nvfp4_and_conservative_chunking(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "dequantize_nvfp4"},
            available_capabilities={"dequantize_int8_embedding"},
        )

        self.assertTrue(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-nvfp4-low-vram")
        self.assertEqual(result["adaptive_profile"], "auto_stable")
        self.assertEqual(result["min_chunk_tokens"], 1024)
        self.assertEqual(result["max_chunk_tokens"], 4096)
        self.assertEqual(result["prefetch_mode"], "auto")
        self.assertEqual(result["megapixels"], 0.1)

    def test_ada_16gb_uses_int8_text_encoder(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=16,
            compute_major=8,
            compute_minor=9,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear"},
        )

        self.assertTrue(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-int8-low-vram")
        self.assertEqual(
            result["text_encoder"],
            "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
        )
        self.assertEqual(result["adaptive_profile"], "auto_balanced")
        self.assertEqual(result["megapixels"], 0.4)

    def test_system_ram_selects_stage_io_mode_independently_of_gpu_name(self):
        enough = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            cuda_major=13,
            system_ram_gib=32,
            available_ram_gib=28,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "dequantize_nvfp4"},
            available_capabilities={"dequantize_int8_embedding"},
        )
        constrained = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            cuda_major=13,
            system_ram_gib=16,
            available_ram_gib=12,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "dequantize_nvfp4"},
            available_capabilities={"dequantize_int8_embedding"},
        )

        self.assertEqual(enough["io_mode"], "ram-assisted")
        self.assertEqual(constrained["io_mode"], "disk-streaming")

    def test_low_currently_available_ram_forces_disk_streaming(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            cuda_major=13,
            system_ram_gib=32,
            available_ram_gib=18,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "dequantize_nvfp4"},
            available_capabilities={"dequantize_int8_embedding"},
        )

        self.assertEqual(result["io_mode"], "disk-streaming")

    def test_old_nvidia_is_not_claimed_supported(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=6,
            compute_minor=1,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear"},
        )

        self.assertFalse(result["supported"])
        self.assertIsNone(result["workflow_profile"])

    def test_sm70_is_not_misclassified_as_int8_candidate(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=7,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear"},
        )

        self.assertFalse(result["supported"])
        self.assertIsNone(result["workflow_profile"])

    def test_missing_native_cuda_backend_is_not_reported_supported(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=False,
            native_capabilities=set(),
            available_capabilities=set(),
        )

        self.assertFalse(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-nvfp4-low-vram")
        self.assertTrue(any("comfy-kitchen" in warning for warning in result["warnings"]))

    def test_nvfp4_missing_loader_capability_falls_back_to_int8(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "gemv_awq_w4a16"},
            available_capabilities={"dequantize_int8_embedding"},
        )

        self.assertTrue(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-int8-low-vram")
        self.assertTrue(any("INT8 ConvRot" in warning for warning in result["warnings"]))

    def test_nvfp4_missing_embedding_fallback_also_selects_int8(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"int8_linear", "dequantize_nvfp4"},
            available_capabilities=set(),
        )

        self.assertTrue(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-int8-low-vram")

    def test_missing_shared_int8_linear_keeps_nvfp4_candidate_unsupported(self):
        result = MODULE.recommend_profile(
            backend="cuda",
            vram_gib=8,
            compute_major=12,
            compute_minor=0,
            cuda_major=13,
            native_backend_ready=True,
            native_capabilities={"dequantize_nvfp4"},
            available_capabilities={"dequantize_int8_embedding"},
        )

        self.assertFalse(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-nvfp4-low-vram")
        self.assertTrue(any("int8_linear" in warning for warning in result["warnings"]))

    def test_rocm_matrix_core_path_remains_experimental(self):
        result = MODULE.recommend_profile(
            backend="rocm",
            vram_gib=16,
            amd_arch="gfx1100",
        )

        self.assertFalse(result["supported"])
        self.assertEqual(result["workflow_profile"], "quantized-int8-low-vram")
        self.assertIn("Experimental", result["warnings"][0])

    def test_non_cuda_backend_is_unsupported(self):
        result = MODULE.recommend_profile(backend="other", vram_gib=12)

        self.assertFalse(result["supported"])
        self.assertIsNone(result["text_encoder"])


if __name__ == "__main__":
    unittest.main()
