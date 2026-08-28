#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [genericBasePath, outputPath] = process.argv.slice(2);
if (!genericBasePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_generic_product_layout_2k_workflow.mjs <generic-base.json> <output.json>",
  );
  process.exit(2);
}

const base = JSON.parse(fs.readFileSync(genericBasePath, "utf8"));

function cloneNode(id, expectedType) {
  const node = base.nodes.find((candidate) => candidate.id === id);
  if (!node || node.type !== expectedType) {
    throw new Error(
      `Base workflow changed: expected node ${id} to be ${expectedType}, got ${node?.type ?? "missing"}`,
    );
  }
  return structuredClone(node);
}

function coreNode({ id, type, pos, size, order, title, inputs = [], outputs = [], widgets = [] }) {
  return {
    id,
    type,
    pos,
    size,
    flags: {},
    order,
    mode: 0,
    inputs,
    outputs,
    title,
    properties: { "Node name for S&R": type },
    widgets_values: widgets,
  };
}

const note = cloneNode(1, "MarkdownNote");
note.widgets_values = [
  [
    "## 通用商品 2K 成图 + 确定性品牌排版",
    "",
    "1. 上半段沿用已验收的自动裁边与百分比排版。",
    "2. RealESRGAN_x4plus 先做 4× 商品细节放大，再缩到精确 1440×2560。",
    "3. clean 分支保存无字母版，可交给设计软件或继续复用。",
    "4. branded 分支在最终尺寸上绘制文字，不交给扩散模型生成乱码。",
    "5. 运行前必须把‘填写真实卖点’和‘YOUR BRAND’替换为自己的真实内容。",
    "",
    "放大模型：models/upscale_models/RealESRGAN_x4plus.pth",
    "中文字体：font_name=auto，优先 Noto Sans SC / 微软雅黑 / 黑体。",
    "文档：docs/04-电商AI工作流/07-通用商品2K与确定性排版.md",
  ].join("\n"),
];

const product = cloneNode(2, "LoadImage");
const model = cloneNode(3, "LoadBackgroundRemovalModel");
const remove = cloneNode(4, "RemoveBackground");
const grow = cloneNode(5, "GrowMask");
const sourceMaskPreview = cloneNode(6, "MaskPreview");
const layout = cloneNode(7, "ProductLayoutByMask");
const outputMaskPreview = cloneNode(8, "MaskPreview");

layout.outputs[0].links = [7];
layout.outputs[1].links = [9];
outputMaskPreview.inputs[0].link = 9;

const upscaleModel = coreNode({
  id: 9,
  type: "UpscaleModelLoader",
  pos: [220, 1030],
  size: [380, 100],
  order: 8,
  title: "加载通用商品 4× 放大模型",
  outputs: [{ name: "UPSCALE_MODEL", type: "UPSCALE_MODEL", links: [8] }],
  widgets: ["RealESRGAN_x4plus.pth"],
});

const modelUpscale = coreNode({
  id: 10,
  type: "ImageUpscaleWithModel",
  pos: [680, 420],
  size: [390, 150],
  order: 9,
  title: "AI 细节放大｜576×1024 → 2304×4096",
  inputs: [
    { name: "upscale_model", type: "UPSCALE_MODEL", link: 8 },
    { name: "image", type: "IMAGE", link: 7 },
  ],
  outputs: [{ name: "IMAGE", type: "IMAGE", links: [10] }],
});

const exact2k = coreNode({
  id: 11,
  type: "ImageScale",
  pos: [1140, 420],
  size: [350, 190],
  order: 10,
  title: "精确输出尺寸｜1440×2560",
  inputs: [{ name: "image", type: "IMAGE", link: 10 }],
  outputs: [{ name: "IMAGE", type: "IMAGE", links: [11, 12, 13] }],
  widgets: ["lanczos", 1440, 2560, "disabled"],
});

const cleanPreview = coreNode({
  id: 12,
  type: "PreviewImage",
  pos: [1570, 0],
  size: [430, 650],
  order: 11,
  title: "2K 无字母版｜优先检查商品细节",
  inputs: [{ name: "images", type: "IMAGE", link: 11 }],
});

const cleanSave = coreNode({
  id: 13,
  type: "SaveImage",
  pos: [1570, 700],
  size: [430, 120],
  order: 12,
  title: "保存 2K 无字母版",
  inputs: [{ name: "images", type: "IMAGE", link: 12 }],
  widgets: ["ecommerce/generic/product-layout-2k-clean"],
});

const sellingPoints = coreNode({
  id: 14,
  type: "ProductTextOverlay",
  pos: [1570, 900],
  size: [480, 600],
  order: 13,
  title: "卖点文字｜请替换占位内容",
  inputs: [{ name: "images", type: "IMAGE", link: 13 }],
  outputs: [{ name: "images", type: "IMAGE", links: [14] }],
  widgets: [
    "填写真实卖点\\n第二行卖点",
    "auto",
    2.4,
    7.5,
    6.5,
    "top_left",
    "left",
    "#111111",
    85.0,
    25.0,
    0.0,
    "#FFFFFF",
    "yes",
  ],
});

const brand = coreNode({
  id: 15,
  type: "ProductTextOverlay",
  pos: [2120, 900],
  size: [480, 600],
  order: 14,
  title: "自有品牌｜禁止照抄竞品品牌",
  inputs: [{ name: "images", type: "IMAGE", link: 14 }],
  outputs: [{ name: "images", type: "IMAGE", links: [15, 16] }],
  widgets: [
    "YOUR BRAND",
    "auto",
    3.2,
    50.0,
    91.0,
    "bottom_center",
    "center",
    "#111111",
    85.0,
    20.0,
    0.0,
    "#FFFFFF",
    "yes",
  ],
});

const brandedPreview = coreNode({
  id: 16,
  type: "PreviewImage",
  pos: [2680, 680],
  size: [430, 650],
  order: 15,
  title: "2K 自有品牌版",
  inputs: [{ name: "images", type: "IMAGE", link: 15 }],
});

const brandedSave = coreNode({
  id: 17,
  type: "SaveImage",
  pos: [2680, 1380],
  size: [430, 120],
  order: 16,
  title: "保存 2K 自有品牌版",
  inputs: [{ name: "images", type: "IMAGE", link: 16 }],
  widgets: ["ecommerce/generic/product-layout-2k-branded"],
});

const workflow = {
  last_node_id: 17,
  last_link_id: 16,
  nodes: [
    note,
    product,
    model,
    remove,
    grow,
    sourceMaskPreview,
    layout,
    outputMaskPreview,
    upscaleModel,
    modelUpscale,
    exact2k,
    cleanPreview,
    cleanSave,
    sellingPoints,
    brand,
    brandedPreview,
    brandedSave,
  ],
  links: [
    [1, 2, 0, 4, 0, "IMAGE"],
    [2, 3, 0, 4, 1, "BACKGROUND_REMOVAL"],
    [3, 4, 0, 5, 0, "MASK"],
    [4, 5, 0, 6, 0, "MASK"],
    [5, 2, 0, 7, 0, "IMAGE"],
    [6, 5, 0, 7, 1, "MASK"],
    [7, 7, 0, 10, 1, "IMAGE"],
    [8, 9, 0, 10, 0, "UPSCALE_MODEL"],
    [9, 7, 1, 8, 0, "MASK"],
    [10, 10, 0, 11, 0, "IMAGE"],
    [11, 11, 0, 12, 0, "IMAGE"],
    [12, 11, 0, 13, 0, "IMAGE"],
    [13, 11, 0, 14, 0, "IMAGE"],
    [14, 14, 0, 15, 0, "IMAGE"],
    [15, 15, 0, 16, 0, "IMAGE"],
    [16, 15, 0, 17, 0, "IMAGE"],
  ],
  groups: [
    ...structuredClone(base.groups),
    {
      id: 3,
      title: "Step 3｜4× 模型放大后收敛到精确 2K",
      bounding: [160, 330, 1400, 850],
      color: "#8b6d3f",
      font_size: 24,
      flags: {},
    },
    {
      id: 4,
      title: "Step 4A｜保存可复用的 2K 无字母版",
      bounding: [1510, -70, 550, 950],
      color: "#477b68",
      font_size: 24,
      flags: {},
    },
    {
      id: 5,
      title: "Step 4B｜最终尺寸上添加真实卖点与自有品牌",
      bounding: [1510, 840, 1660, 720],
      color: "#76558f",
      font_size: 24,
      flags: {},
    },
  ],
  config: {},
  extra: {
    audit: {
      prepared_at: "2026-08-28",
      derived_by: "scripts/derive_generic_product_layout_2k_workflow.mjs",
      derived_from: genericBasePath,
      custom_nodes: ["ProductLayoutByMask", "ProductTextOverlay"],
      upscale_model: {
        name: "RealESRGAN_x4plus.pth",
        sha256: "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1",
        scale: 4,
      },
      output_size: [1440, 2560],
      scope: "Generic deterministic single-product layout, local super-resolution, and editable own-brand typography.",
    },
  },
  version: 0.4,
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
