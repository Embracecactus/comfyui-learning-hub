# MiniMax H3 部署指导（基于当前硬件）

> 适用环境：RTX 5060 8GB / Ryzen 9 9950X / 15GB 内存 / ComfyUI v0.33.0
> 编写日期：2026-08-25

---

## 0. 你的硬件现状

| 项目 | 规格 | 对 H3 的影响 |
|---|---|---|
| GPU | RTX 5060（Blackwell） | **8GB 显存**，瓶颈 |
| CPU | AMD Ryzen 9 9950X（16C/32T） | 很强，但补不了显存/内存缺口 |
| 内存 | 15GB | **不足以容纳权重**，硬墙 |
| 磁盘 | 418GB 可用 | 放权重绰绰有余 |
| ComfyUI | v0.33.0 | 已集成 H3 原生节点 + 工作流模板 |

RTX 5060 是 Blackwell 架构，**原生支持 fp4/nvfp4**，对 4bit 文本编码器是好消息，但救不了内存缺口。

---

## 1. 结论（先看这个）

**当前机器无法本地推理 MiniMax H3。** 原因不是慢，是加载阶段就会 OOM 被杀：

- H3 全量化权重约 **40GB+**，但本机只有 15GB 内存。
- ComfyUI 的卸载机制是把权重缓冲在**系统内存**里、按需搬显存，它**没有自动落盘分页**。权重 > 内存 → 加载即 OOM。
- 即便最小量化，32B 文本编码器（4bit）也约 16GB，单它已超 8GB 显存。

**两条可行路线：**
- **路线 A（推荐，当前机器立即可用）**：走 MiniMax 官方托管 API，按量付费，2K 直出，零硬件门槛。
- **路线 B（需先升级硬件）**：本地全量运行，需 ≥24GB 显存 + ≥64GB 内存。

---

## 2. 权重与资源需求

| 组件 | 量化 | 大致体积 | ComfyUI 落位目录 |
|---|---|---|---|
| DiT 主干 | `minimax_h3_fl2va_pruned_int8_convrot` (int8) | ~20GB | `models/diffusion_models/` |
| 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq` (nvfp4, 32B) | ~16–20GB | `models/text_encoders/` |
| VAE | H3 VAE（文件名以仓库为准，如 `h3_vae.safetensors`） | 数 GB | `models/vae/` |
| **合计** | 全量化 | **≈ 40GB+** | — |

具体文件名/体积以 ModelScope / HuggingFace 仓库实际列出为准。
下载前请先确认磁盘 ≥ 60GB 空闲（权重 + 系统/页面文件余量）。

---

## 3. 路线 A：API 模式（推荐，当前机器可用）

核心 H3 节点是**本地推理节点**（必须本机加载权重）。要走 API，需调用 MiniMax 官方托管 API：

**获取 Key**
- MiniMax 开放平台 / Hailuo AI：注册后在控制台创建 API Key。
- 文档与端点：`https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create`

**调用方式（任选）**
1. 直接用 Python / curl 调官方 API（最简单，不依赖 ComfyUI 节点）。
2. 在 ComfyUI 中查找官方/社区 "MiniMax" API 节点（核心内置节点不含 API 模式，需自行安装社区节点）。

**最小 curl 示例（文生视频）**
```bash
curl https://api.minimaxi.com/v1/video_generation \
  -H "Authorization: Bearer $MINIMAX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-H3",
    "prompt": "一只猫在窗台上看雨",
    "duration": 5
  }'
```
（实际参数以官方 API 文档为准；API 全球可用，不受权重下载地区限制。）

**优点**：零硬件门槛、2K 直出、商用可用（遵守社区许可标注要求）。
**成本**：按量付费，2K 每秒价格低于主流闭源模型。

---

## 4. 路线 B：本地部署（需先升级硬件）

### 4.1 硬件升级清单

| 部件 | 最低要求 | 舒适要求 | 说明 |
|---|---|---|---|
| GPU 显存 | ≥24GB（RTX 4090/5090 24GB） | ≥48GB（RTX 6000 Ada / 5090 24GB 多卡） | 需同时容纳 DiT(~20GB) + 文本编码器分片 |
| 内存 | ≥64GB | ≥128GB | 32B 文本编码器全量驻留内存所需 |
| 磁盘 | ≥60GB 空闲 | ≥100GB | 权重 40GB + 余量 |
| 架构 | Blackwell 优先 | — | 原生 fp4 加速 4bit 文本编码器 |

> 仅换显卡不够：15GB 内存是第二道墙，必须同时升级到 ≥64GB。

### 4.2 权重下载（ModelScope，国内可用）

- 仓库：ModelScope `MiniMax/MiniMax-H3`，或 HuggingFace `MiniMaxAI/MiniMax-H3`（注意地区限制）。
- 许可：**MiniMax H3 Community License**。商用要点：① 商业产品年收入 > 2000 万美元需书面授权；② 须显著标注 "MiniMax H3"；③ 产出与权重不得用于训练其他 AI 模型。
- **权重下载地区限制**：社区许可暂不含美国 / 欧盟 / 英国 / 韩国。你应在国内，走 ModelScope 即可。

下载并落位（示例，按实际文件名调整）：
```bash
pip install modelscope
modelscope download --model MiniMax/MiniMax-H3 \
  minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  --local_dir models/diffusion_models/
modelscope download --model MiniMax/MiniMax-H3 \
  qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
  --local_dir models/text_encoders/
modelscope download --model MiniMax/MiniMax-H3 \
  h3_vae.safetensors \
  --local_dir models/vae/
```

### 4.3 启动与卸载

```bash
# 标准启动
python main.py

# 显存极度紧张时（仍需足够内存）：最小显存模式，权重全卸载到内存
python main.py --novram

# 或完全 CPU（仅验证流程，极慢）
python main.py --cpu
```
> ⚠️ 15GB 内存机器即使 `--novram` 也会 OOM。本地运行前提见 4.1。

**工作流搭建**
- 最快：ComfyUI 左侧 **Templates** 面板搜索 "MiniMax H3"，加载官方示例图（v0.33.0 已装 `comfyui-workflow-templates-*` 模板包），只需在 loader 里指向已下载权重。
- 手动：加载器 `UNetLoader`（选 DiT）/ `CLIPLoader`（选 Qwen3-VL 文本编码器）/ `VAELoader`（选 H3 VAE）→ 接下方节点。

### 4.4 节点速查（来自 ComfyUI 核心）

| 节点 | 作用 |
|---|---|
| `EmptyMiniMaxH3LatentAV` | 生成联合视频+音频 latent（时长按 17k+5 帧网格对齐，24fps） |
| `MiniMaxH3ImageToVideo` | T2V / 首尾帧 I2V（`first_frame` / `last_frame`） |
| `MiniMaxH3ReferenceToVideo` | Ref2VA 全参照：最多 9 图 + 3 视频 + 3 音频 |
| `MiniMaxH3AddGuide` | 在任意像素帧锚定图/视频/音频引导（可链式多个） |
| `MiniMaxH3SigmaShift` | 设置 video/audio flow shift（默认 12.0 / 3.0） |

**画布规格**：768 短边，768×1344 面积上限；长度默认 124 帧（~5s），训练范围 124–362（更长未测试）。

---

## 5. 排错

| 现象 | 原因 / 处理 |
|---|---|
| 启动即被杀 / CUDA OOM 在加载阶段 | 内存不足（权重 > 内存）。升级硬件或改路线 A |
| 节点报找不到权重 | 确认文件名与落位目录：`diffusion_models/` / `text_encoders/` / `vae/` |
| 下载 403 / 不可见 | 所在地区受限（美/欧/英/韩）。改 API 或申请机构授权 |
| `MiniMax H3 supports batch size 1` | H3 仅支持 bs=1，属正常限制，勿设 batch>1 |
| 文本/品牌文字渲染异常 | 提高分辨率或调整 prompt，遵循指令遵循最佳实践 |

---

## 6. 当前机器推荐动作

1. **先用路线 A（API）跑通一条 H3 视频**，验证效果与成本。
2. 若确需本地私有部署，按 §4.1 升级硬件（显卡 + 内存同时）后，再走 §4.2–§4.3。
3. 不要在当前 8GB/15GB 机器上强行下载 40GB 权重——预期加载即 OOM，纯属浪费带宽。
