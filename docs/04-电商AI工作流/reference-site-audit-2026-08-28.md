# 映海站实测、对比与重构决策记录（2026-08-28）

这份记录用于回答一个具体问题：项目第 3 阶段的“SDXL 生成四种背景，再覆盖透明商品”是否已经达到[映海 AIGC 站](https://yinghai.xin/)“复刻商品主图”的实际效果。

结论：**没有达到，也不应继续描述为同等能力。** 第 3 阶段是一条适合学习遮罩、批次和保真合成的固定模板链路；参考站使用商品图、对标主图和商品描述共同驱动整图生成，能够改变构图、光照、人物、服装穿着关系和版式。

本文保留本次调查的输入、观察、公开接口、证据、限制和后续技术决策。手机号、短信验证码、会话 Cookie、平台 API Key 等敏感信息不写入仓库。

## 1. 本次实际执行了什么

访问日期：`2026-08-28`。

执行范围：

1. 使用独立临时浏览器会话访问 `https://yinghai.xin/main-image`。
2. 在用户明确授权后完成短信登录和页面要求的三项确认。
3. 打开“复刻商品主图”，查看真实表单、案例回填、动态报价和个人中心计费说明。
4. 点击网站自带“复刻商品主图-卫衣”的“做同款”，只让公开案例参数回填到表单。
5. 读取公开案例接口，下载到 `/tmp` 做临时视觉对比；第三方案例图片没有提交到本仓库。
6. 没有点击“提交生成任务”，没有调用生成接口，没有消耗积分，也没有充值或修改账户资料。

这次只发生了登录和页面内只读/回填操作。以后若需要用本项目测试商品真正生成，必须先记录输入、模型、尺寸、当次动态报价，并再次确认是否允许消费积分。

## 2. 登录后看到的真实“复刻商品主图”输入

| 输入/设置 | 是否必填 | 页面实测说明 |
|---|---:|---|
| 商品图 | 是 | `1～10` 张；决定要保留的商品身份和外观 |
| 对标主图 | 是 | `1～10` 张；提供竞品构图、风格和版式参考 |
| 模特图 | 否 | 最多 `1` 张；用于指定人物展示方向 |
| 商品描述 | 是 | 要求描述材质、结构、特点和卖点，不只是短提示词 |
| 首选模型 | 是 | 实测页面显示“智能生图-IG-2.0”；公开案例参数记录为 `gpt-image-2` |
| 画质 | 是 | 案例回填为 `2K` |
| 图片比例 | 是 | 案例回填为 `9:16`；页面还提供多种常见比例 |

网站不是“上传透明 PNG 后套四个背景模板”。它先理解商品与参考图，再重新生成一张完整成片。

## 3. 自带案例回填记录

案例：“复刻商品主图-卫衣”。

回填内容：

- 商品图：`1` 张黑色 `1977` 连帽卫衣。
- 对标主图：`3` 张浅色服装商业图。
- 模特图：`0` 张。
- 商品描述：包含版型、印花、面料、袋鼠兜、罗纹收口和卖点的长描述。
- 模型：页面显示“智能生图-IG-2.0”。
- 画质：`2K`。
- 比例：`9:16`。
- 当次动态报价：`1.17` 点。价格可能变化，只能作为 `2026-08-28` 的实测快照。

回填后“提交生成任务”按钮可用，但本次没有提交。

## 4. 公开案例证据

### 4.1 公开接口

本次只读取以下 GET 接口：

```text
https://yinghai.xin/api/feature-cases?config_key=main_image_demo
https://yinghai.xin/api/feature-cases?config_key=product_scene_image_demo
```

`main_image_demo` 在本次检查时包含卫衣和深灰色抓褶鱼尾连衣裙案例。`product_scene_image_demo` 包含婴儿连体衣、鞋子和卫裤的多张场景图案例。

### 4.2 卫衣案例说明了什么

输入是一张黑色卫衣商品图和三张浅色竞品服装图。公开案例不是单张结果，而是同时发布了三张 `1440 × 2560` 成片：

1. 白底平铺卫衣图，重做留白、画幅和底部 `CHICERRO` 品牌式版面。
2. 男模正面穿着卫衣图，左上角带“高克重抗起球面料 / 宽松插肩 复古百搭”中文卖点。
3. 男模近景穿着卫衣图，无额外标题，突出服装上身效果。

可观察结论：

- 商品主体来自商品图，而不是把竞品衣服换色。
- 对标图控制了简洁白底、画面比例和版式气质。
- 即使没有上传模特图，服务仍能生成新人物和服装上身关系；这部分不是简单抠图或像素覆盖能完成的。
- 结果中的品牌式文字存在误复制风险，商用前必须核对并去除竞品品牌。

### 4.3 连衣裙案例说明了什么

输入是一张单独的深灰色细带鱼尾裙商品图和四张粉色少女风穿搭/详情参考图。公开结果生成了新的模特穿着关系、粉白版式、商品局部小窗和装饰文字。

可观察结论：

- 模型不仅换背景，还重新生成了人物、服装上身关系和整页排版。
- 参考图影响配色、人物气质、信息层级和装饰风格。
- 这类结果不可能由“背景图 + 透明商品 PNG 覆盖”完成，需要语义图像编辑或虚拟试穿模型。

## 5. 与第 3 阶段工作流的逐项对比

| 能力 | 参考站实测 | 第 3 阶段 SDXL 固定四风格 | 判断 |
|---|---|---|---|
| 商品图输入 | 1～10 张 | 1 张透明 PNG | 只覆盖最小输入 |
| 对标主图输入 | 1～10 张 | 没有 | 核心缺失 |
| 商品描述 | 详细必填 | 四套固定背景提示词 | 核心缺失 |
| 模特输入 | 可选 1 张 | 没有 | 缺失 |
| 整图生成 | 是 | 否，只生成背景 | 本质不同 |
| 商品与环境光照融合 | 模型共同生成 | 原像素直接覆盖 | 第 3 阶段容易有粘贴感 |
| 人物/穿搭关系 | 可以生成 | 不支持 | 完全不具备 |
| 任意对标构图复刻 | 支持多参考 | 只能四个预设 | 完全不具备 |
| 商品像素绝对保真 | 不保证，需复核 | 原图覆盖，最稳定 | 第 3 阶段的优势 |
| 8 GB 本地运行成本 | 云端不可见 | 可运行 | 第 3 阶段的优势 |

所以第 3 阶段应保留为“固定模板与批次合成教学版”，不能作为最终“复刻商品主图”。

## 6. 左下角蓝色方案为什么突兀

用户截图中左下角商品两侧出现蓝色三角/翼状物，原因不是商品 PNG 本身，而是两步组合造成的：

1. SDXL 背景分支把蓝色科技场景理解成中央亚克力台、几何道具或向两侧伸出的结构。
2. 最终 `ImageCompositeMasked` 把商品原像素盖在中央，只遮住道具的中间部分；道具两侧仍露出，于是看起来像从商品上长出来。

此外，旧流程的阴影是“商品完整轮廓模糊后向下平移 12 像素”，不是只在底部生成的接触阴影。遇到半透明罐体、复杂底座或不同主光方向时，阴影也可能显得脏、宽或悬浮。

提示词增加 `no pedestal`、`no wings` 等只能降低概率，不能改变“先生成背景、后覆盖商品”的结构性限制。

## 7. 重构决策

下一条工作流改用 ComfyUI 官方支持的 **FLUX.2 Klein 4B Distilled 图像编辑**：

```text
图 1：自家商品图（主体身份） ─┐
                               ├→ FLUX.2 Klein 双参考编辑 → 完整商品主图
图 2：对标主图（构图与风格） ─┘
                    商品详细提示词 ─┘
```

选择原因：

- 官方明确支持单参考、多参考合成和语义编辑。
- 4B 蒸馏版比 Qwen-Image-Edit 20B 和 FLUX.2 Dev 更接近 8 GB 机器可运行范围。
- 官方模板已经使用两个 `ReferenceLatent` 链路，正好对应“商品身份 + 对标视觉”。
- 生成完整画面，可以让光照、接触阴影、遮挡和背景统一参与采样。

官方参考峰值为 `8.4 GB VRAM`，而实测电脑 RTX 5060 只有约 `8 GB` 可用显存，因此不能承诺原速运行。需要关闭其他占显存程序，并让 ComfyUI 使用模型卸载/低显存路径；若仍失败，再降低参考图总像素或使用云端/API 方案。

## 8. 官方来源与可复现文件

- [ComfyUI 官方 FLUX.2 Klein 指南](https://docs.comfy.org/tutorials/flux/flux-2-klein)
- [官方 4B Distilled 双参考编辑模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_klein_image_edit_4b_distilled.json)
- [本项目派生脚本](../../scripts/derive_flux2_klein_reference_workflow.mjs)
- [工作流静态校验脚本](../../scripts/validate_comfy_workflow.mjs)
- [第三方来源与 MIT 许可证声明](../../THIRD_PARTY_NOTICES.md)
- [本项目派生工作流](workflows/ecommerce-reference-main-image-flux2-klein.json)
- [第 4 阶段搭建文档](04-参考图驱动商品主图工作流.md)

重新派生工作流：

```bash
curl -L -o /tmp/image_flux2_klein_image_edit_4b_distilled.json \
  https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_flux2_klein_image_edit_4b_distilled.json

node scripts/derive_flux2_klein_reference_workflow.mjs \
  /tmp/image_flux2_klein_image_edit_4b_distilled.json \
  docs/04-电商AI工作流/workflows/ecommerce-reference-main-image-flux2-klein.json
```

派生 JSON 的 `extra.audit` 字段也保存了原模板 URL、日期、脚本和改动摘要。

静态校验命令：

```bash
node scripts/validate_comfy_workflow.mjs \
  docs/04-电商AI工作流/workflows/ecommerce-reference-main-image-flux2-klein.json
```

本次校验结果：`5` 个顶层节点、`3` 条顶层连线、`4` 个子图、`40` 个子图内部节点，未发现重复节点 ID、悬空连线或缺失子图定义。相关的 6 份 Markdown 文档本地链接检查通过，`git diff --check` 通过。

## 9. 尚未验证的部分

截至本记录：

- 派生工作流的 JSON 结构可以静态校验。
- 三个 FLUX.2 Klein 模型已经下载到目标 Windows Desktop 共享模型目录，并通过精确字节数检查；尚未实际运行工作流。
- 尚未验证 RTX 5060 8 GB 的首张生成耗时、峰值显存和包装文字保真率。
- 尚未使用网站余额提交同一商品做 A/B 生成，所以没有声称本地成片已经追平参考站。

下一次继续时应从[第 4 阶段搭建文档](04-参考图驱动商品主图工作流.md)的“运行前验收”开始，不需要重新调查网站表单和官方基础模板。

## 10. 目标机器模型与 Core 验证记录

验证日期：`2026-08-28`。

共享模型目录使用 `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models`。三个目标文件均已去掉 `.download`，没有发现同名断点残留：

| 文件 | 实测字节数 | 结果 |
|---|---:|---|
| `vae/flux2-vae.safetensors` | `336,213,556` | 通过 |
| `diffusion_models/flux-2-klein-4b-fp8.safetensors` | `4,070,624,520` | 通过 |
| `text_encoders/qwen_3_4b.safetensors` | `8,044,982,048` | 通过 |

目标 Desktop 实例：

```text
ComfyUI Core 0.33.4
Git commit 7a131a3afadc8200120f67f9236311a2c48b7445
Build date 2026-08-24
```

已在该实例源码中确认存在以下必需 Core 节点：

```text
EmptyFlux2LatentImage
Flux2Scheduler
ReferenceLatent
GetImageSize
SamplerCustomAdvanced
```

因此下一步不需要先更新 Core，应直接重启实例、导入派生 JSON，并检查三个模型下拉框是否自动命中。

## 11. 卫衣公开案例本地 A/B 素材准备记录

准备日期：`2026-08-28`。

为了让第 4 阶段第一次运行就能与参考站公开结果做可重复比较，已把卫衣案例的商品图、最有代表性的白底版式参考图和网站公开结果保存到 Desktop 共享输入目录：

```text
%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\input\yinghai-hoodie-comparison
```

本地文件与哈希：

```text
01-product-1977-hoodie.png
SHA-256 5cc9ab74ec3f09b47e5d921a5f9af37dc22f02eb14edc6217d24f4d3ee950082

01b-product-1977-hoodie-9x16-canvas.png
SHA-256 74325ea19aa0ba7749835ab69f92379f8be925dbd4cd88a5ab04e0ac13ae7319

02-reference-white-chicerro-layout.png
SHA-256 cfc1fa95fe6784cbfa792b9eeb4a716abc15a88a6d3b31fc2202e170e182344c

03-site-result-baseline.png
SHA-256 38e4445a3ad055b721704100250e3822caf6481b9aebb2fec27928242faf446a
```

`01b` 只把网站商品原图等比放入 `576 × 1024` 白色画布，没有 AI 重绘，用于让本地输出与网站的 `9:16` 比例一致。网站案例实际用了三张对标图；本地首轮只选最直接反映在公开结果中的白底版式图，以减少变量。详细 URL、尺寸、字节数、运行方法和验收表见[卫衣公开案例对比测试](test-cases/01-映海卫衣公开案例对比.md)。

为该案例新增了可重复派生文件：

- [案例工作流](workflows/ecommerce-yinghai-hoodie-comparison-flux2-klein.json)
- [案例派生脚本](../../scripts/derive_yinghai_hoodie_comparison_workflow.mjs)

工作流会自动选择前述三张图片，固定 seed `2026082802`，并把网站结果作为断开的预览节点。图片是第三方公开案例，只保存在本机，没有提交到 GitHub；仓库只保留 URL、哈希、配置和派生方法。本次仍未调用网站生成接口或消耗积分。

### 11.1 第一次导入的缺失输入错误与修正

第一次导入专用 JSON 时，三个 `LoadImage` 节点同时报告“所需的媒体输入未选择文件”。根因是素材最初放在了实例源码目录：

```text
ComfyUI-Installs\ComfyUI-RTX5060\ComfyUI\input
```

但该 Desktop 实例的启动日志明确记录：

```text
Setting input directory to: C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input
Setting output directory to: C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output
```

`2026-08-28` 已将四张素材复制到正确的 `ComfyUI-Shared\input\yinghai-hoodie-comparison`，并重新核对四个 SHA-256，均与本节记录一致。原实例目录文件暂时保留作备份。修正后应重启/刷新实例并重新导入 JSON；因为首次导入时前端可能已经把不存在的下拉值清空，只按 `R` 不一定恢复。

## 12. 当前网页入口与“同款工作流”边界

复核日期：`2026-08-28`。

用户截图位于“一站式视频带货/图像视频创作”首页，因此看不到卫衣案例。该案例属于顶部“图片创作”分类下的独立“商品主图”功能。最稳定的访问方式是登录后直接打开：

```text
https://yinghai.xin/main-image
```

页面左侧标题应为“复刻商品主图”，右侧是“案例参考”。找到“复刻商品主图-卫衣”，点击案例预览可查看公开结果，点击“做同款”只会把案例商品图、三张对标图、商品描述、`2K` 和 `9:16` 参数回填到表单；只有随后点击提交生成任务才会进入计费生成步骤。

本次重新读取公开接口：

```text
https://yinghai.xin/api/feature-cases?config_key=main_image_demo
```

卫衣案例 ID `22e90419-ec27-4bbe-9fc7-835bcfb73b16` 仍为 `is_enabled: true`，并返回三张结果图。网站没有公开 ComfyUI 节点图、服务端工作流或内部实现；页面上的“做同款”指套用网站案例参数，不是下载节点工作流。本仓库的 ComfyUI JSON 是根据公开输入输出和官方模型能力自行搭建的本地实验，不能描述为网站内部工作流。

此前本地画布只加载三张网站结果中的第 1 张白底平铺图，因此三轮本地结果只评估“平铺商品主图”分支，没有评估另外两张男模穿着效果。新的混合像素保真路线也只解决平铺商品图；模特上身必须作为独立的虚拟试穿/语义生成项目继续研究。
