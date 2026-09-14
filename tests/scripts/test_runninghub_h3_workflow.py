import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / "docs"
    / "04-电商AI工作流"
    / "workflows"
    / "yinghai-h3-runninghub-0.2mp.json"
)
HOODIE_WORKFLOW = (
    ROOT
    / "docs"
    / "04-电商AI工作流"
    / "workflows"
    / "rh-h3-hoodie-v3.json"
)
SOURCE = (
    ROOT
    / "docs"
    / "04-电商AI工作流"
    / "workflows"
    / "ecommerce-yinghai-copy-hot-video-h3-nvfp4-0.2mp.json"
)
HOODIE_SOURCE = (
    ROOT
    / "docs"
    / "04-电商AI工作流"
    / "workflows"
    / "ecommerce-yinghai-copy-hot-video-h3-nvfp4-0.2mp-hoodie-second-half.json"
)
GENERATOR = ROOT / "scripts" / "derive_runninghub_h3_workflow.mjs"
PROJECT_ONLY_TYPES = {
    "H3VAEDecodeAudioRelease",
    "H3VAEDecodeTiledRelease",
    "H3ReferenceVideoFrames24FPS",
    "MiniMaxH3AdaptiveMemory",
    "H3ReleaseAfterConditioning",
    "H3ReleaseAfterSampling",
}


class RunningHubH3WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}

    def test_generated_file_matches_generator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = Path(temp_dir) / "runninghub.json"
            subprocess.run(
                ["node", str(GENERATOR), str(SOURCE), str(generated)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.read_bytes(), WORKFLOW.read_bytes())

    def test_project_only_nodes_are_removed(self):
        types = {node["type"] for node in self.workflow["nodes"]}
        self.assertTrue(PROJECT_ONLY_TYPES.isdisjoint(types))
        self.assertEqual(self.nodes[121]["type"], "VAEDecodeAudio")
        self.assertEqual(self.nodes[122]["type"], "VAEDecode")

    def test_core_paths_replace_release_pass_through_nodes(self):
        links = self.workflow["links"]

        def has_link(source_id, source_slot, target_id, target_slot):
            return any(
                link[1:5] == [source_id, source_slot, target_id, target_slot]
                for link in links
            )

        self.assertTrue(has_link(127, 0, 124, 0))
        self.assertTrue(has_link(127, 0, 145, 0))
        self.assertTrue(has_link(127, 0, 141, 0))
        self.assertTrue(has_link(136, 0, 126, 1))
        self.assertTrue(has_link(136, 1, 125, 4))
        self.assertTrue(has_link(125, 0, 122, 0))
        self.assertTrue(has_link(125, 0, 121, 0))
        self.assertTrue(has_link(150, 0, 136, 6))

    def test_media_inputs_are_intentionally_empty(self):
        self.assertEqual(self.nodes[137]["widgets_values_named"]["image"], "")
        self.assertEqual(self.nodes[147]["widgets_values_named"]["file"], "")
        for node_id in (116, 140):
            self.assertEqual(
                self.nodes[node_id]["widgets_values"],
                [self.nodes[node_id]["widgets_values_named"]["text"]],
            )
        self.assertEqual(
            self.workflow["extra"]["audit"]["profile"],
            "yinghai-copy-hot-video-h3-runninghub-0.2mp",
        )

    def test_serialized_links_match_link_table(self):
        expected_inputs = {}
        expected_outputs = {}
        for link_id, source_id, source_slot, target_id, target_slot, *_ in self.workflow["links"]:
            expected_inputs[(target_id, target_slot)] = link_id
            expected_outputs.setdefault((source_id, source_slot), []).append(link_id)

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


class RunningHubHoodieV3WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(HOODIE_WORKFLOW.read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}

    def test_generated_file_matches_exact_local_success_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = Path(temp_dir) / "rh-h3-hoodie-v3.json"
            subprocess.run(
                ["node", str(GENERATOR), str(HOODIE_SOURCE), str(generated)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.read_bytes(), HOODIE_WORKFLOW.read_bytes())

    def test_fixed_validation_inputs_match_local_success_conditions(self):
        prompt = self.nodes[138]["widgets_values"][0]
        for required_text in (
            "black pullover hoodie",
            "long sleeves",
            "exact white 1977 chest print",
            "Do not copy the white off-shoulder top",
        ):
            self.assertIn(required_text, prompt)
        self.assertNotIn("flower positions", prompt)
        self.assertEqual(self.nodes[148]["widgets_values"][:2], [5, 5.2])
        self.assertEqual(self.nodes[136]["widgets_values"][3], 124)
        self.assertEqual(self.workflow["extra"]["audit"]["profile"], "rh-h3-hoodie-v3")

    def test_uploads_are_empty_and_filename_is_runninghub_safe(self):
        self.assertEqual(self.nodes[137]["widgets_values_named"]["image"], "")
        self.assertEqual(self.nodes[147]["widgets_values_named"]["file"], "")
        self.assertLessEqual(len(HOODIE_WORKFLOW.name), 50)

    def test_no_project_only_nodes_remain(self):
        types = {node["type"] for node in self.workflow["nodes"]}
        self.assertTrue(PROJECT_ONLY_TYPES.isdisjoint(types))


if __name__ == "__main__":
    unittest.main()
