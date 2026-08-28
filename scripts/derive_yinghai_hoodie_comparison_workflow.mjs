#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath || !outputPath) {
  console.error(
    "Usage: node scripts/derive_yinghai_hoodie_comparison_workflow.mjs <base-workflow.json> <output.json>",
  );
  process.exit(2);
}

const workflow = JSON.parse(fs.readFileSync(sourcePath, "utf8"));
const nodes = new Map(workflow.nodes.map((node) => [node.id, node]));
const noteNode = nodes.get(97);
const productNode = nodes.get(76);
const referenceNode = nodes.get(81);
const editNode = nodes.get(92);
const saveNode = nodes.get(94);

for (const [name, node] of [
  ["note", noteNode],
  ["product", productNode],
  ["reference", referenceNode],
  ["edit", editNode],
  ["save", saveNode],
]) {
  if (!node) throw new Error(`Base workflow changed: missing ${name} node`);
}

const productFile = "yinghai-hoodie-comparison/01b-product-1977-hoodie-9x16-canvas.png";
const referenceFile = "yinghai-hoodie-comparison/02-reference-white-chicerro-layout.png";
const baselineFile = "yinghai-hoodie-comparison/03-site-result-baseline.png";

productNode.title = "图 1｜1977 卫衣商品图（9:16 白底画布）";
productNode.widgets_values = [productFile, "image"];
referenceNode.title = "图 2｜网站案例中最直接的白底版式参考";
referenceNode.widgets_values = [referenceFile, "image"];

editNode.title = "FLUX.2 Klein｜映海卫衣公开案例同输入测试";
editNode.widgets_values[3] = [
  "Create a vertical 9:16 premium ecommerce main image.",
  "Image 1 is the exact product identity: one black speckled pullover hoodie with a hood, raglan sleeves, ribbed cuffs and hem, a front kangaroo pocket, and the exact readable white number 1977 on the chest.",
  "Preserve Image 1 silhouette, proportions, fabric texture, seams, pocket, sleeve shape, black color, speckles and the exact digits 1977.",
  "Image 2 is only a composition and commercial-layout reference.",
  "Borrow its clean warm-white background, centered isolated apparel presentation, generous negative space, product scale and minimal premium catalog mood.",
  "Do not copy either shirt from Image 2 and do not copy CHICERRO or any other brand, logo, watermark, slogan or readable text from Image 2.",
  "Generate exactly one hoodie, no model, no person, no duplicate garment, no extra accessories, no invented brand text.",
  "Use a soft natural grounding shadow and clean studio lighting.",
].join(" ");
editNode.widgets_values[4] = 2026082802;

saveNode.title = "本地结果｜与右侧网站基线人工对照";
saveNode.widgets_values = ["ecommerce/comparison/yinghai-hoodie-flux2-klein"];

const baselineNode = structuredClone(productNode);
baselineNode.id = 200;
baselineNode.order = 0;
baselineNode.pos = [900, 1040];
baselineNode.size = [360, 620];
baselineNode.title = "网站公开结果基线｜只看，不参与生成";
baselineNode.widgets_values = [baselineFile, "image"];
for (const output of baselineNode.outputs || []) output.links = null;

noteNode.title = "同输入对比说明｜不消耗网站积分";
noteNode.widgets_values = [
  [
    "## 映海公开卫衣案例｜本地同输入 A/B",
    "",
    "- 图 1：网站公开案例的 1977 卫衣商品图，原像素只加到 9:16 白色画布。",
    "- 图 2：三张公开对标图中与网站结果关系最直接的白底 CHICERRO 版式图。",
    "- 右侧基线：网站已经公开的结果，只用于人工比较，不连接采样器。",
    "- 本地输出：576×1024 起步，4 步，CFG 1，固定 seed 2026082802。",
    "",
    "### 比较重点",
    "",
    "1. 1977、帽子、袋鼠兜、袖口和黑色颗粒面料是否保持。",
    "2. 白底、居中比例、留白和目录式商业构图是否接近。",
    "3. 是否错误复制 CHICERRO；复制品牌即不通过。",
    "4. 是否只有一件卫衣，阴影是否自然。",
    "",
    "详细来源与哈希：docs/04-电商AI工作流/test-cases/01-映海卫衣公开案例对比.md",
  ].join("\n"),
];

workflow.nodes.push(baselineNode);
workflow.last_node_id = Math.max(workflow.last_node_id || 0, baselineNode.id);
workflow.groups = [
  {
    id: 1,
    title: "映海公开卫衣案例｜同输入、本地生成、网站结果基线",
    bounding: [-680, 350, 2000, 1380],
    color: "#3f789e",
    flags: {},
  },
];
workflow.extra = {
  ...(workflow.extra || {}),
  comparison_case: {
    prepared_at: "2026-08-28",
    derived_by: "scripts/derive_yinghai_hoodie_comparison_workflow.mjs",
    public_case_id: "22e90419-ec27-4bbe-9fc7-835bcfb73b16",
    public_endpoint: "https://yinghai.xin/api/feature-cases?config_key=main_image_demo",
    website_model_recorded_in_case: "gpt-image-2",
    website_resolution: "2K",
    website_ratio: "9:16",
    local_product_file: productFile,
    local_reference_file: referenceFile,
    local_baseline_file: baselineFile,
    local_output_prefix: "ecommerce/comparison/yinghai-hoodie-flux2-klein",
    limitation: "The website case used three references. This controlled local test uses the single reference most directly reflected in the public output.",
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(workflow, null, 2)}\n`);
