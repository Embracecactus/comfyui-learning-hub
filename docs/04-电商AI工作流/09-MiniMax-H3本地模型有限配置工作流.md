# MiniMax H3 本地模型：有限配置工作流

这一章使用真正的 MiniMax H3 本地权重，不调用 Partner Node，不登录 Comfy 账户，也不按生成次数扣 Credits。

配套工作流：[ecommerce-minimax-h3-local-ref2va.json](workflows/ecommerce-minimax-h3-local-ref2va.json)

## 1. 先看当前电脑能不能跑

2026-08-31 对当前电脑实测：

```text
GPU：NVIDIA GeForce RTX 5060，8 GB 显存
Windows 标称内存：16 GB；WSL/系统实际可见约 15 GiB，当时可用约 8.6 GiB
Swap：4 GiB，已经使用约 3.9 GiB
C 盘可用：约 205 GB
```

结论：磁盘勉强够，显存和内存不够，不能在当前电脑实际运行本地 H3 Ref2VA。这里的 15 GiB 是 16 GB 内存经过单位换算和系统保留后的可见容量，并不是另一台电脑或检测错误。

理由不是“8 GB 可能慢一点”，而是最小核心文件本身已经超过硬件容量：

| 文件 | 作用 | 官方仓库显示大小 |
|---|---|---:|
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 参考视频扩散模型 | 约 21 GB |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 文本/多模态编码器 | 约 15.7 GB |
| 两个 VAE | 解码视频与音频 | 另计 |
| Ref2V Turbo LoRA | 4 步加速 | 另计 |

即使分阶段 offload，15 GiB 系统内存也放不下 21 GB 扩散权重和运行中间数据。扩大 Windows 页文件只能造成严重磁盘换页，不能把它变成可用的视频生成方案。

## 2. 可执行方案

把“本地”理解为模型权重部署在自己控制的 GPU 机器上，而不是调用 MiniMax/Comfy API：

| 机器 | 结论 | 用法 |
|---|---|---|
| 当前 RTX 5060 8 GB / 15 GiB RAM | 不运行 | 编辑工作流、准备素材、查看结果 |
| 24 GB VRAM / 64 GB RAM | 最低实验档 | `--lowvram`、4 步、0.4 MP、5 秒 |
| 32–48 GB VRAM / 64 GB+ RAM | 推荐 | 先 0.4 MP 验证，再升 0.98 MP |
| 80 GB VRAM | 最稳 | 更高分辨率、更少 offload |

24 GB 是实验起点，不是官方保证的最低门槛。不同显卡架构、Torch/CUDA、系统内存和后台占用都会影响能否完成。

你已有的腾讯云 A10 24 GB 或阿里云 DSW A10 24 GB，可以作为第一台本地权重运行机器。模型文件在该实例磁盘上，生成过程不调用付费视频 API。

## 3. 为什么必须用 Ref2VA

H3 有两类扩散权重：

- `fl2va`：文本生成视频、首尾帧生成视频；
- `ref2va`：图片、视频、音频多素材参考生成视频。

我们要复刻“最多 9 图、3 视频、3 音频”的功能，因此必须下载 `minimax_h3_ref2va_...`，不能拿 `fl2va` 代替。

## 4. 四个必需权重

进入云 GPU 上的 ComfyUI 根目录，设置镜像后下载。下面使用 Hugging Face CLI；命令中的路径必须与 ComfyUI 模型目录一致。

```bash
export HF_ENDPOINT=https://hf-mirror.com
export COMFY_ROOT=/workspace/ComfyUI

hf download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors \
  text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors \
  --local-dir "$COMFY_ROOT/models"
```

下载后检查：

```bash
find "$COMFY_ROOT/models" -type f \
  \( -name 'minimax_h3_ref2va*' \
  -o -name 'qwen3vl_32b_minimax_h3*' \
  -o -name 'minimax_h3_*vae*' \
  -o -name 'minimax_h3_ref2v_turbo*' \) \
  -printf '%p  %s bytes\n'
```

不要使用 `huggingface-cli download ... --local-dir models/MiniMax-H3` 把所有文件堆在一个目录；ComfyUI 需要分别在 `diffusion_models`、`text_encoders`、`vae`、`loras` 下找到它们。

## 5. Torch 与 int8_convrot

`int8_convrot` 路线依赖较新的 CUDA/Torch 支持。先检查：

```bash
cd /workspace/ComfyUI
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.get_device_name()); print(round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1), 'GiB')"
```

如果运行时报 int8、convrot、kernel 或 CUDA 算子不支持：

1. 优先使用 ComfyUI 官方模板所对应的当前 Nightly 环境；
2. 更新 ComfyUI 和它要求的 Torch 版本；
3. 若仍不兼容，把扩散权重换成 `minimax_h3_ref2va_pruned_fp8_scaled.safetensors`，并在 `UNETLoader` 中选择它。

FP8 文件也约 21 GB，只是兼容路径不同，不会让 8 GB 显卡变得可运行。

## 6. 启动参数

24 GB 实验机先用：

```bash
cd /workspace/ComfyUI
python main.py --listen 0.0.0.0 --port 8188 --lowvram
```

不要在公网直接暴露 8188。使用云平台自带代理、SSH 隧道或安全组白名单。

## 7. 第一次导入和运行

1. 把测试图放到云端 `ComfyUI/input/amber-serum-transparent.png`。
2. 导入配套 JSON。
3. 确认所有模型节点都不是红色。
4. 在 `Picture 1` 节点重新选择商品图。
5. 保持默认：

   ```text
   9:16 (Portrait Widescreen)
   0.4 megapixels，约 480×864
   5 秒
   Enable Lightning LoRA = true
   4 steps
   ref_image_size = match
   ```

6. 关闭其他占显存程序，点击运行一次。
7. 输出目录：

   ```text
   ComfyUI/output/ecommerce/video
   ```

不要第一次就改成 0.98 MP、20 步或多张参考图。先证明链路能完整完成。

## 8. 工作流节点分组

官方本地 R2V 模板的主链路是：

```text
LoadImage
  ↓
MiniMaxH3ReferenceToVideo ← CLIPLoader + 两个 VAELoader
  ↓ CONDITIONING + LATENT
BasicGuider + SamplerCustomAdvanced
  ↓
VAEDecode（画面） + VAEDecodeAudio（声音）
  ↓
CreateVideo
  ↓
SaveVideo
```

关键节点：

- `UNETLoader`：加载约 21 GB Ref2VA 扩散权重。
- `CLIPLoader`：加载 Qwen3-VL 32B NVFP4 编码器。
- `MiniMaxH3ReferenceToVideo`：把 `<Picture 1>` 素材和提示词编码为参考条件与联合音视频 latent。
- `LoraLoaderModelOnly`：加载 4 步 Turbo LoRA。
- `ComfySwitchNode`：开启 Turbo 时同时选择 LoRA 模型和 4 步采样。
- `SamplerCustomAdvanced`：真正执行扩散采样，是最耗显存和时间的部分。
- `VAEDecode` / `VAEDecodeAudio`：分别解码画面和原生声音。
- `CreateVideo`：按 24 fps 合并音视频。

## 9. 多素材怎么加

H3 本地节点使用尖括号标签：

```text
ref_image_0 → <Picture 1>
ref_image_1 → <Picture 2>
ref_video_0 → <Video 1>
ref_audio_0 → <Audio 1>
```

增加素材时，先在加载节点选择有效文件，再连接。一次只增加一种素材，并同步修改提示词。

第一版不预放空的可选媒体节点，避免导入后出现“媒体输入未选择”。

## 10. 参数升级顺序

链路跑通后按顺序升级，每次只改一项：

1. 固定 seed，重复一次，确认结果可比较。
2. `0.4 MP → 0.6 MP`。
3. `0.6 MP → 0.98 MP`，约 768×1344。
4. 增加第二张场景参考图。
5. 最后才增加参考视频或音频。

若 OOM，按相反顺序回退，并确认 `--lowvram`、Turbo 4 步和 `ref_image_size=match` 仍然开启。

## 11. 验收标准

- 全程只有一个商品，不出现复制品；
- 包装比例、主色、材质和 Logo 位置基本稳定；
- 5 秒镜头连续，没有突然切成另一场景；
- 能同时输出画面和声音；
- 没有陌生字幕、水印或额外品牌；
- 峰值显存、系统内存、总耗时和 GPU 型号记录到测试日志。

## 12. 来源与边界

- [Comfy-Org 官方 MiniMax H3 本地 R2V 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json)
- [Comfy-Org MiniMax H3 权重仓库](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [ComfyUI 内置本地 H3 节点源码](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py)
- [MiniMax H3 官方项目](https://github.com/MiniMax-AI/MiniMax-H3)

MiniMax H3 权重采用其 Community License，不是普通 MIT 模型许可证。部署和商用前应阅读模型仓库中的许可条款。

本项目派生官方工作流并针对电商商品、有限配置和小白操作做了修改；参考站的内部工作流没有公开，不能声称服务端实现完全一致。
