#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [sourcePath, outputPath, profile = "standard"] = process.argv.slice(2);

if (!sourcePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_minimax_h3_local_reference_video_workflow.mjs <official-r2v.json> <output.json> [standard|quantized-nvfp4-low-vram|quantized-int8-low-vram|bf16-streaming-8gb]",
  );
  process.exit(2);
}

if (!new Set(["standard", "quantized-nvfp4-low-vram", "quantized-int8-low-vram", "bf16-streaming-8gb"]).has(profile)) {
  throw new Error(`Unknown profile: ${profile}`);
}
const quantizedNvfp4 = profile === "quantized-nvfp4-low-vram";
const quantizedInt8 = profile === "quantized-int8-low-vram";
const quantizedLowVram = quantizedNvfp4 || quantizedInt8;
const bf16Streaming8gb = profile === "bf16-streaming-8gb";
const lowMemory8gb = quantizedLowVram || bf16Streaming8gb;

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
const megapixels = lowMemory8gb ? 0.1 : 0.4;
resolution.title = lowMemory8gb
  ? "通用低显存首跑 9:16｜约 256×416"
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
  : quantizedLowVram
    ? "通用量化｜Ref2VA Pruned INT8 ConvRot｜约 19.53 GiB"
    : "加载本地 Ref2VA 扩散模型｜约 19.53 GiB";

const clip = nodesById.get(requiredNodes.clip);
clip.title = bf16Streaming8gb
  ? "8GB 流式｜Qwen3-VL BF16｜约 47.97 GiB｜未量化"
  : quantizedNvfp4
    ? "Blackwell 优化｜Qwen3-VL NVFP4 AWQ｜约 14.61 GiB"
    : quantizedInt8
      ? "兼容量化｜Qwen3-VL INT8 ConvRot｜约 25.28 GiB"
    : "加载本地 Qwen3-VL NVFP4 AWQ｜约 14.61 GiB";

const saveVideo = nodesById.get(requiredNodes.saveVideo);
saveVideo.title = "保存 5 秒竖屏商品视频";
const outputPrefix = bf16Streaming8gb
  ? "ecommerce/video/minimax-h3-bf16-streaming-8gb"
  : quantizedNvfp4
    ? "ecommerce/video/minimax-h3-quantized-nvfp4-low-vram"
    : quantizedInt8
      ? "ecommerce/video/minimax-h3-quantized-int8-low-vram"
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
}

if (quantizedInt8) {
  clip.widgets_values = [
    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "minimax",
    "default",
  ];
  clip.widgets_values_named = {
    clip_name: "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    type: "minimax",
    device: "default",
  };
  clip.properties.models = [
    {
      name: "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
      url: "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
      directory: "text_encoders",
    },
  ];
}

if (lowMemory8gb) {
  let nextNodeId = Math.max(...workflow.nodes.map((node) => node.id)) + 1;
  let nextLinkId = Math.max(...workflow.links.map(([id]) => id)) + 1;
  const lowVramId = nextNodeId++;
  const loaderLinks = unet.outputs[0].links.slice();
  const loaderToPatchLinkId = nextLinkId++;
  const lowVram = {
    id: lowVramId,
    type: "MiniMaxH3AdaptiveMemory",
    pos: [-760, 4980],
    size: [470, 330],
    flags: {},
    order: unet.order + 1,
    mode: 0,
    inputs: [
      { name: "model", type: "MODEL", link: loaderToPatchLinkId },
      { name: "enabled", type: "BOOLEAN", widget: { name: "enabled" }, link: null },
      {
        name: "profile",
        type: "COMBO",
        widget: { name: "profile" },
        link: null,
      },
      {
        name: "reserve_vram_mb",
        type: "INT",
        widget: { name: "reserve_vram_mb" },
        link: null,
      },
      {
        name: "prefetch_mode",
        type: "COMBO",
        widget: { name: "prefetch_mode" },
        link: null,
      },
      { name: "min_chunk_tokens", type: "INT", widget: { name: "min_chunk_tokens" }, link: null },
      { name: "max_chunk_tokens", type: "INT", widget: { name: "max_chunk_tokens" }, link: null },
      { name: "manual_chunk_tokens", type: "INT", widget: { name: "manual_chunk_tokens" }, link: null },
      { name: "verbose", type: "BOOLEAN", widget: { name: "verbose" }, link: null },
    ],
    outputs: [{ name: "MODEL", type: "MODEL", links: loaderLinks }],
    properties: { "Node name for S&R": "MiniMaxH3AdaptiveMemory" },
    widgets_values: bf16Streaming8gb
      ? [true, "auto_stable", 1536, "disable", 512, 4096, 2048, true]
      : [true, "auto_stable", 1024, "auto", 1024, 8192, 4096, true],
    widgets_values_named: {
      enabled: true,
      profile: "auto_stable",
      reserve_vram_mb: bf16Streaming8gb ? 1536 : 1024,
      prefetch_mode: bf16Streaming8gb ? "disable" : "auto",
      min_chunk_tokens: bf16Streaming8gb ? 512 : 1024,
      max_chunk_tokens: bf16Streaming8gb ? 4096 : 8192,
      manual_chunk_tokens: bf16Streaming8gb ? 2048 : 4096,
      verbose: true,
    },
    title: bf16Streaming8gb
      ? "自适应内存｜BF16 稳定档 + 强制关闭预取"
      : "自研自适应内存｜实时分块 + 条件预取",
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

  const clipLoader = nodesById.get(requiredNodes.clip);
  const videoVaeLoader = nodesById.get(119);
  const audioVaeLoader = nodesById.get(120);
  const sampler = nodesById.get(125);
  const finalModelSwitch = nodesById.get(141);
  if (!videoVaeLoader || !audioVaeLoader || !sampler || !finalModelSwitch) {
    throw new Error("Official template changed: missing a stage-release dependency");
  }

  const conditioningReleaseId = nextNodeId++;
  const clipReleaseLinkId = nextLinkId++;
  const videoVaeReleaseLinkId = nextLinkId++;
  const audioVaeReleaseLinkId = nextLinkId++;
  const conditioningIntoReleaseLinkId = nextLinkId++;
  const latentIntoReleaseLinkId = nextLinkId++;
  const conditioningRelease = {
    id: conditioningReleaseId,
    type: "H3ReleaseAfterConditioning",
    pos: [960, 5520],
    size: [440, 260],
    flags: {},
    order: h3Reference.order + 1,
    mode: 0,
    inputs: [
      { name: "clip", type: "CLIP", link: clipReleaseLinkId },
      { name: "video_vae", type: "VAE", link: videoVaeReleaseLinkId },
      { name: "audio_vae", type: "VAE", link: audioVaeReleaseLinkId },
      { name: "conditioning", type: "CONDITIONING", link: conditioningIntoReleaseLinkId },
      { name: "latent", type: "LATENT", link: latentIntoReleaseLinkId },
      { name: "release", type: "BOOLEAN", widget: { name: "release" }, link: null },
    ],
    outputs: [
      { name: "CONDITIONING", type: "CONDITIONING", links: [270] },
      { name: "LATENT", type: "LATENT", links: [271] },
    ],
    properties: { "Node name for S&R": "H3ReleaseAfterConditioning" },
    widgets_values: [true],
    widgets_values_named: { release: true },
    title: "阶段 1 回收｜Qwen + 参考 VAE 编码后立即卸载",
  };
  workflow.nodes.push(conditioningRelease);
  for (const link of workflow.links) {
    if (link[0] === 270) link[1] = conditioningReleaseId;
    if (link[0] === 271) link[1] = conditioningReleaseId;
  }
  h3Reference.outputs[0].links = [conditioningIntoReleaseLinkId];
  h3Reference.outputs[1].links = [latentIntoReleaseLinkId];
  clipLoader.outputs[0].links.push(clipReleaseLinkId);
  videoVaeLoader.outputs[0].links.push(videoVaeReleaseLinkId);
  audioVaeLoader.outputs[0].links.push(audioVaeReleaseLinkId);
  workflow.links.push(
    [clipReleaseLinkId, clipLoader.id, 0, conditioningReleaseId, 0, "CLIP"],
    [videoVaeReleaseLinkId, videoVaeLoader.id, 0, conditioningReleaseId, 1, "VAE"],
    [audioVaeReleaseLinkId, audioVaeLoader.id, 0, conditioningReleaseId, 2, "VAE"],
    [conditioningIntoReleaseLinkId, h3Reference.id, 0, conditioningReleaseId, 3, "CONDITIONING"],
    [latentIntoReleaseLinkId, h3Reference.id, 1, conditioningReleaseId, 4, "LATENT"],
  );

  const samplingReleaseId = nextNodeId++;
  const modelIntoSamplingReleaseLinkId = nextLinkId++;
  const samplesIntoReleaseLinkId = nextLinkId++;
  const samplingRelease = {
    id: samplingReleaseId,
    type: "H3ReleaseAfterSampling",
    pos: [2320, 5520],
    size: [420, 180],
    flags: {},
    order: sampler.order + 1,
    mode: 0,
    inputs: [
      { name: "model", type: "MODEL", link: modelIntoSamplingReleaseLinkId },
      { name: "samples", type: "LATENT", link: samplesIntoReleaseLinkId },
      { name: "release", type: "BOOLEAN", widget: { name: "release" }, link: null },
    ],
    outputs: [{ name: "LATENT", type: "LATENT", links: [280, 281] }],
    properties: { "Node name for S&R": "H3ReleaseAfterSampling" },
    widgets_values: [true],
    widgets_values_named: { release: true },
    title: "阶段 2 回收｜DiT 采样后、VAE 解码前卸载",
  };
  workflow.nodes.push(samplingRelease);
  for (const link of workflow.links) {
    if (link[0] === 280 || link[0] === 281) link[1] = samplingReleaseId;
  }
  sampler.outputs[0].links = [samplesIntoReleaseLinkId];
  finalModelSwitch.outputs[0].links.push(modelIntoSamplingReleaseLinkId);
  workflow.links.push(
    [modelIntoSamplingReleaseLinkId, finalModelSwitch.id, 0, samplingReleaseId, 0, "MODEL"],
    [samplesIntoReleaseLinkId, sampler.id, 0, samplingReleaseId, 1, "LATENT"],
  );

  const vaeDecode = nodesById.get(122);
  if (!vaeDecode || vaeDecode.type !== "VAEDecode") {
    throw new Error("Official template changed: missing VAEDecode node 122");
  }
  vaeDecode.type = "H3VAEDecodeTiledRelease";
  vaeDecode.title = "阶段 3A｜视频 VAE 分块解码后立即卸载";
  vaeDecode.size = [350, 240];
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
    { name: "release", type: "BOOLEAN", widget: { name: "release" }, link: null },
  );
  vaeDecode.properties = {
    ...(vaeDecode.properties || {}),
    "Node name for S&R": "H3VAEDecodeTiledRelease",
  };
  delete vaeDecode.properties.cnr_id;
  delete vaeDecode.properties.ver;
  vaeDecode.widgets_values = [256, 64, 32, 8, true];
  vaeDecode.widgets_values_named = {
    tile_size: 256,
    overlap: 64,
    temporal_size: 32,
    temporal_overlap: 8,
    release: true,
  };

  const videoReleaseBarrierLinkId = nextLinkId++;
  vaeDecode.outputs.push({
    name: "released",
    type: "BOOLEAN",
    links: [videoReleaseBarrierLinkId],
  });

  const audioVaeDecode = nodesById.get(121);
  if (!audioVaeDecode || audioVaeDecode.type !== "VAEDecodeAudio") {
    throw new Error("Official template changed: missing VAEDecodeAudio node 121");
  }
  audioVaeDecode.type = "H3VAEDecodeAudioRelease";
  audioVaeDecode.title = "阶段 3B｜音频 VAE 解码后立即卸载";
  audioVaeDecode.size = [340, 150];
  audioVaeDecode.inputs.push(
    {
      name: "video_release_barrier",
      type: "BOOLEAN",
      link: videoReleaseBarrierLinkId,
    },
    { name: "release", type: "BOOLEAN", widget: { name: "release" }, link: null },
  );
  audioVaeDecode.properties = {
    ...(audioVaeDecode.properties || {}),
    "Node name for S&R": "H3VAEDecodeAudioRelease",
  };
  delete audioVaeDecode.properties.cnr_id;
  delete audioVaeDecode.properties.ver;
  audioVaeDecode.widgets_values = [true];
  audioVaeDecode.widgets_values_named = { release: true };
  workflow.links.push([
    videoReleaseBarrierLinkId,
    vaeDecode.id,
    1,
    audioVaeDecode.id,
    2,
    "BOOLEAN",
  ]);
}

const overviewNote = nodesById.get(requiredNodes.overviewNote);
overviewNote.title = "先读这里｜这是本地权重，不调用付费 API";
const overviewText = [
    bf16Streaming8gb
      ? "## MiniMax H3 本地 Ref2VA｜BF16 磁盘流式实验版"
      : quantizedLowVram
        ? "## MiniMax H3 本地 Ref2VA｜通用量化低显存首跑版"
        : "## MiniMax H3 本地 Ref2VA｜有限配置起步版",
    "",
    "这条链路使用本地模型文件，不登录 Partner Node，也不按次扣 Credits。",
    "",
    "### 硬件结论",
    "",
    bf16Streaming8gb
      ? "- RTX 5060 8 GB + Windows 32 GB 已完成 BF16 最低规格实跑，但磁盘读取压力很高。"
      : quantizedLowVram
        ? "- 本配置以 8 GB 显存为保守首跑档；12/16/24 GB 可逐级提高分块和分辨率。"
        : "- 标准模板保留官方量化权重，仍需根据显存逐级降低输出规格。",
    bf16Streaming8gb
      ? "- 全套权重约 93 GiB；DynamicVRAM 会大量按需读取 NVMe。"
      : quantizedLowVram
        ? `- 全套必需文件约 ${quantizedNvfp4 ? "41.38" : "52.04"} GiB；编码器格式必须按 GPU 原生算子能力选择。`
        : "- 本标准版使用官方 ComfyUI 模板的量化组合。",
    bf16Streaming8gb
      ? "- 扩散模型与文本编码器均为 BF16，VAE 为官方 FP16/FP32，没有使用低比特量化。"
      : "- 扩散模型使用 INT8 ConvRot，Qwen3-VL 使用 NVFP4 AWQ；VAE 与 LoRA 保持官方精度。",
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
    lowMemory8gb
      ? "- 9:16、约 0.1 MP、5 秒、单张商品图"
      : "- 9:16、约 0.4 MP、5 秒、单张商品图",
    bf16Streaming8gb
      ? "- H3 MLP 按实时显存自适应分块、关闭 block prefetch、VAE 分块解码"
      : quantizedLowVram
        ? "- H3 MLP 按实时显存自适应分块；仅在异步流、显存和内存都允许时预取"
        : "",
    lowMemory8gb
      ? "- Qwen/参考 VAE 编码后定向卸载；DiT 采样后再定向卸载，避免三阶段同时驻留"
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
  : quantizedLowVram
    ? `五个官方量化组合文件｜约 ${quantizedNvfp4 ? "41.38" : "52.04"} GiB`
    : "五个必需权重｜必须放到对应 models 子目录";
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
} else if (quantizedLowVram) {
  const quantizedModelNote = [
    "## 通用量化低显存首跑版所需文件",
    "",
    "所有文件均来自 `Comfy-Org/MiniMax-H3`，模型选择与官方 R2V 模板一致。",
    "",
    "```text",
    "ComfyUI-Shared/models/",
    "├── diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    `├── text_encoders/${quantizedNvfp4 ? "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" : "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"}`,
    "├── vae/minimax_h3_video_vae_fp16.safetensors",
    "├── vae/minimax_h3_audio_vae_fp32.safetensors",
    "└── loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
    "```",
    "",
    quantizedNvfp4
      ? "扩散模型为 pruned INT8 ConvRot，文本/视觉编码器为 NVFP4 AWQ。NVFP4 只推荐给原生支持的 NVIDIA SM 10+。"
      : "扩散模型和文本/视觉编码器均使用 INT8 ConvRot。这是 NVIDIA SM 7.5/8.x/8.9 的兼容候选，仍必须通过当前 comfy-kitchen 日志和完整短片验证。",
    "",
    "下载脚本：`scripts/download_minimax_h3_quantized_windows.cmd`",
  ].join("\n");
  modelNote.widgets_values = [quantizedModelNote];
  modelNote.widgets_values_named = { text: quantizedModelNote };
}

const sizeNote = nodesById.get(requiredNodes.sizeNote);
sizeNote.title = lowMemory8gb
  ? "通用低显存升级顺序｜0.1 MP 跑通后只升一档"
  : "画质升级顺序｜先 0.4 MP，再 0.98 MP";
const sizeNoteText = [
    "## 9:16 尺寸参考",
    "",
    "| megapixels | 约等于 | 用途 |",
    "|---:|---:|---|",
    `| 0.1 | 约 256 × 416 | ${quantizedLowVram ? "8 GB 量化首跑" : "8 GB BF16 首次验证"} |`,
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
        ? "Kept BF16 diffusion/text weights and official VAE precision; added live-VRAM H3 MLP chunking, staged model release, disabled block prefetch, tiled video VAE decode, and a 0.1 MP first-run profile."
        : quantizedLowVram
          ? `Kept the official INT8 ConvRot diffusion and ${quantizedNvfp4 ? "NVFP4 AWQ" : "INT8 ConvRot"} text encoder; added live-VRAM H3 MLP chunking, conditional block prefetch, staged Qwen/DiT/VAE release, tiled video VAE decode, and a conservative 0.1 MP first-run profile.`
          : "Added a product-preservation prompt and explicit hardware guidance.",
    ],
    profile,
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
