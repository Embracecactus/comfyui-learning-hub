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
YINGHAI_WORKFLOW = "ecommerce-yinghai-copy-hot-video-h3-nvfp4-low-vram.json"


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

    def test_yinghai_reference_video_chain_and_prompt(self):
        workflow = json.loads((WORKFLOW_ROOT / YINGHAI_WORKFLOW).read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in workflow["nodes"]}
        by_type = {node["type"]: node for node in workflow["nodes"]}
        self.assertEqual(by_type["LoadVideo"]["widgets_values_named"]["file"],
                         "yinghai-copy-hot-video-v2-01-benchmark.mp4")
        self.assertEqual(by_type["LoadImage"]["widgets_values_named"]["image"],
                         "yinghai-copy-hot-video-v2-02-product.png")
        self.assertEqual(by_type["Video Slice"]["widgets_values_named"],
                         {"start_time": 0, "duration": 5.2, "strict_duration": False})
        self.assertEqual(by_type["H3ReferenceVideoFrames24FPS"]["widgets_values_named"],
                         {"source_fps": 24, "target_fps": 24, "max_seconds": 5.2})
        self.assertEqual(by_type["H3ReferenceVideoFrames24FPS"]["widgets_values"],
                         [24, 24, 5.2])
        scale = by_type["ImageScaleToTotalPixels"]
        self.assertEqual(scale["widgets_values_named"],
                         {"upscale_method": "area", "megapixels": 0.1, "resolution_steps": 32})
        self.assertEqual([output["type"] for output in by_type["GetVideoComponents"]["outputs"]],
                         ["IMAGE", "AUDIO", "FLOAT", "INT"])
        self.assertEqual(len(by_type["GetVideoComponents"]["outputs"]), 4)
        ref = by_type["MiniMaxH3ReferenceToVideo"]
        self.assertIsNotNone(next(i for i in ref["inputs"] if i["name"] == "ref_videos.ref_video_0")["link"])
        self.assertIsNone(next(i for i in ref["inputs"] if i["name"] == "ref_video_audios.ref_video_audio_0")["link"])
        prompt = by_type["PrimitiveStringMultiline"]["widgets_values_named"]["value"]
        for term in ("Picture1", "Video1", "color", "silhouette", "flower", "Do not copy", "watermark"):
            self.assertIn(term, prompt)
        links = workflow["links"]
        def connected(src_type, dst_type):
            src_ids = {n["id"] for n in workflow["nodes"] if n["type"] == src_type}
            dst_ids = {n["id"] for n in workflow["nodes"] if n["type"] == dst_type}
            return any(l[1] in src_ids and l[3] in dst_ids for l in links)
        self.assertTrue(connected("LoadVideo", "Video Slice"))
        self.assertTrue(connected("Video Slice", "GetVideoComponents"))
        self.assertTrue(connected("GetVideoComponents", "H3ReferenceVideoFrames24FPS"))
        self.assertTrue(connected("H3ReferenceVideoFrames24FPS", "MiniMaxH3ReferenceToVideo"))
        self.assertTrue(connected("GetVideoComponents", "ImageScaleToTotalPixels"))
        self.assertTrue(connected("ImageScaleToTotalPixels", "H3ReferenceVideoFrames24FPS"))
        self.assertEqual(next(group for group in workflow["groups"] if group["id"] == 7)["title"],
                         "Video 1｜对标视频预处理")

    def test_yinghai_release_barrier_no_orphans_and_declared_ids(self):
        workflow = json.loads((WORKFLOW_ROOT / YINGHAI_WORKFLOW).read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in workflow["nodes"]}
        self.assertEqual(workflow["last_node_id"], max(nodes))
        self.assertEqual(workflow["last_link_id"], max(link[0] for link in workflow["links"]))
        self.assertTrue(all(link[1] in nodes and link[3] in nodes for link in workflow["links"]))
        video = next(node for node in nodes.values() if node["type"] == "H3VAEDecodeTiledRelease")
        audio = next(node for node in nodes.values() if node["type"] == "H3VAEDecodeAudioRelease")
        self.assertTrue(video["widgets_values_named"]["release"])
        self.assertTrue(audio["widgets_values_named"]["release"])
        self.assertTrue(any(link[1] == video["id"] and link[3] == audio["id"] and link[5] == "BOOLEAN"
                            for link in workflow["links"]))


if __name__ == "__main__":
    unittest.main()
