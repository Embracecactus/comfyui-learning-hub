import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[2] / "custom_nodes" / "comfyui_adaptive_memory" / "reference_video.py"
SPEC = importlib.util.spec_from_file_location("h3_reference_video", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class H3ReferenceVideoTests(unittest.TestCase):
    def test_default_limit_156_frames_at_30_fps(self):
        indices = MODULE.h3_reference_frame_indices(156, 30.0)
        self.assertEqual(len(indices), 124)
        self.assertEqual(len(indices) % 17, 5)
        self.assertEqual(indices[0], 0)

    def test_124_frames_at_24_fps_is_unchanged(self):
        indices = MODULE.h3_reference_frame_indices(124, 24.0)
        self.assertEqual(indices, tuple(range(124)))

    def test_max_seconds_is_capped_at_15_seconds(self):
        indices = MODULE.h3_reference_frame_indices(900, 60.0, 24.0, 60.0)
        self.assertEqual(len(indices), 345)
        self.assertEqual(len(indices) % 17, 5)

    def test_invalid_input_is_rejected(self):
        for args in ((0, 24.0), (10, 0.0), (10, 24.0, 0.0), (10, 24.0, 24.0, 0.0)):
            with self.assertRaises(ValueError):
                MODULE.h3_reference_frame_indices(*args)


if __name__ == "__main__":
    unittest.main()
