import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).parents[2]
    / "custom_nodes"
    / "comfyui_product_layout"
    / "layout_math.py"
)
SPEC = importlib.util.spec_from_file_location("product_layout_math", MODULE_PATH)
LAYOUT_MATH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT_MATH)


class ComputeLayoutTests(unittest.TestCase):
    def test_hoodie_like_foreground_matches_relative_safe_area(self):
        self.assertEqual(
            LAYOUT_MATH.compute_layout(435, 496, 576, 1024, 88, 65, 50, 43.5),
            (34, 156, 507, 578),
        )

    def test_portrait_product_is_limited_by_height(self):
        self.assertEqual(
            LAYOUT_MATH.compute_layout(200, 800, 576, 1024, 88, 65, 50, 43.5),
            (205, 112, 166, 666),
        )

    def test_landscape_product_is_limited_by_width(self):
        self.assertEqual(
            LAYOUT_MATH.compute_layout(800, 200, 576, 1024, 88, 65, 50, 43.5),
            (34, 382, 507, 127),
        )

    def test_upscale_can_be_disabled(self):
        self.assertEqual(
            LAYOUT_MATH.compute_layout(
                100,
                100,
                576,
                1024,
                88,
                65,
                50,
                43.5,
                allow_upscale=False,
            ),
            (238, 395, 100, 100),
        )


class ExpandBoundingBoxTests(unittest.TestCase):
    def test_padding_is_clamped_to_image(self):
        self.assertEqual(
            LAYOUT_MATH.expand_bbox(2, 4, 50, 80, 100, 120, 10),
            (0, 0, 58, 88),
        )

    def test_empty_box_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            LAYOUT_MATH.expand_bbox(10, 10, 9, 20, 100, 100, 1)


class ComputeTextOriginTests(unittest.TestCase):
    def test_top_left_uses_percentage_as_visible_box_corner(self):
        self.assertEqual(
            LAYOUT_MATH.compute_text_origin(
                1000, 2000, (-2, 4, 198, 104), 10, 5, "top_left"
            ),
            (102, 96),
        )

    def test_center_anchor_centers_visible_text_box(self):
        self.assertEqual(
            LAYOUT_MATH.compute_text_origin(
                1000, 2000, (0, 0, 200, 100), 50, 50, "center_center"
            ),
            (400, 950),
        )

    def test_bottom_right_anchor_places_visible_box_at_target(self):
        self.assertEqual(
            LAYOUT_MATH.compute_text_origin(
                1000, 2000, (0, 0, 200, 100), 90, 95, "bottom_right"
            ),
            (700, 1800),
        )

    def test_keep_inside_clamps_text_block_to_canvas(self):
        self.assertEqual(
            LAYOUT_MATH.compute_text_origin(
                100, 200, (0, 0, 80, 50), 100, 100, "top_left"
            ),
            (20, 150),
        )

    def test_invalid_anchor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            LAYOUT_MATH.compute_text_origin(
                100, 200, (0, 0, 10, 10), 50, 50, "middle"
            )


if __name__ == "__main__":
    unittest.main()
