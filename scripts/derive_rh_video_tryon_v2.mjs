#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const defaultTarget = path.join(
  repoRoot,
  "docs/04-电商AI工作流/workflows/rh-video-tryon-v2.json",
);

const sourceWorkflowId = "2025934636399988738";
const sourcePage = `https://www.runninghub.cn/post/${sourceWorkflowId}`;
const sourceExportApi = "https://www.runninghub.cn/api/workflow/export";
const expectedSourceSha256 =
  "81308448f84f78327032ad700e37d6953828b6d8c8e02123ca2dc0b22bf5da3b";
const expectedVhsVersion = "8e4d79471bf1952154768e8435a9300077b534fa";

const sourceArgument = process.argv[2];
const targetPath = path.resolve(process.argv[3] ?? defaultTarget);

async function loadSource() {
  if (sourceArgument) {
    const sourcePath = path.resolve(sourceArgument);
    return {
      buffer: fs.readFileSync(sourcePath),
      description: path.relative(repoRoot, sourcePath),
    };
  }

  const response = await fetch(sourceExportApi, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflowId: sourceWorkflowId }),
    signal: AbortSignal.timeout(45_000),
  });
  if (!response.ok) {
    throw new Error(`RunningHub export failed: HTTP ${response.status}`);
  }
  return {
    buffer: Buffer.from(await response.arrayBuffer()),
    description: sourceExportApi,
  };
}

const loaded = await loadSource();
const loadedSha256 = crypto.createHash("sha256").update(loaded.buffer).digest("hex");
const workflow = JSON.parse(loaded.buffer.toString("utf8"));

if (!Array.isArray(workflow.nodes) || !Array.isArray(workflow.links)) {
  throw new Error("Source is not a ComfyUI workflow JSON");
}

const isGeneratedInput =
  workflow.extra?.audit?.profile === "rh-video-tryon-v2";
if (!isGeneratedInput && loadedSha256 !== expectedSourceSha256) {
  throw new Error(
    "RunningHub public source changed. Review the new graph before updating " +
      `expectedSourceSha256 (expected ${expectedSourceSha256}, got ${loadedSha256}).`,
  );
}

const expectedNodes = new Map([
  [61, "VHS_LoadVideo"],
  [75, "LoadImage"],
  [97, "WanVideoClipVisionEncode"],
  [102, "ClothesSegment"],
  [113, "SeCVideoSegmentation"],
  [115, "WanVideoModelLoader"],
  [92, "WanVideoAnimateEmbeds"],
  [86, "WanVideoSampler"],
  [67, "VHS_VideoCombine"],
  [71, "JWInteger"],
  [72, "JWInteger"],
  [139, "Int"],
]);

let nodesById = new Map(workflow.nodes.map((node) => [node.id, node]));
for (const [id, type] of expectedNodes) {
  if (nodesById.get(id)?.type !== type) {
    throw new Error(`Source workflow drifted: expected node ${id} to be ${type}`);
  }
}
if (nodesById.get(61)?.properties?.ver !== expectedVhsVersion) {
  throw new Error(
    `VHS_LoadVideo version drifted: expected ${expectedVhsVersion}`,
  );
}

const hasLink = (sourceId, sourceSlot, targetId, targetSlot) =>
  workflow.links.some(
    (link) =>
      link[1] === sourceId &&
      link[2] === sourceSlot &&
      link[3] === targetId &&
      link[4] === targetSlot,
  );

for (const contract of [
  [75, 0, 98, 0],
  [98, 0, 97, 1],
  [97, 0, 92, 1],
  [98, 0, 92, 2],
  [61, 0, 42, 0],
  [42, 0, 102, 0],
  [102, 1, 113, 3],
  [61, 0, 113, 1],
  [113, 0, 57, 0],
  [59, 0, 82, 1],
  [82, 0, 92, 5],
  [59, 0, 92, 6],
]) {
  if (!hasLink(...contract)) {
    throw new Error(
      `Source workflow contract drifted: missing ${contract[0]}:${contract[1]} -> ${contract[2]}:${contract[3]}`,
    );
  }
}

const sourceAdjacency = new Map();
for (const [, sourceId, , targetId] of workflow.links) {
  if (!sourceAdjacency.has(sourceId)) sourceAdjacency.set(sourceId, new Set());
  sourceAdjacency.get(sourceId).add(targetId);
}
const isReachable = (start, target) => {
  const pending = [start];
  const visited = new Set(pending);
  while (pending.length) {
    const current = pending.pop();
    if (current === target) return true;
    for (const next of sourceAdjacency.get(current) ?? []) {
      if (!visited.has(next)) {
        visited.add(next);
        pending.push(next);
      }
    }
  }
  return false;
};
if (isReachable(61, 97)) {
  throw new Error("Source video reaches the garment CLIP encoder; identity isolation is broken");
}

const updateNode = (id, update) => {
  const node = nodesById.get(id);
  if (!node) throw new Error(`Missing node ${id}`);
  update(node);
};

// Uploaded media and generated previews belong to a specific RunningHub account.
// Remove them so an imported workflow cannot silently reuse somebody else's demo.
for (const node of workflow.nodes) {
  if (node.widgets_values && !Array.isArray(node.widgets_values)) {
    if ("videopreview" in node.widgets_values) {
      node.widgets_values.videopreview = {
        paused: false,
        hidden: false,
        params: {},
      };
    }
  }
}

updateNode(75, (node) => {
  node.title = "① 上传商品服装图｜服装身份唯一来源";
  node.color = "#1f4d3d";
  node.bgcolor = "#2b5d4b";
  node.widgets_values = ["", "image"];
});

updateNode(61, (node) => {
  node.title = "② 上传参考视频｜提供人物动作镜头场景，不进服装编码";
  node.color = "#49345f";
  node.bgcolor = "#60437a";
  node.widgets_values = {
    ...node.widgets_values,
    custom_height: 768,
    force_rate: 10,
    custom_width: 432,
    select_every_nth: 1,
    frame_load_cap: 49,
    video: "",
    skip_first_frames: 0,
    // In the serialized VHS version used by RunningHub, force_size is a
    // deprecated hidden value. Non-zero custom_width/custom_height inputs do
    // the actual resize even while this legacy field says Disabled.
    force_size: "Disabled",
    "choose video to upload": "image",
    videopreview: { paused: false, hidden: false, params: {} },
  };
});

updateNode(71, (node) => {
  node.title = "③ 首跑宽度｜432";
  node.widgets_values = [432];
});
updateNode(72, (node) => {
  node.title = "④ 首跑高度｜768";
  node.widgets_values = [768];
});
updateNode(139, (node) => {
  node.title = "⑤ 首跑帧率｜10 FPS";
  node.widgets_values = [10];
});

updateNode(102, (node) => {
  node.title = "⑥ 原视频服装区域｜默认抹掉全部衣服类别";
  // Hat, Hair, Face, Sunglasses, Upper-clothes, Skirt, Dress, Belt,
  // Pants, arms, legs, Bag, Scarf, shoes, Background, then processing values.
  // The default masks all clothing plus both arms so the long-sleeve hoodie
  // acceptance case can replace a sleeveless dress. Face, hair, accessories,
  // legs, shoes, and background remain untouched. Users can narrow this after
  // the first pass.
  node.widgets_values = [
    false, // Hat
    false, // Hair
    false, // Face
    false, // Sunglasses
    true, // Upper-clothes
    true, // Skirt
    true, // Dress
    true, // Belt
    true, // Pants
    true, // Left-arm
    true, // Right-arm
    false, // Left-leg
    false, // Right-leg
    false, // Bag
    false, // Scarf
    false, // Left-shoe
    false, // Right-shoe
    false, // Background
    512,
    0,
    0,
    false,
    "Alpha",
    "#222222",
  ];
});

updateNode(113, (node) => {
  node.title = "⑦ 把首帧服装遮罩追踪到整段视频";
});
updateNode(82, (node) => {
  node.title = "⑧ 擦除原视频服装｜阻止原衣服继续支配结果";
});
updateNode(97, (node) => {
  node.title = "⑨ 商品服装身份编码｜只读取①";
});
updateNode(92, (node) => {
  node.title = "⑩ 视频重绘｜商品身份 + 动作背景 + 服装遮罩";
});

updateNode(131, (node) => {
  node.title = "正向提示词｜保持通用，不写死商品类型";
  node.widgets_values = [
    "commercial fashion video, the person wears the exact garment from the clothing reference image, preserve the garment color, pattern, logo, material and silhouette, preserve the source video identity, body motion, camera movement, background and lighting, natural fabric motion, temporally consistent",
  ];
});
updateNode(133, (node) => {
  node.title = "负向提示词｜明确拒绝原视频服装回流";
  node.widgets_values = [
    "original source-video outfit, unchanged clothes, wrong garment, wrong color, altered logo, duplicated pattern, clothing leakage, exposed erased region, flicker, unstable fabric, warped hands",
  ];
});

updateNode(86, (node) => {
  node.title = "⑪ Wan 采样｜4 步固定种子便于对比";
  node.widgets_values[4] = "fixed";
});

for (const [id, prefix, saveOutput] of [
  [53, "rh-video-tryon-v2-mask", false],
  [69, "rh-video-tryon-v2-erased", false],
  [67, "rh-video-tryon-v2-final", true],
]) {
  updateNode(id, (node) => {
    node.widgets_values = {
      ...node.widgets_values,
      filename_prefix: prefix,
      save_output: saveOutput,
      videopreview: { paused: false, hidden: false, params: {} },
    };
  });
}
updateNode(53, (node) => {
  node.title = "遮罩预览｜红色必须覆盖原视频服装";
});
updateNode(69, (node) => {
  node.title = "擦除预览｜原服装区域必须变黑";
});
updateNode(67, (node) => {
  node.title = "⑫ 最终视频｜必须看到商品服装发生替换";
  node.color = "#1f4d3d";
  node.bgcolor = "#2b5d4b";
});

// Make the transform idempotent: generated workflows can be used as an offline
// input by tests without accumulating duplicate notes.
workflow.nodes = workflow.nodes.filter(
  (node) => node.properties?.comfyui_learning_hub_note !== true,
);

const notes = [
  {
    id: 10001,
    pos: [1770, 1745],
    size: [800, 330],
    color: "#234",
    bgcolor: "#345",
    text:
      "先读这里｜这不是旧版 H3 参考复刻\n\n" +
      "1. ① 只上传商品服装图。\n" +
      "2. ② 只上传有动作的真人参考视频。\n" +
      "3. 默认只跑 432×768、10 FPS、49 帧，约 4.9 秒。\n" +
      "4. 先检查红色动态遮罩是否完整覆盖原视频衣服，再运行。\n" +
      "5. 最终人物仍穿原视频衣服，就判失败，不能因为视频能播放而通过。",
  },
  {
    id: 10002,
    pos: [1770, 2110],
    size: [800, 390],
    color: "#432",
    bgcolor: "#653",
    text:
      "服装遮罩怎么选\n\n" +
      "⑥ 默认勾选 Upper-clothes、Skirt、Dress、Belt、Pants 和双臂，用于先彻底清除原视频整套衣服，并让长袖商品能覆盖裸露手臂。\n\n" +
      "跑通后可按原视频中的衣服类别缩小范围：\n" +
      "- 上衣：只留 Upper-clothes\n" +
      "- 连衣裙：只留 Dress\n" +
      "- 下装：只留 Skirt 或 Pants\n\n" +
      "服装类别依据原视频人物穿什么；双臂依据目标商品是不是长袖。不要勾 Face、Hair 或 Background。",
  },
  {
    id: 10003,
    pos: [1770, 2540],
    size: [800, 360],
    color: "#432",
    bgcolor: "#653",
    text:
      `来源与边界\n\n基于 RunningHub 可公开下载的“视频换装”工作流 ${sourceWorkflowId} 做教学化改造：\n${sourcePage}\n\n` +
      "保留原作者核心节点和连线；本项目只清理账号媒体、限制首跑成本、缩小服装遮罩范围、固定种子并补充中文验收说明。RunningHub 模型库存或节点版本变化时，仍需平台首跑确认。",
  },
].map((note, index) => ({
  id: note.id,
  type: "Note",
  pos: note.pos,
  size: note.size,
  flags: {},
  order: 40 + index,
  mode: 0,
  inputs: [],
  outputs: [],
  properties: {
    widget_ue_connectable: {},
    comfyui_learning_hub_note: true,
  },
  widgets_values: [note.text],
  color: note.color,
  bgcolor: note.bgcolor,
}));
workflow.nodes.push(...notes);

workflow.id = "7f0b3214-5060-4f6f-8d9b-fb2c1d87a201";
workflow.revision = 0;
workflow.last_node_id = Math.max(...workflow.nodes.map((node) => node.id));
workflow.last_link_id = Math.max(...workflow.links.map((link) => link[0]));
workflow.extra ??= {};
workflow.extra.ds = { offset: [-1530, -1320], scale: 0.7 };
const existingAudit = workflow.extra.audit;
workflow.extra.audit = {
  derived_at: "2026-09-02",
  derived_by: "scripts/derive_rh_video_tryon_v2.mjs",
  target_platform: "RunningHub",
  source_workflow_id: sourceWorkflowId,
  source_page: sourcePage,
  source_export_api: sourceExportApi,
  source_sha256:
    existingAudit?.profile === "rh-video-tryon-v2"
      ? existingAudit.source_sha256
      : loadedSha256,
  expected_source_sha256: expectedSourceSha256,
  source_description: "RunningHub public export snapshot fetched on 2026-09-02",
  profile: "rh-video-tryon-v2",
  acceptance_rule:
    "The uploaded garment must replace the source-video outfit; playable output alone is not a pass.",
  modifications: [
    "Cleared account-specific uploaded media and generated preview URLs.",
    "Limited the first run to 432x768, 10 FPS, and 49 frames.",
    "Changed the human-parsing preset to mask clothing categories and arms for the long-sleeve acceptance case without masking face, hair, legs, accessories, or background.",
    "Kept garment identity on the LoadImage to WanVideoClipVisionEncode branch and source video on the mask/background branch.",
    "Fixed the seed policy and added beginner instructions plus explicit functional acceptance criteria.",
  ],
};

// Verify every serialized connection against the authoritative link table.
nodesById = new Map(workflow.nodes.map((node) => [node.id, node]));
for (const [linkId, sourceId, sourceSlot, targetId, targetSlot] of workflow.links) {
  const source = nodesById.get(sourceId);
  const target = nodesById.get(targetId);
  if (!source || !target) {
    throw new Error(`Dangling link ${linkId}: ${sourceId} -> ${targetId}`);
  }
  if (!source.outputs?.[sourceSlot] || !target.inputs?.[targetSlot]) {
    throw new Error(
      `Invalid slot on link ${linkId}: ${sourceId}:${sourceSlot} -> ${targetId}:${targetSlot}`,
    );
  }
}

fs.mkdirSync(path.dirname(targetPath), { recursive: true });
fs.writeFileSync(targetPath, `${JSON.stringify(workflow, null, 2)}\n`);
console.log(
  `Wrote ${path.relative(repoRoot, targetPath)} (${workflow.nodes.length} nodes, ${workflow.links.length} links)`,
);
