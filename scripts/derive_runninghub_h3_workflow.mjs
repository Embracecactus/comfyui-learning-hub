#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const defaultSource = path.join(
  repoRoot,
  "docs/04-电商AI工作流/workflows/ecommerce-yinghai-copy-hot-video-h3-nvfp4-0.2mp.json",
);
const defaultTarget = path.join(
  repoRoot,
  "docs/04-电商AI工作流/workflows/yinghai-h3-runninghub-0.2mp.json",
);

const sourcePath = path.resolve(process.argv[2] ?? defaultSource);
const targetPath = path.resolve(process.argv[3] ?? defaultTarget);
const workflow = JSON.parse(fs.readFileSync(sourcePath, "utf8"));
const hoodieSecondHalfProfile = path.basename(sourcePath).includes("hoodie-second-half");
const profile = hoodieSecondHalfProfile
  ? "rh-h3-hoodie-v3"
  : "yinghai-copy-hot-video-h3-runninghub-0.2mp";

const nodesById = new Map(workflow.nodes.map((node) => [node.id, node]));
const expectedNodes = new Map([
  [121, "H3VAEDecodeAudioRelease"],
  [122, "H3VAEDecodeTiledRelease"],
  [151, "H3ReferenceVideoFrames24FPS"],
  [152, "MiniMaxH3AdaptiveMemory"],
  [153, "H3ReleaseAfterConditioning"],
  [154, "H3ReleaseAfterSampling"],
]);

for (const [id, type] of expectedNodes) {
  if (nodesById.get(id)?.type !== type) {
    throw new Error(`Source workflow drifted: expected node ${id} to be ${type}`);
  }
}

// RunningHub does not carry this repository's low-memory extension. Keep the
// graph semantics, but replace its decode wrappers with ComfyUI core nodes and
// bypass its model/resource-release pass-through nodes.
const audioDecode = nodesById.get(121);
Object.assign(audioDecode, {
  type: "VAEDecodeAudio",
  size: [230, 60],
  title: "RunningHub 官方节点｜音频 VAE 解码",
  inputs: audioDecode.inputs.slice(0, 2),
  outputs: audioDecode.outputs.slice(0, 1),
  properties: {
    cnr_id: "comfy-core",
    ver: "0.33.0",
    "Node name for S&R": "VAEDecodeAudio",
  },
  widgets_values: [],
  widgets_values_named: {},
});

const videoDecode = nodesById.get(122);
Object.assign(videoDecode, {
  type: "VAEDecode",
  size: [230, 60],
  title: "RunningHub 官方节点｜视频 VAE 解码",
  inputs: videoDecode.inputs.slice(0, 2),
  outputs: videoDecode.outputs.slice(0, 1),
  properties: {
    cnr_id: "comfy-core",
    ver: "0.33.0",
    "Node name for S&R": "VAEDecode",
  },
  widgets_values: [],
  widgets_values_named: {},
});

const removedNodeIds = new Set([151, 152, 153, 154]);
workflow.nodes = workflow.nodes.filter((node) => !removedNodeIds.has(node.id));

const removedLinkIds = new Set([
  295,
  296,
  298,
  299,
  300,
  301,
  302,
  303,
  304,
  305,
  306,
]);

const sourceRewrites = new Map([
  // UNETLoader directly feeds the scheduler, LoRA branch, and raw-model branch.
  [252, [127, 0]],
  [285, [127, 0]],
  [287, [127, 0]],
  // MiniMaxH3ReferenceToVideo directly feeds conditioning and the sampler latent.
  [270, [136, 0]],
  [271, [136, 1]],
  // The sampled AV latent directly feeds the two official decoders.
  [280, [125, 0]],
  [281, [125, 0]],
  // MiniMaxH3ReferenceToVideo itself trims the batch to a legal 17n+5 length.
  [297, [150, 0]],
]);

workflow.links = workflow.links
  .filter((link) => !removedLinkIds.has(link[0]))
  .map((link) => {
    const rewrite = sourceRewrites.get(link[0]);
    if (rewrite) {
      link[1] = rewrite[0];
      link[2] = rewrite[1];
    }
    return link;
  });

// Rebuild every serialized input/output link list from the authoritative link
// table so the exported graph cannot retain a dangling custom-node reference.
const remainingNodesById = new Map(workflow.nodes.map((node) => [node.id, node]));
for (const node of workflow.nodes) {
  for (const input of node.inputs ?? []) input.link = null;
  for (const output of node.outputs ?? []) output.links = null;
}

for (const [linkId, sourceId, sourceSlot, targetId, targetSlot] of workflow.links) {
  const source = remainingNodesById.get(sourceId);
  const target = remainingNodesById.get(targetId);
  if (!source || !target) {
    throw new Error(`Dangling link ${linkId}: ${sourceId} -> ${targetId}`);
  }
  const output = source.outputs?.[sourceSlot];
  const input = target.inputs?.[targetSlot];
  if (!output || !input) {
    throw new Error(`Invalid slot on link ${linkId}: ${sourceId}:${sourceSlot} -> ${targetId}:${targetSlot}`);
  }
  output.links ??= [];
  output.links.push(linkId);
  input.link = linkId;
}

const updateNode = (id, update) => {
  const node = remainingNodesById.get(id);
  if (!node) throw new Error(`Missing node ${id}`);
  update(node);
};

// Uploaded media is account-specific. Empty fields make RunningHub ask the user
// for the two required inputs instead of retaining invalid local filenames.
updateNode(137, (node) => {
  node.title = hoodieSecondHalfProfile
    ? "① 上传1977卫衣商品图｜Picture 1（固定验收）"
    : "① 上传商品/服装主图｜Picture 1（必选）";
  node.widgets_values = ["", "image"];
  node.widgets_values_named = { image: "", upload: "image" };
});
updateNode(147, (node) => {
  node.title = hoodieSecondHalfProfile
    ? "② 上传24FPS完整对标视频｜Video 1（取5.0–10.2秒）"
    : "② 上传动作参考视频｜Video 1（建议 24 FPS、至少 5.2 秒）";
  node.widgets_values = [""];
  node.widgets_values_named = { file: "" };
});
updateNode(138, (node) => {
  node.title = hoodieSecondHalfProfile
    ? "③ 固定验收提示词｜不要修改"
    : "③ 填写提示词｜商品身份用 Picture 1，动作镜头用 Video 1";
  if (hoodieSecondHalfProfile) {
    const prompt = node.widgets_values?.[0] ?? "";
    for (const requiredText of [
      "black pullover hoodie",
      "long sleeves",
      "exact white 1977 chest print",
      "Do not copy the white off-shoulder top",
    ]) {
      if (!prompt.includes(requiredText)) {
        throw new Error(`Hoodie validation prompt lost required text: ${requiredText}`);
      }
    }
  }
});
updateNode(149, (node) => {
  node.title = "Video 1｜拆分视频帧（音频不参与参考）";
});
updateNode(150, (node) => {
  node.title = "Video 1｜整批帧缩至 0.1 MP 后交给 H3 自动裁帧";
});
updateNode(92, (node) => {
  node.title = "④ 下载 RunningHub 生成的视频";
  const prefix = hoodieSecondHalfProfile
    ? "ecommerce/video/rh-h3-hoodie-v3"
    : "ecommerce/video/yinghai-copy-hot-video-h3-runninghub-0.2mp";
  node.widgets_values[0] = prefix;
  node.widgets_values_named = {
    ...(node.widgets_values_named ?? {}),
    filename_prefix: prefix,
  };
});

updateNode(116, (node) => {
  node.title = hoodieSecondHalfProfile
    ? "先读这里｜严格复跑本地已通过条件"
    : "先读这里｜RunningHub 兼容版";
  const text = hoodieSecondHalfProfile
    ? "## RunningHub H3 卫衣固定验收 V3\n\n" +
      "这不是通用模板，而是本地已通过案例的云端等条件复跑。不要先改商品、视频、提示词或参数。\n\n" +
      "1. ① 上传同一张黑色 1977 卫衣平铺图。\n" +
      "2. 先在本机把完整对标视频转换为 24 FPS，再在 ② 上传；本图固定截取 5.0–10.2 秒。\n" +
      "3. ③ 已恢复本地通过版的 hoodie、long sleeves、hood、pocket、cuffs 和 1977 强约束，不要修改。\n" +
      "4. 保持 0.2 MP、124 帧、4 步 Turbo 和固定 seed。\n\n" +
      "验收：黑色连帽卫衣、长袖、宽松轮廓和胸前 1977 必须出现；仍是原白色上衣或其他服装就判失败。"
    : "## RunningHub 首次导入与测试\n\n" +
      "这是独立的平台兼容版，不需要本仓库的 `comfyui_adaptive_memory` 节点。\n\n" +
      "1. 在 ① 上传一张商品或服装主图。\n" +
      "2. 在 ② 上传动作参考视频；建议预先转为 24 FPS，并保证至少 5.2 秒。\n" +
      "3. 在 ③ 修改提示词；`<Picture 1>` 表示商品身份，`<Video 1>` 只表示动作、镜头、节奏和场景。\n" +
      "4. 首次保持 9:16、0.2 MP、5 秒和 4 步 Turbo，不要同时改多个参数。\n\n" +
      "参考视频帧会直接交给官方 `MiniMaxH3ReferenceToVideo`；该节点会裁到 H3 合法的 `17n+5` 帧数。非 24 FPS 视频仍能导入，但动作速度不一定与原片一致。";
  node.widgets_values = [text];
  node.widgets_values_named = { text };
});
updateNode(140, (node) => {
  node.title = "RunningHub 升级顺序｜先 0.2 MP 跑通";
  const text =
    "## RunningHub 画质升级建议\n\n" +
      "| 阶段 | 设置 | 目的 |\n|---|---|---|\n" +
      "| 首跑 | 9:16、0.2 MP、5 秒、4 步 | 验证节点、模型和媒体输入 |\n" +
      "| 第二次 | 9:16、0.4 MP、5 秒、4 步 | 检查商品一致性与动作跟随 |\n" +
      "| 定稿 | 0.6 MP 或更高 | 确认前两档稳定后再增加成本 |\n\n" +
      "若模型下拉框变红，优先在 RunningHub 下拉框中选择同名 H3 模型，不要重新安装本地低显存节点。";
  node.widgets_values = [text];
  node.widgets_values_named = { text };
});

workflow.last_node_id = Math.max(...workflow.nodes.map((node) => node.id));
workflow.last_link_id = Math.max(...workflow.links.map((link) => link[0]));
workflow.extra ??= {};
workflow.extra.audit = {
  ...(workflow.extra.audit ?? {}),
  derived_at: "2026-09-02",
  derived_by: "scripts/derive_runninghub_h3_workflow.mjs",
  target_platform: "RunningHub",
  source_workflow: path.relative(repoRoot, sourcePath),
  profile,
  compatibility_reference: "https://www.runninghub.ai/post/2084160024145948674",
  modifications: [
    "Removed the four project-only adaptive-memory and staged-release pass-through nodes.",
    "Replaced the two project-only release decoders with ComfyUI core VAEDecode and VAEDecodeAudio.",
    "Connected scaled reference frames directly to the official MiniMaxH3ReferenceToVideo node, which trims to a legal 17n+5 frame count.",
    "Cleared machine-local image and video filenames so RunningHub exposes explicit upload requirements.",
    "Kept the 0.2 MP, five-second, four-step Turbo validation profile and the Picture 1 / Video 1 ecommerce prompt contract.",
    ...(hoodieSecondHalfProfile
      ? [
          "Preserved the locally validated 5.0-10.2 second slice and the exact 1977 hoodie identity prompt.",
          "Requires a 24 fps full-length reference upload because the project-only frame resampler is unavailable on RunningHub.",
        ]
      : []),
  ],
};

const forbiddenTypes = new Set([...expectedNodes.values()]);
const remainingForbidden = workflow.nodes.filter((node) => forbiddenTypes.has(node.type));
if (remainingForbidden.length) {
  throw new Error(`RunningHub graph still contains project nodes: ${remainingForbidden.map((node) => node.type).join(", ")}`);
}

fs.mkdirSync(path.dirname(targetPath), { recursive: true });
fs.writeFileSync(targetPath, `${JSON.stringify(workflow, null, 2)}\n`);
console.log(`Wrote ${path.relative(repoRoot, targetPath)} (${workflow.nodes.length} nodes, ${workflow.links.length} links)`);
