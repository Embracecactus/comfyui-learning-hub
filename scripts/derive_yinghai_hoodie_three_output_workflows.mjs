#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [cutoutBasePath, fluxBasePath, outputDirectory] = process.argv.slice(2);
if (!cutoutBasePath || !fluxBasePath || !outputDirectory) {
  console.error(
    "Usage: node scripts/derive_yinghai_hoodie_three_output_workflows.mjs <cutout-base.json> <flux-base.json> <output-directory>",
  );
  process.exit(2);
}

const cutoutBase = JSON.parse(fs.readFileSync(cutoutBasePath, "utf8"));
const fluxBase = JSON.parse(fs.readFileSync(fluxBasePath, "utf8"));
const preparedAt = "2026-08-28";

function cloneNode(workflow, id, expectedType) {
  const node = workflow.nodes.find((candidate) => candidate.id === id);
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
      cnr_id: "comfy-core",
    },
    widgets_values: widgets,
  };
}

function loadImageNode({ id, pos, order, title, file, links = null, size = [330, 390] }) {
  return coreNode({
    id,
    type: "LoadImage",
    pos,
    size,
    order,
    title,
    outputs: [
      { name: "IMAGE", type: "IMAGE", links },
      { name: "MASK", type: "MASK", links: null },
    ],
    widgets: [file, "image"],
  });
}

function makeFlatPixelFaithfulWorkflow() {
  const note = cloneNode(fluxBase, 97, "MarkdownNote");
  note.id = 1;
  note.pos = [-1450, -520];
  note.size = [720, 430];
  note.order = 0;
  note.title = "平铺分支说明｜原商品像素不经过扩散模型";
  note.widgets_values = [
    [
      "## 公开卫衣案例｜白底平铺像素保真分支",
      "",
      "1. BiRefNet 只负责识别商品轮廓。",
      "2. ImageScale 同步缩放原 RGB 商品与遮罩。",
      "3. ImageCompositeMasked 把原商品像素贴到 576×1024 纯白画布。",
      "4. FLUX 不参与本分支，因此 1977、帽型、口袋与面料不会被重绘。",
      "5. 右侧参考图和网站结果均为断开预览，不参与计算。",
      "",
      "模型：models/background_removal/birefnet.safetensors",
      "输出：ComfyUI-Shared/output/ecommerce/replica/hoodie-flat-pixel-faithful",
      "文档：docs/04-电商AI工作流/05-映海卫衣三结果复刻实战.md",
    ].join("\n"),
  ];

  const product = loadImageNode({
    id: 2,
    pos: [-1450, 20],
    order: 1,
    title: "商品原图｜网站公开 1977 卫衣",
    file: "yinghai-hoodie-comparison/01-product-1977-hoodie.png",
    links: [1, 5],
  });

  const model = cloneNode(cutoutBase, 2, "LoadBackgroundRemovalModel");
  model.id = 3;
  model.pos = [-1450, 480];
  model.order = 2;
  model.outputs[0].links = [2];

  const remove = cloneNode(cutoutBase, 3, "RemoveBackground");
  remove.id = 4;
  remove.pos = [-1040, 130];
  remove.order = 3;
  remove.inputs[0].link = 1;
  remove.inputs[1].link = 2;
  remove.outputs[0].links = [3];

  const grow = cloneNode(cutoutBase, 4, "GrowMask");
  grow.id = 5;
  grow.pos = [-690, 130];
  grow.order = 4;
  grow.inputs[0].link = 3;
  grow.outputs[0].links = [4, 6];
  grow.title = "边缘微调｜先保持 0";

  const previewMask = cloneNode(cutoutBase, 5, "MaskPreview");
  previewMask.id = 6;
  previewMask.pos = [-360, -20];
  previewMask.order = 5;
  previewMask.inputs[0].link = 4;

  const scaleProduct = coreNode({
    id: 7,
    type: "ImageScale",
    pos: [-360, 410],
    size: [310, 180],
    order: 6,
    title: "原商品等比缩放｜宽 560，高度自动",
    inputs: [{ name: "image", type: "IMAGE", link: 5 }],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [10] }],
    widgets: ["lanczos", 560, 0, "disabled"],
  });

  const maskToImage = coreNode({
    id: 8,
    type: "MaskToImage",
    pos: [-360, 650],
    size: [260, 90],
    order: 7,
    title: "遮罩转图片｜准备同步缩放",
    inputs: [{ name: "mask", type: "MASK", link: 6 }],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [7] }],
  });

  const scaleMask = coreNode({
    id: 9,
    type: "ImageScale",
    pos: [-40, 650],
    size: [310, 180],
    order: 8,
    title: "遮罩等比缩放｜必须与商品同宽 560",
    inputs: [{ name: "image", type: "IMAGE", link: 7 }],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [8] }],
    widgets: ["bilinear", 560, 0, "disabled"],
  });

  const imageToMask = coreNode({
    id: 10,
    type: "ImageToMask",
    pos: [330, 650],
    size: [260, 110],
    order: 9,
    title: "缩放结果转回前景遮罩",
    inputs: [{ name: "image", type: "IMAGE", link: 8 }],
    outputs: [{ name: "MASK", type: "MASK", links: [11] }],
    widgets: ["red"],
  });

  const canvas = coreNode({
    id: 11,
    type: "EmptyImage",
    pos: [30, 320],
    size: [290, 210],
    order: 10,
    title: "创建 9:16 纯白画布｜576×1024",
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [9] }],
    widgets: [576, 1024, 1, 16777215],
  });

  const composite = coreNode({
    id: 12,
    type: "ImageCompositeMasked",
    pos: [700, 360],
    size: [330, 230],
    order: 11,
    title: "原像素合成｜x=8，y=114",
    inputs: [
      { name: "destination", type: "IMAGE", link: 9 },
      { name: "source", type: "IMAGE", link: 10 },
      { name: "mask", shape: 7, type: "MASK", link: 11 },
    ],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [12, 13] }],
    widgets: [8, 114, false],
  });

  const preview = coreNode({
    id: 13,
    type: "PreviewImage",
    pos: [1080, 210],
    size: [360, 480],
    order: 12,
    title: "本地像素保真结果",
    inputs: [{ name: "images", type: "IMAGE", link: 12 }],
  });

  const save = coreNode({
    id: 14,
    type: "SaveImage",
    pos: [1080, 750],
    size: [360, 110],
    order: 13,
    title: "保存平铺商品主图",
    inputs: [{ name: "images", type: "IMAGE", link: 13 }],
    widgets: ["ecommerce/replica/hoodie-flat-pixel-faithful"],
  });

  const reference = loadImageNode({
    id: 15,
    pos: [1510, -80],
    order: 14,
    title: "网站对标图3｜只看版式，不参与合成",
    file: "yinghai-hoodie-comparison/02-reference-white-chicerro-layout.png",
    size: [350, 500],
  });

  const baseline = loadImageNode({
    id: 16,
    pos: [1510, 500],
    order: 15,
    title: "网站结果1基线｜只比较，不参与合成",
    file: "yinghai-hoodie-comparison/03-site-result-baseline.png",
    size: [350, 600],
  });

  return {
    last_node_id: 16,
    last_link_id: 13,
    nodes: [
      note,
      product,
      model,
      remove,
      grow,
      previewMask,
      scaleProduct,
      maskToImage,
      scaleMask,
      imageToMask,
      canvas,
      composite,
      preview,
      save,
      reference,
      baseline,
    ],
    links: [
      [1, 2, 0, 4, 0, "IMAGE"],
      [2, 3, 0, 4, 1, "BACKGROUND_REMOVAL"],
      [3, 4, 0, 5, 0, "MASK"],
      [4, 5, 0, 6, 0, "MASK"],
      [5, 2, 0, 7, 0, "IMAGE"],
      [6, 5, 0, 8, 0, "MASK"],
      [7, 8, 0, 9, 0, "IMAGE"],
      [8, 9, 0, 10, 0, "IMAGE"],
      [9, 11, 0, 12, 0, "IMAGE"],
      [10, 7, 0, 12, 1, "IMAGE"],
      [11, 10, 0, 12, 2, "MASK"],
      [12, 12, 0, 13, 0, "IMAGE"],
      [13, 12, 0, 14, 0, "IMAGE"],
    ],
    groups: [
      {
        id: 1,
        title: "Step 1｜BiRefNet 提取真实商品轮廓",
        bounding: [-1510, -580, 1240, 1400],
        color: "#3f789e",
        font_size: 24,
        flags: {},
      },
      {
        id: 2,
        title: "Step 2｜同步缩放 RGB 与遮罩，再做 9:16 原像素合成",
        bounding: [-420, 250, 1920, 680],
        color: "#4f7d45",
        font_size: 24,
        flags: {},
      },
      {
        id: 3,
        title: "网站公开参考｜断开，仅人工验收",
        bounding: [1460, -140, 460, 1320],
        color: "#8b5e3c",
        font_size: 24,
        flags: {},
      },
    ],
    config: {},
    extra: {
      audit: {
        prepared_at: preparedAt,
        derived_by: "scripts/derive_yinghai_hoodie_three_output_workflows.mjs",
        derived_from: cutoutBasePath,
        branch: "flat_pixel_faithful",
        public_case_id: "22e90419-ec27-4bbe-9fc7-835bcfb73b16",
        limitation: "This branch reproduces only the flat-lay output category and deliberately preserves source product pixels.",
      },
    },
    version: 0.4,
  };
}

const modelBranches = {
  full: {
    referenceFile: "yinghai-hoodie-comparison/02a-reference-male-beige.png",
    baselineFile: "yinghai-hoodie-comparison/04-site-result-male-full-baseline.png",
    referenceTitle: "图2｜网站男模参考1：人物、姿态与全身构图",
    editTitle: "FLUX.2 Klein｜男模全身穿着分支",
    baselineTitle: "网站结果2基线｜只比较，不参与生成",
    seed: 2026082804,
    outputPrefix: "ecommerce/replica/hoodie-model-full-flux2-klein",
    prompt: [
      "Create a vertical 9:16 premium ecommerce fashion photograph.",
      "Image 1 is the exact garment identity: one black speckled pullover hoodie with raglan sleeves, ribbed cuffs and hem, a front kangaroo pocket, and the exact readable white digits 1977.",
      "Image 2 is the exact male model identity, hair, face, body proportions, standing pose, camera angle and clean studio composition reference.",
      "Replace only the beige short-sleeve shirt in Image 2 with the black 1977 hoodie from Image 1 and dress it naturally on the same model.",
      "The hood stays down and folded around the back of the neck, never covering the head and never becoming pointed.",
      "Preserve the garment black color, dense white speckles, exact 1977 digits, raglan seams, kangaroo pocket, cuffs and hem.",
      "Keep realistic sleeve folds, fabric thickness and body occlusion while both hands rest naturally in the kangaroo pocket.",
      "Use loose light-gray sweatpants and a neutral warm-white seamless studio background.",
      "Remove the bouquet, hat, bag, jewelry and all props from Image 2.",
      "Do not copy the beige shirt, its collar or buttons. No brand, logo, watermark, headline, Chinese text or other typography.",
      "Generate exactly one adult male model and one hoodie, with anatomically correct hands and no duplicate limbs.",
    ].join(" "),
  },
  close: {
    referenceFile: "yinghai-hoodie-comparison/02b-reference-male-blue.png",
    baselineFile: "yinghai-hoodie-comparison/05-site-result-male-close-baseline.png",
    referenceTitle: "图2｜网站男模参考2：人物、姿态与近景构图",
    editTitle: "FLUX.2 Klein｜男模近景穿着分支",
    baselineTitle: "网站结果3基线｜只比较，不参与生成",
    seed: 2026082805,
    outputPrefix: "ecommerce/replica/hoodie-model-close-flux2-klein",
    prompt: [
      "Create a vertical 9:16 premium ecommerce fashion photograph with a front-facing medium-full portrait composition.",
      "Image 1 is the exact garment identity: one black speckled pullover hoodie with raglan sleeves, ribbed cuffs and hem, a front kangaroo pocket, and the exact readable white digits 1977.",
      "Image 2 is the exact male model identity, hair, face, body proportions, frontal pose, camera angle and clean studio composition reference.",
      "Replace only the light-blue short-sleeve shirt in Image 2 with the black 1977 hoodie from Image 1 and dress it naturally on the same model.",
      "The hood stays down and softly folded behind the neck, never covering the head and never becoming pointed.",
      "Preserve the garment black color, dense white speckles, exact 1977 digits, raglan seams, kangaroo pocket, cuffs and hem.",
      "Use realistic thick fleece fabric and let both hands rest naturally in the kangaroo pocket.",
      "Use loose light-gray sweatpants and a neutral warm-white seamless studio background.",
      "Remove the straw hat, straps, jewelry and every accessory from Image 2.",
      "Do not copy the blue shirt, its collar or buttons. No brand, logo, watermark, headline, Chinese text or other typography.",
      "Generate exactly one adult male model and one hoodie, with anatomically correct hands and no duplicate limbs.",
    ].join(" "),
  },
};

function makeModelWorkflow(branchName) {
  const branch = modelBranches[branchName];
  const workflow = structuredClone(fluxBase);
  const nodes = new Map(workflow.nodes.map((node) => [node.id, node]));
  const note = nodes.get(97);
  const product = nodes.get(76);
  const reference = nodes.get(81);
  const edit = nodes.get(92);
  const save = nodes.get(94);

  for (const [name, node] of [
    ["note", note],
    ["product", product],
    ["reference", reference],
    ["edit", edit],
    ["save", save],
  ]) {
    if (!node) throw new Error(`Flux base changed: missing ${name} node`);
  }

  product.title = "图1｜1977 卫衣商品身份（9:16 画布）";
  product.widgets_values = [
    "yinghai-hoodie-comparison/01b-product-1977-hoodie-9x16-canvas.png",
    "image",
  ];
  reference.title = branch.referenceTitle;
  reference.widgets_values = [branch.referenceFile, "image"];
  edit.title = branch.editTitle;
  edit.widgets_values[3] = branch.prompt;
  edit.widgets_values[4] = branch.seed;
  save.title = "保存本地模特穿着结果";
  save.widgets_values = [branch.outputPrefix];

  note.title = `公开卫衣案例｜${branchName === "full" ? "男模全身" : "男模近景"}最小复刻说明`;
  note.widgets_values = [
    [
      `## ${branch.editTitle}`,
      "",
      "- 图1只提供黑色 1977 卫衣身份。",
      "- 图2提供网站公开男模参考的人物、姿态和构图。",
      "- FLUX.2 Klein 负责生成新的穿着关系，因此不是原像素保真分支。",
      "- 网站基线节点断开，只用于检查，不参与生成。",
      "- 第一轮禁用模型文字；中文卖点和自有品牌应在后期排版。",
      `- 固定 seed：${branch.seed}；4 步；CFG 1；约 0.6 MP。`,
      "",
      "文档：docs/04-电商AI工作流/05-映海卫衣三结果复刻实战.md",
    ].join("\n"),
  ];

  const baseline = structuredClone(product);
  baseline.id = 200;
  baseline.order = 0;
  baseline.pos = [900, 1040];
  baseline.size = [360, 620];
  baseline.title = branch.baselineTitle;
  baseline.widgets_values = [branch.baselineFile, "image"];
  for (const output of baseline.outputs || []) output.links = null;
  workflow.nodes.push(baseline);
  workflow.last_node_id = Math.max(workflow.last_node_id || 0, 200);
  workflow.groups = [
    {
      id: 1,
      title: `公开卫衣案例｜${branchName === "full" ? "男模全身" : "男模近景"}本地生成与网站基线`,
      bounding: [-680, 350, 2000, 1380],
      color: "#3f789e",
      flags: {},
    },
  ];
  workflow.extra = {
    ...(workflow.extra || {}),
    replica_branch: {
      prepared_at: preparedAt,
      derived_by: "scripts/derive_yinghai_hoodie_three_output_workflows.mjs",
      derived_from: fluxBasePath,
      branch: `model_${branchName}`,
      public_case_id: "22e90419-ec27-4bbe-9fc7-835bcfb73b16",
      product_file: product.widgets_values[0],
      reference_file: branch.referenceFile,
      baseline_file: branch.baselineFile,
      output_prefix: branch.outputPrefix,
      limitation: "This is a local two-reference FLUX.2 Klein approximation of one public result, not the website's undisclosed multi-reference server workflow.",
    },
  };
  return workflow;
}

const outputs = [
  ["ecommerce-yinghai-hoodie-flat-pixel-faithful-birefnet.json", makeFlatPixelFaithfulWorkflow()],
  ["ecommerce-yinghai-hoodie-model-full-flux2-klein.json", makeModelWorkflow("full")],
  ["ecommerce-yinghai-hoodie-model-close-flux2-klein.json", makeModelWorkflow("close")],
];

fs.mkdirSync(outputDirectory, { recursive: true });
for (const [filename, workflow] of outputs) {
  fs.writeFileSync(
    path.join(outputDirectory, filename),
    `${JSON.stringify(workflow, null, 2)}\n`,
  );
}
