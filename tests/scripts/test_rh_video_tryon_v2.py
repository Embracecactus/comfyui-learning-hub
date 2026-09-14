import json
import subprocess
import tempfile
import unittest
from collections import defaultdict, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / "docs"
    / "04-电商AI工作流"
    / "workflows"
    / "rh-video-tryon-v2.json"
)
GENERATOR = ROOT / "scripts" / "derive_rh_video_tryon_v2.mjs"
VALIDATOR = ROOT / "scripts" / "validate_comfy_workflow.mjs"


class RunningHubVideoTryOnV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = json.loads(cls.raw)
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}
        cls.outgoing = defaultdict(set)
        for _, source_id, _, target_id, _, *_ in cls.workflow["links"]:
            cls.outgoing[source_id].add(target_id)

    def reachable_from(self, start):
        reached = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for target in self.outgoing[current]:
                if target not in reached:
                    reached.add(target)
                    queue.append(target)
        return reached

    def has_link(self, source_id, source_slot, target_id, target_slot):
        return any(
            link[1:5] == [source_id, source_slot, target_id, target_slot]
            for link in self.workflow["links"]
        )

    def test_short_filename_and_structural_validator(self):
        self.assertLessEqual(len(WORKFLOW.name), 50)
        result = subprocess.run(
            ["node", str(VALIDATOR), str(WORKFLOW)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(": OK (", result.stdout)

    def test_generated_file_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = Path(temp_dir) / "rh-video-tryon-v2.json"
            subprocess.run(
                ["node", str(GENERATOR), str(WORKFLOW), str(generated)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.read_bytes(), WORKFLOW.read_bytes())

    def test_generator_rejects_topology_drift(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tampered = json.loads(self.raw)
            for link in tampered["links"]:
                if link[1:5] == [75, 0, 98, 0]:
                    link[1] = 61
                    break
            source = Path(temp_dir) / "tampered.json"
            target = Path(temp_dir) / "output.json"
            source.write_text(json.dumps(tampered), encoding="utf-8")
            result = subprocess.run(
                ["node", str(GENERATOR), str(source), str(target)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source workflow contract drifted", result.stderr)

    def test_required_runninghub_video_tryon_nodes_exist(self):
        expected = {
            61: "VHS_LoadVideo",
            75: "LoadImage",
            97: "WanVideoClipVisionEncode",
            102: "ClothesSegment",
            113: "SeCVideoSegmentation",
            92: "WanVideoAnimateEmbeds",
            86: "WanVideoSampler",
            67: "VHS_VideoCombine",
        }
        self.assertEqual(
            {node_id: self.nodes[node_id]["type"] for node_id in expected},
            expected,
        )

    def test_garment_identity_and_source_video_are_separated(self):
        self.assertTrue(self.has_link(75, 0, 98, 0))
        self.assertTrue(self.has_link(98, 0, 97, 1))
        self.assertTrue(self.has_link(97, 0, 92, 1))
        self.assertTrue(self.has_link(98, 0, 92, 2))

        self.assertTrue(self.has_link(61, 0, 42, 0))
        self.assertTrue(self.has_link(42, 0, 102, 0))
        self.assertTrue(self.has_link(102, 1, 113, 3))
        self.assertTrue(self.has_link(61, 0, 113, 1))
        self.assertTrue(self.has_link(113, 0, 57, 0))
        self.assertTrue(self.has_link(82, 0, 92, 5))
        self.assertTrue(self.has_link(59, 0, 92, 6))

        self.assertNotIn(97, self.reachable_from(61))
        self.assertIn(92, self.reachable_from(61))
        self.assertIn(97, self.reachable_from(75))

    def test_first_run_profile_is_bounded(self):
        video = self.nodes[61]["widgets_values"]
        self.assertEqual(video["frame_load_cap"], 49)
        self.assertEqual(video["video"], "")
        self.assertEqual(video["force_size"], "Disabled")
        self.assertEqual(self.nodes[71]["widgets_values"], [432])
        self.assertEqual(self.nodes[72]["widgets_values"], [768])
        self.assertEqual(self.nodes[139]["widgets_values"], [10])
        self.assertEqual(self.nodes[86]["widgets_values"][4], "fixed")
        self.assertEqual(
            self.nodes[61]["properties"]["ver"],
            "8e4d79471bf1952154768e8435a9300077b534fa",
        )

    def test_default_mask_supports_long_sleeve_acceptance_case(self):
        values = self.nodes[102]["widgets_values"]
        labels = [
            "Hat",
            "Hair",
            "Face",
            "Sunglasses",
            "Upper-clothes",
            "Skirt",
            "Dress",
            "Belt",
            "Pants",
            "Left-arm",
            "Right-arm",
            "Left-leg",
            "Right-leg",
            "Bag",
            "Scarf",
            "Left-shoe",
            "Right-shoe",
            "Background",
        ]
        selected = {label for label, value in zip(labels, values) if value}
        self.assertEqual(
            selected,
            {
                "Upper-clothes",
                "Skirt",
                "Dress",
                "Belt",
                "Pants",
                "Left-arm",
                "Right-arm",
            },
        )

    def test_no_account_media_or_demo_output_is_embedded(self):
        self.assertEqual(self.nodes[75]["widgets_values"][0], "")
        self.assertNotIn("cos_url", self.raw)
        self.assertNotIn("/data/ComfyUI/personal/", self.raw)
        self.assertNotIn("c252c16467331e78e2b520e74aaebc9e868bf1804c27159a0b8ed0f4c7af9803", self.raw)
        self.assertNotIn("3f423ace8ff1ef31e2d3acfc9efceff05a27801eb17552f44062cd77eb78dc18", self.raw)

    def test_serialized_links_match_link_table(self):
        expected_inputs = {}
        expected_outputs = defaultdict(list)
        for link_id, source_id, source_slot, target_id, target_slot, *_ in self.workflow["links"]:
            expected_inputs[(target_id, target_slot)] = link_id
            expected_outputs[(source_id, source_slot)].append(link_id)

        for node in self.workflow["nodes"]:
            for slot, input_spec in enumerate(node.get("inputs", [])):
                self.assertEqual(
                    input_spec.get("link"),
                    expected_inputs.get((node["id"], slot)),
                    f"input mismatch at {node['id']}:{slot}",
                )
            for slot, output_spec in enumerate(node.get("outputs", [])):
                self.assertEqual(
                    output_spec.get("links") or [],
                    expected_outputs.get((node["id"], slot), []),
                    f"output mismatch at {node['id']}:{slot}",
                )

        self.assertEqual(self.workflow["last_node_id"], max(self.nodes))
        self.assertEqual(
            self.workflow["last_link_id"],
            max(link[0] for link in self.workflow["links"]),
        )


if __name__ == "__main__":
    unittest.main()
