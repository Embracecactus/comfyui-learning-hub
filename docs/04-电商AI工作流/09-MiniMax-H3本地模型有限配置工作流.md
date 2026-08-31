# MiniMax H3 本地模型：RTX 5060 8GB 无量化流式工作流

这一章坚持在本机运行 MiniMax H3，不调用视频生成 API，也不把扩散模型或文本编码器改成 INT8、FP8、NVFP4、NF4 或 GGUF。

配套文件：

- [RTX 5060 8GB BF16 流式工作流](workflows/ecommerce-minimax-h3-bf16-streaming-8gb.json)
- [Windows 断点续传下载脚本](../../scripts/download_minimax_h3_bf16_windows.cmd)
- [24GB 量化实验旧版](workflows/ecommerce-minimax-h3-local-ref2va.json)仅保留用于历史对比，本章不使用。

## 1. 先说结论

当前电脑实测环境：

```text
GPU：NVIDIA GeForce RTX 5060
显存：7.96 GiB
计算能力：SM 12.0（Blackwell）
Windows 物理内存：约 32 GB
当前 Windows 页面文件：22 GB
当前 C 盘可用：约 204 GiB
ComfyUI Python：ComfyUI/.venv/Scripts/python.exe
Python：3.13.12
PyTorch：2.12.1+cu130
CUDA runtime：13.0
```

这台电脑无法把约 37.46 GiB 的 BF16 扩散模型和约 47.97 GiB 的 BF16 文本编码器同时放进显存或物理内存，但可以尝试让 ComfyUI：

1. 从 NVMe 映射模型文件；
2. 文本/图片条件编码完成后卸载编码器；
3. 每次只把当前扩散层换入 GPU；
4. 把 H3 的 MLP 激活按 2048 token 分块计算；
5. 最后用分块 VAE 解码。

这个方案优化的是“峰值驻留量”，不是把 90 多 GiB 权重凭空变小。验收目标是**能够完成一条最低规格视频**，预计会非常慢，也不能在尚未实跑前承诺一定成功。

## 2. “未量化”到底指什么

默认文件：

```text
minimax_h3_ref2va_pruned_bf16.safetensors
qwen3vl_32b_minimax_h3_bf16.safetensors
minimax_h3_video_vae_fp16.safetensors
minimax_h3_audio_vae_fp32.safetensors
minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
```

- 扩散模型和文本/视觉编码器保持 BF16 数值精度；
- 视频 VAE 是官方 FP16，音频 VAE 是官方 FP32；
- `pruned` 是 ComfyUI 版 AdaLN 结构剪枝，不是低比特数值量化；
- 4 步 Turbo LoRA 是减少采样步数的蒸馏 LoRA，不是量化。

若连结构剪枝也不要，可把扩散模型换成 `minimax_h3_ref2va_bf16.safetensors`，但单文件约 61.73 GiB，当前配置的磁盘换页压力会明显增加。本章先使用 BF16 pruned 版。

早先在 WSL 中看到约 15 GiB，是 WSL 虚拟机的内存上限；ComfyUI Desktop 运行在 Windows `.venv` 中，应以 Windows 的约 32 GB 物理内存为准。

## 3. 为什么这套改法不降低计算精度

主链路：

```text
BF16 UNETLoader
  ↓
MiniMax H3 Low VRAM
  ├─ MLP 每次只算 2048 token
  └─ 禁止提前预取下一层
  ↓
4 步 Turbo LoRA / 采样
  ↓
VAEDecodeTiled
```

MLP 分块只是把同一个矩阵运算拆成多批执行，再按原顺序写回输出；它不修改模型权重，也不跳过 token。代价是重复调度和换入次数增加，所以更慢。

当前工作流没有默认启用 Sol-Attn。Sol-Attn 是稀疏注意力近似，虽然不是量化，但可能改变结果；而本机当前也没有 Triton，因此先用可比较的精确注意力建立基线。

## 4. 磁盘和 Windows 页面文件

准备条件：

- 模型文件至少预留 105 GB；
- 使用 NVMe SSD，机械硬盘不适合逐层流式换入；
- 建议另留 64 GB 页面文件和至少 30 GB 系统余量；
- 下载前确认模型、页面文件和系统盘不会共同挤满同一块磁盘。

设置页面文件：

1. Windows 搜索“查看高级系统设置”。
2. 打开“性能 → 设置 → 高级 → 虚拟内存 → 更改”。
3. 取消“自动管理”后选择 NVMe 所在盘。
4. 初始大小和最大值先都填 `65536 MB`。
5. 应用并重启 Windows。

本机当前只分配了 22 GB 页面文件，建议调整到 64 GB 后再开始。64 GB 是实验起点，不是通用保证。若磁盘空间不足，优先把 ComfyUI Shared models 放到另一块 NVMe，不要把系统盘塞满。

## 5. 安装唯一必需的低显存节点

本机已安装：

```text
ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-LowVRAM
```

其他电脑可在 Manager 中使用 Git URL 安装：

```text
https://github.com/lericogit/ComfyUI-MiniMaxH3-LowVRAM
```

该节点只对原生 MiniMax H3 模型的 MLP 做等价分块。本工作流不需要 ComfyUI-GGUF。

## 6. 一键断点续传下载

在 Windows CMD 进入本仓库，然后执行：

```bat
cd /d D:\path\to\comfyui-learning-hub
set HF_ENDPOINT=https://hf-mirror.com
scripts\download_minimax_h3_bf16_windows.cmd
```

脚本默认写入：

```text
C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\models
```

其他电脑可把模型根目录作为第一个参数：

```bat
scripts\download_minimax_h3_bf16_windows.cmd "D:\ComfyUI-Shared\models"
```

下载中断后重新执行同一命令即可。脚本使用 `curl.exe -C -` 从 `.download` 文件续传，完整下载后才改成正式文件名，因此 ComfyUI 不会误加载半个模型。

五个文件下载完成前不要运行工作流。

只想检查脚本和链接、不下载大文件时：

```bat
set H3_VERIFY_ONLY=1
scripts\download_minimax_h3_bf16_windows.cmd
set H3_VERIFY_ONLY=
```

## 7. Desktop 启动参数

打开：

```text
左上角菜单 → 打开仪表板 → 当前本地实例 → 启动参数
```

设置为：

```text
--enable-manager --novram --cpu-vae --disable-smart-memory --reserve-vram 1.0 --async-offload 1 --preview-method none
```

参数作用：

| 参数 | 作用 |
|---|---|
| `--novram` | 比 `--lowvram` 更激进地减少模型显存驻留 |
| `--cpu-vae` | 在 CPU 上执行 VAE，给扩散采样留显存 |
| `--disable-smart-memory` | 不把暂时不用的模型继续留在显存 |
| `--reserve-vram 1.0` | 给 Windows 桌面和 CUDA 临时缓冲留约 1 GB |
| `--async-offload 1` | 只用一条异步卸载流，降低并行换入峰值 |
| `--preview-method none` | 禁用采样预览，减少额外解码和显存占用 |

不要添加 `--disable-mmap`。当前方案依赖文件映射；禁用后会尝试把大权重完整读入 16 GB 内存。

保存后重启本地实例。

## 8. 不要再装错 Python 环境

Desktop 中存在两个 Python：

```text
standalone-env/python.exe          # Desktop 管理/安装环境，不含 Torch
ComfyUI/.venv/Scripts/python.exe   # 当前实例真正运行模型的环境
```

检查模型环境必须使用：

```bat
"C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI-RTX5060\ComfyUI\.venv\Scripts\python.exe" -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))"
```

安装自定义节点依赖时也应使用 `.venv\Scripts\python.exe -m pip`，不能使用 `standalone-env`。

## 9. 第一次运行必须保持这些参数

1. 导入 `ecommerce-minimax-h3-bf16-streaming-8gb.json`。
2. 在 `Picture 1` 重新选择一张商品图。
3. 检查五个模型加载节点都不是红色。
4. 保持：

   ```text
   9:16
   0.1 megapixels（约 256×416）
   5 秒
   一张参考图
   ref_image_size = match
   Turbo LoRA = true
   4 steps
   Low VRAM profile = minimum_vram
   block_prefetch = disable
   VAE tile = 256
   ```

5. 关闭游戏、浏览器视频、其他 AI 软件和占用 GPU 的窗口。
6. 打开任务管理器的 GPU、内存和磁盘页，再点击一次运行。
7. 不要因为磁盘长时间 100% 就立即终止；流式换入阶段可能主要消耗磁盘而不是 GPU。

输出目录：

```text
ComfyUI-Shared/output/ecommerce/video
```

## 10. 每个关键节点做什么

| 节点 | 当前设置 | 职责 |
|---|---|---|
| `UNETLoader` | Ref2VA pruned BF16 | 映射约 37.46 GiB 扩散权重 |
| `CLIPLoader` | Qwen3-VL 32B BF16 / minimax | 编码提示词和商品参考图 |
| `MiniMaxH3LowVRAM` | 2048 token、禁预取 | 限制每个 MLP 激活峰值，不改权重 |
| `MiniMaxH3ReferenceToVideo` | 单图、match、5 秒 | 生成参考条件和联合音视频 latent |
| `LoraLoaderModelOnly` | Ref2V Turbo BF16 | 把采样步数降到 4 步 |
| `SamplerCustomAdvanced` | 4 steps | 执行最耗时的逐层扩散计算 |
| `VAEDecodeTiled` | 256/64、32/8 | 分块解码视频，降低解码峰值 |
| `VAEDecodeAudio` | 官方 FP32 Audio VAE | 解码原生音频 |
| `CreateVideo` | 24 fps | 合并画面和声音 |
| `SaveVideo` | 本地目录 | 保存最终视频 |

## 11. OOM 或系统卡死时按顺序处理

不要同时乱改参数。按以下顺序逐项确认：

1. 确认启动日志真的出现 `novram`、CPU VAE 和异步卸载设置。
2. 确认没有误选 0.4/0.98 MP，也没有添加第二张参考图。
3. 确认页面文件已经生效，系统盘仍有 30 GB 以上空闲。
4. 将 Low VRAM 节点改成：

   ```text
   memory_profile = custom
   custom_chunk_tokens = 1024
   block_prefetch = disable
   ```

5. 若仍在 MLP OOM，最后试 `512` token；会更慢，但仍是等价分块。
6. 若在 VAE 解码 OOM，保持 `--cpu-vae`，把 VAE `tile_size` 从 256 降到 192。
7. 若 Windows 直接无响应，停止本次实验，确认 64 GB 页面文件已生效；仍失败再考虑升级到 64 GB 系统内存。反复强行换页可能导致应用和系统一起超时。

## 12. 跑通后的升级顺序

每次只改一项，并固定 seed：

1. `0.1 MP → 0.2 MP`；
2. MLP `512/1024 → 2048`，观察是否提速；
3. `block_prefetch=disable → keep`，观察峰值是否仍能承受；
4. 最后才增加第二张参考图；
5. 不建议 8GB 机器直接尝试 0.98 MP。

## 13. 验收与留痕

第一次完整运行记录：

```text
GPU / 显存：
系统内存：
页面文件：
模型所在磁盘：
分辨率与帧数：
MLP chunk tokens：
文本编码耗时：
每步采样耗时：
VAE 解码耗时：
总耗时：
峰值 GPU：
峰值内存：
是否完成：
错误原文：
```

只有本机完整生成过视频，才能把状态从“结构与环境已验证”改成“RTX 5060 8GB 实跑通过”。

## 14. 来源与边界

- [Comfy-Org MiniMax H3 R2V 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json)
- [Comfy-Org MiniMax H3 模型文件](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [ComfyUI MiniMax H3 原生节点](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py)
- [MiniMax H3 Low VRAM 等价 MLP 分块节点](https://github.com/lericogit/ComfyUI-MiniMaxH3-LowVRAM)
- [MiniMax H3 官方项目](https://github.com/MiniMax-AI/MiniMax-H3)

MiniMax H3 权重受其 Community License 约束。工作流结构校验和本机软件环境已经核实；在模型下载完成并实际产出视频前，不夸大为已验证性能。
