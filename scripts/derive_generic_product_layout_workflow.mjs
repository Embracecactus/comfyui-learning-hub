#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [cutoutBasePath, outputPath] = process.argv.slice(2);
if (!cutoutBasePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_generic_product_layout_workflow.mjs <cutout-base.json> <output.json>",
  );
  process.exit(2);
}

const base = JSON.parse(fs.readFileSync(cutoutBasePath, "utf8"));

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
    properties: {
      "Node name for S&R": type,
    },
    widgets_values: widgets,
  };
}

const note = coreNode({
  id: 1,
  type: "MarkdownNote",
  pos: [-1450, -520],
  size: [700, 470],
  order: 0,
  title: "通用模板说明｜参数是画布百分比，不绑定某个商品",
  widgets: [
    [
      "## 通用商品自动裁边与白底排版",
      "",
      "1. BiRefNet 产生前景遮罩。",
      "2. Product Layout by Mask 根据遮罩自动删除任意原图留白。",
      "3. 商品按目标画布百分比缩放、定位，不使用某张商品专属 x/y/width。",
      "4. 默认支持任意输入尺寸与横/竖/方形单商品图。",
      "5. 固定卫衣案例只作为回归测试，不是本模板的业务输入。",
      "",
      "自定义节点：custom_nodes/comfyui_product_layout",
      "模型：models/background_removal/birefnet.safetensors",
      "输出：ComfyUI-Shared/output/ecommerce/generic/product-layout-white",
      "文档：docs/04-电商AI工作流/06-通用商品自动排版工作流.md",
    ].join("\n"),
  ],
});

const product = cloneNode(1, "LoadImage");
product.id = 2;
product.pos = [-1450, 50];
product.size = [350, 450];
product.order = 1;
product.title = "上传任意单商品照片｜尺寸和留白不限";
product.widgets_values = ["product-photo.jpg", "image"];
product.outputs[0].links = [1, 5];
product.outputs[1].links = null;

const model = cloneNode(2, "LoadBackgroundRemovalModel");
model.id = 3;
model.pos = [-1450, 590];
model.order = 2;
model.outputs[0].links = [2];

const remove = cloneNode(3, "RemoveBackground");
remove.id = 4;
remove.pos = [-1020, 110];
remove.order = 3;
remove.inputs[0].link = 1;
remove.inputs[1].link = 2;
remove.outputs[0].links = [3];

const grow = cloneNode(4, "GrowMask");
grow.id = 5;
grow.pos = [-690, 110];
grow.order = 4;
grow.inputs[0].link = 3;
grow.outputs[0].links = [4, 6];
grow.title = "边缘微调｜默认 0";

const sourceMaskPreview = cloneNode(5, "MaskPreview");
sourceMaskPreview.id = 6;
sourceMaskPreview.pos = [-360, -40];
sourceMaskPreview.order = 5;
sourceMaskPreview.inputs[0].link = 4;
sourceMaskPreview.title = "检查原始前景遮罩";

const layout = coreNode({
  id: 7,
  type: "ProductLayoutByMask",
  pos: [-300, 410],
  size: [430, 520],
  order: 6,
  title: "通用排版｜自动裁边 + 百分比安全框",
  inputs: [
    { name: "image", type: "IMAGE", link: 5 },
    { name: "mask", type: "MASK", link: 6 },
  ],
  outputs: [
    { name: "image", type: "IMAGE", links: [7, 8] },
    { name: "mask", type: "MASK", links: [9] },
  ],
  widgets: [576, 1024, 88.0, 65.0, 50.0, 43.5, 0.1, 1.0, "#FFFFFF", "lanczos", "yes"],
});

const outputMaskPreview = cloneNode(5, "MaskPreview");
outputMaskPreview.id = 8;
outputMaskPreview.pos = [220, 510];
outputMaskPreview.order = 7;
outputMaskPreview.inputs[0].link = 9;
outputMaskPreview.title = "检查自动裁边、缩放与定位后的遮罩";

const preview = coreNode({
  id: 9,
  type: "PreviewImage",
  pos: [620, 190],
  size: [420, 620],
  order: 8,
  title: "通用白底商品结果",
  inputs: [{ name: "images", type: "IMAGE", link: 7 }],
});

const save = coreNode({
  id: 10,
  type: "SaveImage",
  pos: [620, 870],
  size: [420, 120],
  order: 9,
  title: "保存通用排版结果",
  inputs: [{ name: "images", type: "IMAGE", link: 8 }],
  widgets: ["ecommerce/generic/product-layout-white"],
});

const workflow = {
  last_node_id: 10,
  last_link_id: 9,
  nodes: [note, product, model, remove, grow, sourceMaskPreview, layout, outputMaskPreview, preview, save],
  links: [
    [1, 2, 0, 4, 0, "IMAGE"],
    [2, 3, 0, 4, 1, "BACKGROUND_REMOVAL"],
    [3, 4, 0, 5, 0, "MASK"],
    [4, 5, 0, 6, 0, "MASK"],
    [5, 2, 0, 7, 0, "IMAGE"],
    [6, 5, 0, 7, 1, "MASK"],
    [7, 7, 0, 9, 0, "IMAGE"],
    [8, 7, 0, 10, 0, "IMAGE"],
    [9, 7, 1, 8, 0, "MASK"],
  ],
  groups: [
    {
      id: 1,
      title: "Step 1｜任意商品 → BiRefNet 前景遮罩",
      bounding: [-1510, -580, 1220, 1420],
      color: "#3f789e",
      font_size: 24,
      flags: {},
    },
    {
      id: 2,
      title: "Step 2｜按遮罩自动裁边，再按画布百分比排版",
      bounding: [-360, 330, 1450, 730],
      color: "#4f7d45",
      font_size: 24,
      flags: {},
    },
  ],
  config: {},
  extra: {
    audit: {
      prepared_at: "2026-08-28",
      derived_by: "scripts/derive_generic_product_layout_workflow.mjs",
      derived_from: cutoutBasePath,
      custom_node: "custom_nodes/comfyui_product_layout",
      scope: "Generic single-product deterministic layout; no case-specific image, category, width, x, y, or prompt.",
    },
  },
  version: 0.4,
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
