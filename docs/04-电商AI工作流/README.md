# 电商 AI 工作流项目

这是一个独立项目。目标是搭建一套与[赢海 AIGC 站](https://yinghai.xin/)公开产品方向相似、能够在本地理解和修改的电商图片与视频素材工作流。

这里不只提供“能打开的 JSON”，还会按产品目标拆解每条工作流的输入、输出、节点职责、连线、模型目录、硬件差异和验收方法。对方的服务端模型与内部工作流并未公开，本项目只复现可观察到的功能类别和输入输出，不复制或推断其私有实现。

## 已完成

| 顺序 | 实战 | 学习结果 | 配套 JSON |
|---:|---|---|---|
| 1 | [电商商品场景图](01-商品场景图工作流.md) | AI 生成背景、商品遮罩、投影和原像素合成 | [打开](workflows/ecommerce-product-scene-sdxl.json) |
| 2 | [自动抠图与白底主图](02-自动抠图与白底主图工作流.md) | 普通照片自动分割、透明 PNG、动态同尺寸白底合成 | [打开](workflows/ecommerce-auto-cutout-white-background-birefnet.json) |
| 3 | [四种风格商品主图批量生成](03-四种风格商品主图批量生成.md) | 四套提示词顺序采样、图片合批、同一商品批量保真合成 | [打开](workflows/ecommerce-main-image-four-styles-sdxl.json) |
| 4 | [参考图驱动商品主图](04-参考图驱动商品主图工作流.md) | 商品身份与对标视觉双参考、FLUX.2 Klein 完整图像编辑 | [打开](workflows/ecommerce-reference-main-image-flux2-klein.json) |
| 4A | [映海卫衣公开案例同输入对比](test-cases/01-映海卫衣公开案例对比.md) | 固定商品、代表性参考、网站公开结果基线与逐项验收 | [打开](workflows/ecommerce-yinghai-hoodie-comparison-flux2-klein.json) |
| 5 | [映海卫衣三结果分支复刻](05-映海卫衣三结果复刻实战.md) | 原像素平铺 + 男模全身 + 男模近景，三条独立工作流 | [平铺](workflows/ecommerce-yinghai-hoodie-flat-pixel-faithful-birefnet.json) / [全身](workflows/ecommerce-yinghai-hoodie-model-full-flux2-klein.json) / [近景](workflows/ecommerce-yinghai-hoodie-model-close-flux2-klein.json) |

参考站登录实测、公开接口、案例观察、差异判断、技术选型和未验证事项统一记录在[2026-08-28 映海站实测与重构决策](reference-site-audit-2026-08-28.md)，后续不需要重新调查同一批信息。

没有透明商品素材时，可以使用项目提供的测试图片：

- [无品牌琥珀精华瓶](assets/test-products/amber-serum-transparent.png)：适合验证第一章商品场景合成。
- [无品牌象牙白面霜罐](assets/test-products/ivory-cream-jar-transparent.png)：适合验证第三章四种明暗背景批量生成。

两张图片均为 1:1 RGBA PNG，背景 alpha 已验证为真实透明。

需要验证第 4 阶段是否真正借鉴了参考版式时，直接使用[映海卫衣公开案例同输入对比](test-cases/01-映海卫衣公开案例对比.md)。第三方公开案例素材只保存在本机 ComfyUI `input` 目录，仓库记录来源、哈希和用法，不再分发图片文件。

## 电商素材工作流路线

目标是逐步形成一套与电商 AI 素材平台公开功能方向相似、但可以在本地理解和修改的模块化工作流：

| 阶段 | 工作流 | 状态 | 核心难点 |
|---:|---|---|---|
| 1 | 透明商品 → AI 场景图 | 已完成 | 遮罩方向、商品保真、接触阴影 |
| 2 | 自动抠图与白底主图 | 已完成 | 背景分割、遮罩方向、边缘和半透明材质 |
| 3 | 商品主图批量变体 | 链路完成，视觉验收中 | 风格模板、种子管理、显存安全的顺序采样与图片批次 |
| 4 | 参考图驱动商品主图 | 已搭建，待本机运行 | 多参考语义编辑、商品保真、8 GB 模型卸载 |
| 5 | 模特穿戴/换装 | 最小双参考分支已搭建，待本机实测 | 姿态、服装区域、身份与商品一致性 |
| 6 | 详情页素材与版式 | 待学习 | 多图叙事、中文文字、最终排版工具 |
| 7 | 商品广告与带货视频 | 待学习 | 商品一致性、镜头设计、视频模型选择 |
| 8 | 参考视频拆镜与成片 | 待学习 | 分镜、节奏、音频、字幕和镜头拼接 |

先把每个模块单独跑通，再决定哪些模块需要组合。大型一体化画布同时加载多个图像和视频模型，在 8 GB 显存电脑上会更慢，也更难判断是哪一步出错。
