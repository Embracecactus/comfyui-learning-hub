#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [sourcePath, outputPath] = process.argv.slice(2);

if (!sourcePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_minimax_h3_local_reference_video_workflow.mjs <official-r2v.json> <output.json>",
  );
  process.exit(2);
}

const workflow = JSON.parse(fs.readFileSync(sourcePath, "utf8"));
const nodesById = new Map(workflow.nodes.map((node) => [node.id, node]));

const requiredNodes = {
  saveVideo: 92,
  resolution: 115,
  overviewNote: 116,
  modelNote: 117,
  scheduler: 124,
  unet: 127,
  clip: 128,
  duration: 132,
  h3Reference: 136,
  productImage: 137,
  prompt: 138,
  secondImage: 139,
  sizeNote: 140,
  turboToggle: 146,
};

for (const [name, id] of Object.entries(requiredNodes)) {
  if (!nodesById.has(id)) {
    throw new Error(`Official template changed: missing ${name} node ${id}`);
  }
}

const prompt = [
  "<Picture 1> is the only product identity reference.",
  "Create a five-second vertical ecommerce product film. Preserve the exact product geometry, proportions, colors, material, package structure, logo placement, and label layout as much as possible.",
  "[0:00-0:02.00] Clean warm studio background, medium close-up. The camera slowly pushes in. The product remains still while soft highlights move naturally across its surface.",
  "[0:02.00-0:04.00] The camera performs a small smooth orbit to the right, revealing the front and side material with realistic contact shadow and reflection.",
  "[0:04.00-0:05.00] Return to a centered hero shot and hold steadily.",
  "Native stereo audio: quiet studio ambience and one soft transition sound. No speech and no lyrics.",
  "Exactly one product. No duplicate, no extra brand, no subtitles, no watermark, no sudden cut, and no deformed package.",
].join("\n");

const productImage = nodesById.get(requiredNodes.productImage);
productImage.title = "Picture 1｜商品主体（必选）";
productImage.widgets_values = ["amber-serum-transparent.png", "image"];
productImage.widgets_values_named = {
  image: "amber-serum-transparent.png",
  upload: "image",
};

const secondImage = nodesById.get(requiredNodes.secondImage);
workflow.nodes = workflow.nodes.filter((node) => node.id !== secondImage.id);
workflow.links = workflow.links.filter(([linkId]) => linkId !== 282);
const h3Reference = nodesById.get(requiredNodes.h3Reference);
const image2Input = h3Reference.inputs.find((input) => input.name === "ref_images.ref_image_1");
if (!image2Input) throw new Error("Official template changed: missing second reference image slot");
image2Input.link = null;
h3Reference.title = "本地 MiniMax H3 Ref2VA｜商品多素材参考";
h3Reference.widgets_values[4] = "match";
if (h3Reference.widgets_values_named) h3Reference.widgets_values_named.ref_image_size = "match";

const promptNode = nodesById.get(requiredNodes.prompt);
promptNode.title = "电商视频提示词｜Picture 1 是商品身份";
promptNode.widgets_values = [prompt];
if (promptNode.widgets_values_named) promptNode.widgets_values_named.value = prompt;

const resolution = nodesById.get(requiredNodes.resolution);
resolution.title = "最低负载 9:16｜约 480×864";
resolution.widgets_values = ["9:16 (Portrait Widescreen)", 0.4, 32];
resolution.widgets_values_named = {
  aspect_ratio: "9:16 (Portrait Widescreen)",
  megapixels: 0.4,
  multiple: 32,
};

const duration = nodesById.get(requiredNodes.duration);
duration.title = "时长｜首次只跑 5 秒";
duration.widgets_values = [5];
if (duration.widgets_values_named) duration.widgets_values_named.value = 5;

const turboToggle = nodesById.get(requiredNodes.turboToggle);
turboToggle.title = "开启 4 步 Turbo LoRA｜首次验证推荐";
turboToggle.widgets_values = [true];
turboToggle.widgets_values_named = { value: true };

const scheduler = nodesById.get(requiredNodes.scheduler);
scheduler.title = "采样调度｜Turbo 自动切换为 4 步";

const unet = nodesById.get(requiredNodes.unet);
unet.title = "加载本地 Ref2VA 扩散模型｜约 21 GB";

const clip = nodesById.get(requiredNodes.clip);
clip.title = "加载本地 Qwen3-VL NVFP4 文本编码器｜约 15.7 GB";

const saveVideo = nodesById.get(requiredNodes.saveVideo);
saveVideo.title = "保存 5 秒竖屏商品视频";
saveVideo.widgets_values = ["ecommerce/video/minimax-h3-local-ref2va", "auto", "auto"];

const overviewNote = nodesById.get(requiredNodes.overviewNote);
overviewNote.title = "先读这里｜这是本地权重，不调用付费 API";
overviewNote.widgets_values = [
  [
    "## MiniMax H3 本地 Ref2VA｜有限配置起步版",
    "",
    "这条链路使用本地模型文件，不登录 Partner Node，也不按次扣 Credits。",
    "",
    "### 硬件结论",
    "",
    "- 当前 RTX 5060 8 GB + 15 GiB 内存：不能实际运行 H3。",
    "- 最低实验目标：24 GB 显存 + 64 GB 内存 + 80 GB 可用磁盘。",
    "- 更稳目标：32–48 GB 显存。",
    "",
    "### 本工作流的减负设置",
    "",
    "- Ref2VA pruned int8 扩散权重",
    "- Qwen3-VL 32B NVFP4 AWQ 文本编码器",
    "- 4 步 Turbo LoRA 已开启",
    "- 9:16、约 0.4 MP、5 秒、单张商品图",
    "- ref_image_size=match，避免保留 2048px 参考 token",
    "",
    "模型、下载、启动和排错：docs/04-电商AI工作流/09-MiniMax-H3本地模型有限配置工作流.md",
  ].join("\n"),
];

const modelNote = nodesById.get(requiredNodes.modelNote);
modelNote.title = "四个必需权重｜必须放到对应 models 子目录";

const sizeNote = nodesById.get(requiredNodes.sizeNote);
sizeNote.title = "画质升级顺序｜先 0.4 MP，再 0.98 MP";
sizeNote.widgets_values = [
  [
    "## 9:16 尺寸参考",
    "",
    "| megapixels | 约等于 | 用途 |",
    "|---:|---:|---|",
    "| 0.4 | 480 × 864 | 第一次验证、最低负载 |",
    "| 0.6 | 576 × 1056 | 链路稳定后比较 |",
    "| 0.98 | 768 × 1344 | 接近官方 768p 竖屏 |",
    "",
    "不要第一次就改 0.98。先确认模型、LoRA、VAE、提示词和保存链路都能运行。",
  ].join("\n"),
];

workflow.extra = {
  ...(workflow.extra || {}),
  audit: {
    derived_at: "2026-08-31",
    derived_by: "scripts/derive_minimax_h3_local_reference_video_workflow.mjs",
    source:
      "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/video_minimax_h3_r2v.json",
    source_project: "Comfy-Org/workflow_templates",
    source_license: "MIT; see THIRD_PARTY_NOTICES.md",
    modifications: [
      "Kept the official local MiniMax H3 ref2va loading, conditioning, sampling, audio/video decode, and mux chain.",
      "Reduced the starting input from two images to one required ecommerce product image.",
      "Changed output to portrait 9:16 at 0.4 megapixels and five seconds for a lower-load first test.",
      "Enabled the official four-step Ref2V Turbo LoRA path.",
      "Added a product-preservation prompt and explicit 8 GB local hardware warning.",
    ],
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
