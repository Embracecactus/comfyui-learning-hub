#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [sourcePath, outputPath] = process.argv.slice(2);

if (!sourcePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_flux2_klein_reference_workflow.mjs <official-template.json> <output.json>",
  );
  process.exit(2);
}

const workflow = JSON.parse(fs.readFileSync(sourcePath, "utf8"));
const nodesById = new Map(workflow.nodes.map((node) => [node.id, node]));

const productNode = nodesById.get(76);
const referenceNode = nodesById.get(81);
const multiReferenceEditNode = nodesById.get(92);
const multiReferenceSaveNode = nodesById.get(94);
const noteNode = nodesById.get(97);

for (const [name, node] of [
  ["product LoadImage", productNode],
  ["reference LoadImage", referenceNode],
  ["multi-reference edit subgraph", multiReferenceEditNode],
  ["multi-reference SaveImage", multiReferenceSaveNode],
  ["model note", noteNode],
]) {
  if (!node) throw new Error(`Official template changed: missing ${name}`);
}

const prompt = [
  "Create a new premium ecommerce hero image.",
  "Image 1 is the exact product source and is the only product identity reference.",
  "Preserve Image 1 product geometry, proportions, material, colors, packaging structure, logo and readable label details.",
  "Image 2 is only the visual and composition reference.",
  "Borrow Image 2 background design, camera angle, product scale, visual hierarchy, palette, lighting direction and commercial mood,",
  "but do not copy its product, brand, logo, watermark, people or text.",
  "Place exactly one Image 1 product naturally in the recreated scene with physically plausible contact shadow, reflection and occlusion.",
  "Keep the center product unobstructed. No duplicate product, no invented accessories, no protruding wings or geometric props touching the product.",
  "Square 1:1 ecommerce main image, clean high-end commercial photography, no extra text.",
].join(" ");

productNode.title = "图 1｜上传自家商品图（主体身份）";
productNode.widgets_values = ["product-source.png", "image"];
productNode.pos = [-140, 430];
productNode.outputs[0].links = [169];

referenceNode.title = "图 2｜上传对标主图（只参考构图与风格）";
referenceNode.widgets_values = ["reference-main-image.png", "image"];
referenceNode.pos = [-140, 930];
referenceNode.outputs[0].links = [172];

multiReferenceEditNode.mode = 0;
multiReferenceEditNode.title = "双参考编辑｜商品身份 + 对标视觉";
multiReferenceEditNode.pos = [330, 500];
multiReferenceEditNode.widgets_values = [
  "flux-2-klein-4b-fp8.safetensors",
  "qwen_3_4b.safetensors",
  "flux2-vae.safetensors",
  prompt,
  2026082801,
];

const multiReferenceSubgraph = workflow.definitions?.subgraphs?.find(
  (subgraph) => subgraph.id === multiReferenceEditNode.type,
);
if (!multiReferenceSubgraph) {
  throw new Error("Official template changed: missing multi-reference subgraph definition");
}

for (const node of multiReferenceSubgraph.nodes) {
  if (node.type === "EmptyFlux2LatentImage") {
    node.widgets_values = [768, 768, 1];
  } else if (node.type === "Flux2Scheduler") {
    node.widgets_values = [4, 768, 768];
  } else if (node.type === "ImageScaleToTotalPixels") {
    node.widgets_values = [node.widgets_values?.[0] || "nearest-exact", 0.6, 1];
  }
}

multiReferenceSaveNode.mode = 0;
multiReferenceSaveNode.title = "保存参考图驱动商品主图";
multiReferenceSaveNode.pos = [890, 500];
multiReferenceSaveNode.widgets_values = ["ecommerce/reference-main-image-flux2-klein"];

noteNode.title = "模型、来源与运行前检查";
noteNode.pos = [-650, 430];
noteNode.widgets_values = [
  [
    "## 本地商品主图复刻｜FLUX.2 Klein 4B Distilled",
    "",
    "图 1 是自家商品身份，图 2 是对标构图与风格。模型会重绘整张图，不保证包装文字 100% 不漂移；商用前必须人工核对。",
    "",
    "### 官方来源",
    "",
    "- 教程：https://docs.comfy.org/tutorials/flux/flux-2-klein",
    "- 模板：Comfy-Org/workflow_templates / image_flux2_klein_image_edit_4b_distilled.json",
    "",
    "### 模型目录",
    "",
    "- diffusion_models/flux-2-klein-4b-fp8.safetensors",
    "- text_encoders/qwen_3_4b.safetensors",
    "- vae/flux2-vae.safetensors",
    "",
    "### 8 GB 显存",
    "",
    "官方参考峰值为 8.4 GB，RTX 5060 8 GB 需要模型卸载/低显存路径；先关闭其他占显存程序，只运行单张 1024×1024。",
    "",
    "详细说明见：docs/04-电商AI工作流/04-参考图驱动商品主图工作流.md",
  ].join("\n"),
];

workflow.nodes = [noteNode, productNode, referenceNode, multiReferenceEditNode, multiReferenceSaveNode];
workflow.links = workflow.links.filter(([id]) => [169, 171, 172].includes(id));
workflow.groups = [
  {
    id: 1,
    title: "参考站同类最小链路｜商品图 + 对标主图 → 全图编辑",
    bounding: [-180, 360, 1500, 1050],
    color: "#3f789e",
    flags: {},
  },
];
workflow.last_group_id = 1;
workflow.extra = {
  ...(workflow.extra || {}),
  audit: {
    derived_at: "2026-08-28",
    derived_by: "scripts/derive_flux2_klein_reference_workflow.mjs",
    source: "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_flux2_klein_image_edit_4b_distilled.json",
    source_project: "Comfy-Org/workflow_templates",
    source_license: "MIT; see THIRD_PARTY_NOTICES.md",
    modifications: [
      "Kept the official two-image FLUX.2 Klein 4B distilled edit subgraph.",
      "Mapped image 1 to product identity and image 2 to competitor visual reference.",
      "Enabled only the multi-reference branch and changed the save prefix.",
      "Added a product-preservation prompt and local 8 GB guidance.",
      "Changed the multi-reference branch from the official 1024px/1MP defaults to a 768px/0.6MP safe starting point for 8 GB GPUs.",
    ],
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
