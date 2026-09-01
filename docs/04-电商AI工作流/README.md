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
| 6 | [通用商品自动排版](06-通用商品自动排版工作流.md) | 从遮罩自动裁边，按画布百分比缩放和定位，不绑定某个商品 | [打开](workflows/ecommerce-generic-product-layout-birefnet.json) |
| 7 | [通用商品 2K 与确定性排版](07-通用商品2K与确定性排版.md) | RealESRGAN 4× 后精确输出 1440×2560，并添加可编辑的真实卖点和自有品牌 | [打开](workflows/ecommerce-generic-product-layout-2k-branded.json) |
| 8 | [小白版：与参考站功能对比及阶段成果](08-与参考站功能对比及阶段成果.md) | 用生活化语言说明当前能做什么、不能做什么，以及为什么抠图排版不等于 AI 换装 | — |
| 9 | [MiniMax H3 量化模型：通用低显存自适应工作流](09-MiniMax-H3本地模型有限配置工作流.md) | 按算子选择 NVFP4/INT8、实时显存分块、Qwen→DiT→VAE 分阶段释放 | [NVFP4](workflows/ecommerce-minimax-h3-quantized-nvfp4-low-vram.json) / [INT8](workflows/ecommerce-minimax-h3-quantized-int8-low-vram.json) / [BF16 历史基线](workflows/ecommerce-minimax-h3-bf16-streaming-8gb.json) |
| 10 | [映海“复刻爆款带货视频”本地 H3 工作流](10-映海爆款带货视频本地复刻.md) | 商品图负责服装身份、对标视频负责人物动作/镜头/节奏；先做前 5 秒 0.1 MP 低显存验证 | [打开](workflows/ecommerce-yinghai-copy-hot-video-h3-nvfp4-low-vram.json) |

参考站的图片功能记录在[2026-08-28 映海站实测与重构决策](reference-site-audit-2026-08-28.md)；“复刻爆款带货视频”的真实表单、模型选项、公开案例媒体哈希和逐帧结论记录在[2026-09-01 视频功能实测](reference-site-video-audit-2026-09-01.md)。后续不需要重新调查同一批信息。

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
| 6 | 详情页素材与版式 | 2K 单图与确定性文字链路已完成 | 多图叙事、价格组件、品牌模板系统 |
| 7 | 商品广告与带货视频 | BF16 历史基线和 RTX 5060 8 GB 的 NVFP4 低分辨率基线均已实跑；INT8 与其他硬件待复测 | 不同 GPU 算子兼容、磁盘抖动、商品一致性与高分辨率耗时 |
| 8 | 参考视频拆镜与成片 | 前 5 秒商品图 + 对标视频 H3 工作流已搭建，待新分支真机运行 | 分镜、节奏、音频、字幕和镜头拼接 |

先把每个模块单独跑通，再决定哪些模块需要组合。大型一体化画布同时加载多个图像和视频模型，在 8 GB 显存电脑上会更慢，也更难判断是哪一步出错。
