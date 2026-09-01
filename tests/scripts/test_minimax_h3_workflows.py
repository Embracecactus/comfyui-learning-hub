import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / "docs" / "04-电商AI工作流" / "workflows"
LOW_MEMORY_WORKFLOWS = (
    "ecommerce-minimax-h3-quantized-nvfp4-low-vram.json",
    "ecommerce-minimax-h3-quantized-int8-low-vram.json",
    "ecommerce-minimax-h3-bf16-streaming-8gb.json",
)


class MiniMaxH3WorkflowTopologyTests(unittest.TestCase):
    def test_low_memory_workflows_have_explicit_video_to_audio_release_barrier(self):
        for filename in LOW_MEMORY_WORKFLOWS:
            with self.subTest(filename=filename):
                workflow = json.loads((WORKFLOW_ROOT / filename).read_text(encoding="utf-8"))
                nodes = {node["id"]: node for node in workflow["nodes"]}
                video = next(
                    node for node in nodes.values() if node["type"] == "H3VAEDecodeTiledRelease"
                )
                audio = next(
                    node for node in nodes.values() if node["type"] == "H3VAEDecodeAudioRelease"
                )
                barriers = [
                    link
                    for link in workflow["links"]
                    if link[1] == video["id"]
                    and link[2] == 1
                    and link[3] == audio["id"]
                    and link[4] == 2
                    and link[5] == "BOOLEAN"
                ]
                self.assertEqual(len(barriers), 1)
                self.assertTrue(video["widgets_values_named"]["release"])
                self.assertTrue(audio["widgets_values_named"]["release"])

    def test_every_workflow_link_references_existing_nodes(self):
        for filename in LOW_MEMORY_WORKFLOWS:
            with self.subTest(filename=filename):
                workflow = json.loads((WORKFLOW_ROOT / filename).read_text(encoding="utf-8"))
                node_ids = {node["id"] for node in workflow["nodes"]}
                self.assertTrue(
                    all(link[1] in node_ids and link[3] in node_ids for link in workflow["links"])
                )


if __name__ == "__main__":
    unittest.main()
