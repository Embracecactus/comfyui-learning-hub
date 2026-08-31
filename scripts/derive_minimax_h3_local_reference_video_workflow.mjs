#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [sourcePath, outputPath, profile = "standard"] = process.argv.slice(2);

if (!sourcePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_minimax_h3_local_reference_video_workflow.mjs <official-r2v.json> <output.json> [standard|bf16-streaming-8gb]",
  );
  process.exit(2);
}

if (!new Set(["standard", "bf16-streaming-8gb"]).has(profile)) {
  throw new Error(`Unknown profile: ${profile}`);
}
const bf16Streaming8gb = profile === "bf16-streaming-8gb";

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
const megapixels = bf16Streaming8gb ? 0.1 : 0.4;
resolution.title = bf16Streaming8gb
  ? "8 GB 极限实验 9:16｜约 256×416"
  : "最低负载 9:16｜约 480×864";
resolution.widgets_values = ["9:16 (Portrait Widescreen)", megapixels, 32];
resolution.widgets_values_named = {
  aspect_ratio: "9:16 (Portrait Widescreen)",
  megapixels,
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
unet.title = bf16Streaming8gb
  ? "8GB 流式｜Ref2VA Pruned BF16｜约 37.46 GiB｜未量化"
  : "加载本地 Ref2VA 扩散模型｜约 21 GB";

const clip = nodesById.get(requiredNodes.clip);
clip.title = bf16Streaming8gb
  ? "8GB 流式｜Qwen3-VL BF16｜约 47.97 GiB｜未量化"
  : "加载本地 Qwen3-VL NVFP4 文本编码器｜约 15.7 GB";

const saveVideo = nodesById.get(requiredNodes.saveVideo);
saveVideo.title = "保存 5 秒竖屏商品视频";
const outputPrefix = bf16Streaming8gb
  ? "ecommerce/video/minimax-h3-bf16-streaming-8gb"
  : "ecommerce/video/minimax-h3-local-ref2va";
saveVideo.widgets_values = [
  outputPrefix,
  "auto",
  "auto",
];
saveVideo.widgets_values_named = {
  filename_prefix: outputPrefix,
  format: "auto",
  codec: "auto",
};

if (bf16Streaming8gb) {
  unet.widgets_values = ["minimax_h3_ref2va_pruned_bf16.safetensors", "default"];
  unet.widgets_values_named = {
    unet_name: "minimax_h3_ref2va_pruned_bf16.safetensors",
    weight_dtype: "default",
  };
  unet.properties.models = [
    {
      name: "minimax_h3_ref2va_pruned_bf16.safetensors",
      url: "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors",
      directory: "diffusion_models",
    },
  ];
  clip.widgets_values = [
    "qwen3vl_32b_minimax_h3_bf16.safetensors",
    "minimax",
    "default",
  ];
  clip.widgets_values_named = {
    clip_name: "qwen3vl_32b_minimax_h3_bf16.safetensors",
    type: "minimax",
    device: "default",
  };
  clip.properties.models = [
    {
      name: "qwen3vl_32b_minimax_h3_bf16.safetensors",
      url: "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors",
      directory: "text_encoders",
    },
  ];

  const lowVramId = Math.max(...workflow.nodes.map((node) => node.id)) + 1;
  const loaderLinks = unet.outputs[0].links.slice();
  const loaderToPatchLinkId = Math.max(...workflow.links.map(([id]) => id)) + 1;
  const lowVram = {
    id: lowVramId,
    type: "MiniMaxH3LowVRAM",
    pos: [-760, 4980],
    size: [430, 230],
    flags: {},
    order: unet.order + 1,
    mode: 0,
    inputs: [
      { name: "model", type: "MODEL", link: loaderToPatchLinkId },
      { name: "enabled", type: "BOOLEAN", widget: { name: "enabled" }, link: null },
      {
        name: "memory_profile",
        type: "COMBO",
        widget: { name: "memory_profile" },
        link: null,
      },
      {
        name: "custom_chunk_tokens",
        type: "INT",
        widget: { name: "custom_chunk_tokens" },
        link: null,
      },
      {
        name: "block_prefetch",
        type: "COMBO",
        widget: { name: "block_prefetch" },
        link: null,
      },
      { name: "verbose", type: "BOOLEAN", widget: { name: "verbose" }, link: null },
    ],
    outputs: [{ name: "MODEL", type: "MODEL", links: loaderLinks }],
    properties: { "Node name for S&R": "MiniMaxH3LowVRAM" },
    widgets_values: [true, "minimum_vram", 2048, "disable", true],
    widgets_values_named: {
      enabled: true,
      memory_profile: "minimum_vram",
      custom_chunk_tokens: 2048,
      block_prefetch: "disable",
      verbose: true,
    },
    title: "8GB 等价计算补丁｜MLP 2048 token 分块 + 关闭预取",
  };
  workflow.nodes.push(lowVram);
  for (const link of workflow.links) {
    if (loaderLinks.includes(link[0]) && link[1] === unet.id) link[1] = lowVramId;
  }
  workflow.links.push([
    loaderToPatchLinkId,
    unet.id,
    0,
    lowVramId,
    0,
    "MODEL",
  ]);
  unet.outputs[0].links = [loaderToPatchLinkId];

  const vaeDecode = nodesById.get(122);
  if (!vaeDecode || vaeDecode.type !== "VAEDecode") {
    throw new Error("Official template changed: missing VAEDecode node 122");
  }
  vaeDecode.type = "VAEDecodeTiled";
  vaeDecode.title = "视频 VAE 分块解码｜256px / 32 帧";
  vaeDecode.size = [280, 200];
  vaeDecode.inputs.push(
    { name: "tile_size", type: "INT", widget: { name: "tile_size" }, link: null },
    { name: "overlap", type: "INT", widget: { name: "overlap" }, link: null },
    { name: "temporal_size", type: "INT", widget: { name: "temporal_size" }, link: null },
    {
      name: "temporal_overlap",
      type: "INT",
      widget: { name: "temporal_overlap" },
      link: null,
    },
  );
  vaeDecode.properties = {
    ...(vaeDecode.properties || {}),
    cnr_id: "comfy-core",
    ver: "0.33.0",
    "Node name for S&R": "VAEDecodeTiled",
  };
  vaeDecode.widgets_values = [256, 64, 32, 8];
  vaeDecode.widgets_values_named = {
    tile_size: 256,
    overlap: 64,
    temporal_size: 32,
    temporal_overlap: 8,
  };
}

const overviewNote = nodesById.get(requiredNodes.overviewNote);
overviewNote.title = "先读这里｜这是本地权重，不调用付费 API";
const overviewText = [
    "## MiniMax H3 本地 Ref2VA｜有限配置起步版",
    "",
    "这条链路使用本地模型文件，不登录 Partner Node，也不按次扣 Credits。",
    "",
    "### 硬件结论",
    "",
    bf16Streaming8gb
      ? "- 当前 RTX 5060 8 GB + 16 GB 内存：使用 BF16 磁盘映射与逐层卸载进行极限实验。"
      : "- 当前 RTX 5060 8 GB + 16 GB 内存：请改用配套 BF16 流式 8GB 版。",
    bf16Streaming8gb
      ? "- 全套权重约 93 GiB；必须使用 NVMe 和足够页面文件，目标是跑完而不是实时。"
      : "- 本标准版仍建议 24 GB 显存 + 64 GB 内存。",
    bf16Streaming8gb
      ? "- 扩散模型与文本编码器均为 BF16，VAE 为官方 FP16/FP32，没有使用低比特量化。"
      : "- 标准版使用官方 ComfyUI 重打包权重。",
    "",
    "### 本工作流的减负设置",
    "",
    bf16Streaming8gb
      ? "- Ref2VA AdaLN-pruned BF16（结构剪枝，不是数值量化）"
      : "- Ref2VA pruned int8 扩散权重",
    bf16Streaming8gb
      ? "- Qwen3-VL 32B BF16 文本/视觉编码器"
      : "- Qwen3-VL 32B NVFP4 AWQ 文本编码器",
    "- 4 步 Turbo LoRA 已开启",
    bf16Streaming8gb
      ? "- 9:16、约 0.1 MP、5 秒、单张商品图"
      : "- 9:16、约 0.4 MP、5 秒、单张商品图",
    bf16Streaming8gb
      ? "- H3 MLP 2048 token 等价分块、关闭 block prefetch、VAE 分块解码"
      : "",
    "- ref_image_size=match，避免保留 2048px 参考 token",
    "",
    "模型、下载、启动和排错：docs/04-电商AI工作流/09-MiniMax-H3本地模型有限配置工作流.md",
  ].join("\n");
overviewNote.widgets_values = [overviewText];
overviewNote.widgets_values_named = { text: overviewText };

const modelNote = nodesById.get(requiredNodes.modelNote);
modelNote.title = bf16Streaming8gb
  ? "五个 BF16/FP 权重｜约 93 GiB｜没有低比特量化"
  : "四个必需权重｜必须放到对应 models 子目录";
if (bf16Streaming8gb) {
  const bf16ModelNote = [
    "## 8 GB 无量化流式版所需文件",
    "",
    "所有文件均来自 `Comfy-Org/MiniMax-H3`。扩散模型与文本编码器为 BF16，视频/音频 VAE 为 FP16/FP32。",
    "",
    "```text",
    "ComfyUI-Shared/models/",
    "├── diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors",
    "├── text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors",
    "├── vae/minimax_h3_video_vae_fp16.safetensors",
    "├── vae/minimax_h3_audio_vae_fp32.safetensors",
    "└── loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
    "```",
    "",
    "`pruned` 是移除一部分 AdaLN 结构权重，不是把 BF16 数值压成 INT8/FP8。若要求原始未剪枝模型，可换 `minimax_h3_ref2va_bf16.safetensors`，但文件约 61.73 GiB，当前机器更难完成。",
    "",
    "下载脚本：`scripts/download_minimax_h3_bf16_windows.cmd`",
  ].join("\n");
  modelNote.widgets_values = [bf16ModelNote];
  modelNote.widgets_values_named = { text: bf16ModelNote };
}

const sizeNote = nodesById.get(requiredNodes.sizeNote);
sizeNote.title = bf16Streaming8gb
  ? "8GB 升级顺序｜0.1 MP 跑通后只升一档"
  : "画质升级顺序｜先 0.4 MP，再 0.98 MP";
const sizeNoteText = [
    "## 9:16 尺寸参考",
    "",
    "| megapixels | 约等于 | 用途 |",
    "|---:|---:|---|",
    "| 0.1 | 约 256 × 416 | 8 GB 无量化首次验证 |",
    "| 0.2 | 约 352 × 608 | 首次完整成功后再试 |",
    "| 0.4 | 480 × 864 | 第一次验证、最低负载 |",
    "| 0.6 | 576 × 1056 | 链路稳定后比较 |",
    "| 0.98 | 768 × 1344 | 接近官方 768p 竖屏 |",
    "",
    "不要第一次就改 0.98。先确认模型、LoRA、VAE、提示词和保存链路都能运行。",
  ].join("\n");
sizeNote.widgets_values = [sizeNoteText];
sizeNote.widgets_values_named = { text: sizeNoteText };

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
      `Changed output to portrait 9:16 at ${megapixels} megapixels and five seconds for a lower-load first test.`,
      "Enabled the official four-step Ref2V Turbo LoRA path.",
      bf16Streaming8gb
        ? "Kept BF16 diffusion/text weights and official VAE precision; added H3 MLP chunking, disabled block prefetch, tiled video VAE decode, and a 0.1 MP first-run profile for disk-backed execution on 8 GB VRAM."
        : "Added a product-preservation prompt and explicit hardware guidance.",
    ],
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
