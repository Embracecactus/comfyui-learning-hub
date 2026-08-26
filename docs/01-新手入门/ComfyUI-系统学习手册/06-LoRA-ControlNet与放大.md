# 06｜LoRA、ControlNet 与放大

## 1. LoRA 是什么

LoRA 是附加在基础模型上的小型权重，用来注入角色、风格、服装、物体或概念。它不是独立大模型，必须与兼容的基础架构配合。

```text
Load Checkpoint ─ MODEL ─→ Load LoRA ─ MODEL ─→ KSampler
               └ CLIP ──→ Load LoRA ─ CLIP ──→ CLIP Text Encode
```

### Load LoRA 的参数

- `lora_name`：`models/loras/` 中的文件。
- `strength_model`：LoRA 对扩散模型的影响强度。
- `strength_clip`：LoRA 对文本编码器的影响强度。

建议从模型作者推荐值或 `0.6～1.0` 附近起步。LoRA 强度不是统一刻度，有些 0.4 已很强，有些需要 1.0。负值虽可输入，但只有明确知道用途时使用。

### 多个 LoRA

多个 `Load LoRA` 可以串联：

```text
Checkpoint → LoRA A → LoRA B → KSampler
```

每叠一个 LoRA 都可能互相干扰。先分别验证，再一起使用；总强度过高常导致风格过载、结构异常或颜色脏。

### 常见错误

- SD1.5 LoRA 接到 SDXL/Flux 基础模型：架构不匹配。
- 忘记模型作者要求的触发词：效果不明显。
- 只把 LoRA 后的 MODEL 接走，却仍使用 LoRA 前的 CLIP：文本侧效果可能缺失。
- LoRA 文件放到 checkpoints：加载器下拉框看不到。

## 2. ControlNet 是什么

ControlNet 用边缘、姿态、深度、线稿等控制图约束生成结构。它通常包含三部分：

1. 控制图：原图或预处理结果。
2. 与基础模型兼容的 ControlNet 权重。
3. `Apply ControlNet` 把控制信息写入正/负 conditioning。

基础连接：

```text
Load ControlNet Model ─ CONTROL_NET ─┐
控制图 / 预处理结果 ─────── IMAGE ────┤
正向 conditioning ──────────────────┤→ Apply ControlNet ─ positive ─→ KSampler
负向 conditioning ──────────────────┘                   └ negative ─→ KSampler
```

### Apply ControlNet 关键参数

- `strength`：控制强度。过低看不出约束，过高会僵硬或产生控制图痕迹。
- `start_percent`：从采样过程哪个比例开始生效。
- `end_percent`：到哪个比例停止生效。
- `vae`：部分 ControlNet/工作流可选或需要。

例如 `start=0, end=0.6` 表示主要约束早期结构，后期给模型更多自由细化。

### 预处理器与 ControlNet 必须匹配

- Canny ControlNet 配 Canny 边缘图。
- OpenPose 类 ControlNet 配姿态骨架图。
- Depth ControlNet 配深度图。
- Lineart ControlNet 配线稿。

把普通照片直接交给期待边缘图的 ControlNet，未必会自动替你提取边缘。预处理节点可能来自 Comfy Core，也可能来自第三方包。

## 3. 像素插值放大和模型放大

### Upscale Image / Upscale Image By

使用 nearest、bilinear、bicubic、lanczos 等传统插值，只改变像素尺寸，不会真正创造可信细节。适合对齐尺寸、进入后续流程或做轻量缩放。

### Load Upscale Model + Upscale Image (using Model)

使用 ESRGAN 等超分模型补充纹理细节：

```text
Load Upscale Model ─ UPSCALE_MODEL ─┐
IMAGE ──────────────────────────────┤→ Upscale Image (using Model) → IMAGE
```

优点是简单快速；缺点是可能过度锐化、改变纹理或产生伪细节。

### Latent Upscale

在潜空间中放大，然后再次采样。通常比纯插值更有机会增加生成式细节，但 denoise 太高会改变原图，太低则细节提升有限。

## 4. 常见二次采样高清流程

```text
第一次 KSampler → latent
        ↓
Upscale Latent By（如 1.5～2 倍）
        ↓
第二次 KSampler（较低 denoise）
        ↓
VAE Decode → Save Image
```

建议：

- 第一阶段解决构图，第二阶段解决尺寸和细节。
- 第二阶段固定 seed 并从较低 denoise 测试。
- 宽高翻倍约等于像素四倍，先估算显存。
- 最终可再使用轻量超分模型，但要比较是否出现假纹理。

## 5. 三者怎么选

| 需求 | 首选 |
|---|---|
| 改画风、角色或服装概念 | LoRA |
| 保持姿态、边缘、深度或构图 | ControlNet |
| 只改变输出像素尺寸 | 普通 Upscale |
| 希望补纹理且可接受模型推断 | 超分模型 |
| 放大同时重新生成细节 | Latent upscale + 二次采样 |

它们可以组合，但排错时应一次只加一个模块。基础文生图能跑后，加 LoRA 验证，再加 ControlNet，最后加放大；这样能快速定位是哪一步出问题。

下一章：[模板、工作流与自定义节点](07-模板-工作流与自定义节点.md)。
