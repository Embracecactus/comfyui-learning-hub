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
Windows 页面文件：测试机配置为 80 GB；成功运行时当前占用约 1.3 GB
当前 C 盘可用：约 204 GiB
ComfyUI Python：ComfyUI/.venv/Scripts/python.exe
Python：3.13.12
PyTorch：2.12.1+cu130
CUDA runtime：13.0
```

这台电脑无法把约 37.46 GiB 的 BF16 扩散模型和约 47.97 GiB 的 BF16 文本编码器同时放进显存或物理内存。实测可行的办法不是把整份权重换进页面文件，而是让 ComfyUI：

1. 从 NVMe 映射模型文件；
2. 文本/图片条件编码完成后卸载编码器；
3. 每次只把当前扩散层换入 GPU；
4. 把 H3 的 MLP 激活按 2048 token 分块计算；
5. 最后用分块 VAE 解码。

这个方案优化的是“同一时刻驻留在内存/显存中的权重”，不是把 90 多 GiB 权重凭空变小。2026-09-01 已在上述机器上以原始 BF16/FP16/FP32 权重完成一条 `256×416、5.167 秒、4 步` 的带声音 MP4，总耗时 `261.72 秒`。这证明最低规格链路可运行，但不等于 8 GB 显存可以直接制作高清长视频。

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

若连结构剪枝也不要，可把扩散模型换成 `minimax_h3_ref2va_bf16.safetensors`，但单文件约 61.73 GiB，磁盘 I/O、首次调度和总运行时间都会明显增加。本章先使用 BF16 pruned 版。

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

## 4. 磁盘、内存和 Windows 页面文件

准备条件：

- 模型文件至少预留 105 GB；
- 使用 NVMe SSD，机械硬盘不适合逐层流式换入；
- 运行前关闭游戏、其他 AI 软件和不必要的浏览器页面；
- 下载前确认模型、输出和系统盘不会共同挤满同一块磁盘。

### 4.1 先纠正一个容易踩的坑

本工作流的主方案**不要求把 90 多 GiB 权重全部塞进页面文件**。`DynamicVRAM + fast-disk` 会把大权重保留为磁盘文件切片，需要某一层时才读取。测试机虽然曾为旧方案配置 80 GB 页面文件，但成功运行结束时 `CurrentUsage` 约为 `1282 MB`。

Windows 的 `PeakUsage` 会保留本次开机以来的历史峰值。本机曾用错误的 eager/pread 方案冲到约 42 GB，因此成功后仍能看到这个旧峰值；它不能用来证明成功工作流消耗了 42 GB 页面文件。

查看当前值：

```powershell
Get-CimInstance Win32_PageFileUsage |
  Select-Object Name, AllocatedBaseSize, CurrentUsage, PeakUsage
```

### 4.2 页面文件怎么设

优先保留“系统管理的大小”。若系统提交内存不足，再把页面文件放在空间充足的 NVMe 上作为安全网；不要一开始就把 80 GB 当成必需条件。

> 主方案用户可以跳过下面的固定 80 GB 设置。以下步骤只用于复现本机排查旧加载路径时的实验环境。

设置页面文件：

1. Windows 搜索“查看高级系统设置”。
2. 打开“性能 → 设置 → 高级 → 虚拟内存 → 更改”。
3. 取消“自动管理”后选择 NVMe 所在盘。
4. 初始大小和最大值先都填 `81920 MB`。
5. 应用并重启 Windows。

只有明确需要复现实验配置时，才在仓库根目录的管理员 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\set_windows_pagefile_80gb.ps1
```

80 GB 不是推荐起步值，也不是 DynamicVRAM 的运行前提。若当前提交量持续上涨几十 GB，通常说明仍在使用 `--disable-mmap`/pread 等整文件加载路径，应先修正启动参数，而不是继续扩大页面文件。

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

下载中断后重新执行同一命令即可。脚本使用 `curl.exe -C -` 从 `.download` 文件续传，并核对五个官方文件的字节数；大小正确后才改成正式文件名。已有正式文件也会重新检查，避免把中断文件或错误页面误当成模型。

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

RTX 50 系 Windows 的实测稳定参数为：

```text
--enable-manager --enable-manager-legacy-ui --enable-dynamic-vram --fast-disk --disable-smart-memory --reserve-vram 1.0 --vram-headroom 0.5 --disable-async-offload --disable-pinned-memory --preview-method none
```

参数作用：

| 参数 | 作用 |
|---|---|
| `--enable-dynamic-vram` | 将大模型权重保留为文件切片，按当前模块换入，而不是一次载入整份 48 GiB 编码器 |
| `--fast-disk` | 模型在 NVMe 时直接从文件切片读取，避免额外建立巨大的内存缓存 |
| `--disable-smart-memory` | 不把暂时不用的模型继续留在显存 |
| `--reserve-vram 1.0` | 给 Windows 桌面和 CUDA 临时缓冲留约 1 GB |
| `--vram-headroom 0.5` | DynamicVRAM 再留约 0.5 GB 调度余量 |
| `--disable-async-offload` | 避开 Windows/Blackwell 上异步文件读取与 HostBuffer 崩溃路径 |
| `--disable-pinned-memory` | 避开 Windows/Blackwell 的 pinned host memory 原生崩溃路径 |
| `--preview-method none` | 禁用采样预览，减少额外解码和显存占用 |

也可以在仓库根目录直接运行已经固化的启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_comfyui_h3_8gb.ps1
```

脚本会自动查找 Desktop 的共享模型 YAML，停止同一实例的旧 `main.py`、检查 8188 端口、使用正确的 Desktop `.venv` 启动，并同时核对目标进程和 `/system_stats` 中的 `--enable-dynamic-vram --fast-disk`。

本地实例不叫 `ComfyUI-RTX5060` 时传入自己的实例目录名：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_comfyui_h3_8gb.ps1 `
  -InstanceName "你的实例目录名"
```

电脑里有多个 Desktop 模型路径 YAML、无法自动判断时，明确传入当前实例的文件：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_comfyui_h3_8gb.ps1 `
  -ExtraModelsConfig "$env:APPDATA\Comfy Desktop\instance-model-paths\inst-你的实例编号.yaml"
```

### 7.1 这四个参数不要加

| 不要添加 | 原因 |
|---|---|
| `--novram` | 会绕开这次依赖的 DynamicVRAM 文件切片路径 |
| `--disable-dynamic-vram` | 会直接关闭逐模块流式加载 |
| `--disable-mmap` | 进入 eager/pread 整文件加载，48 GiB Qwen 容易把 RAM/页面文件吃满 |
| `--cpu-vae` | H3 Video VAE 权重为 FP16，而 CPU VAE 输入会选 FP32；本机已复现 `float != Half` 错误 |

确认实际进程参数：

```powershell
(Invoke-RestMethod http://127.0.0.1:8188/system_stats).system.argv
```

### 7.2 `pread` 补丁只作为兼容回退

仓库仍保留针对本机 ComfyUI v0.33.4 的 Windows 非 mmap 回退补丁，主要用于记录历史故障。确实需要时先检查上下文是否匹配：

```bat
cd /d C:\path\to\ComfyUI
git apply --check C:\path\to\comfyui-learning-hub\patches\comfyui-windows-large-safetensors-pread.patch
git apply C:\path\to\comfyui-learning-hub\patches\comfyui-windows-large-safetensors-pread.patch
```

若 `--check` 失败，不要强行应用；先用 `git apply --reverse --check <补丁路径>` 判断是否已经打过补丁。该补丁让 `--disable-mmap` 使用 safetensors `backend="pread"`，并直接读取 JSON 头部，避免 `safe_open()` 再创建 Windows 文件映射。但 `load_file()` 仍会把整份权重读入内存，所以它不是 32 GB 内存运行 H3 BF16 的推荐路径。本章成功运行时补丁虽然已安装，启动参数没有启用 `--disable-mmap`，因此走的是 DynamicVRAM。

更新 ComfyUI 后先检查补丁是否仍需要，不要不加判断地重复应用。

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

1. 用 `/system_stats` 确认进程含 `--enable-dynamic-vram --fast-disk`，且不含上一节列出的四个禁用参数。
2. 确认没有误选 0.4/0.98 MP，也没有添加第二张参考图。
3. 确认模型位于 NVMe，磁盘仍有至少 30 GB 空闲。
4. 将 Low VRAM 节点改成：

   ```text
   memory_profile = custom
   custom_chunk_tokens = 1024
   block_prefetch = disable
   ```

5. 若仍在 MLP OOM，最后试 `512` token；会更慢，但仍是等价分块。
6. 若在 VAE 解码 OOM，把 Video VAE `tile_size` 从 256 降到 192；不要加 `--cpu-vae`。
7. 若日志打印 `49118MB Staged` 后，页面文件当前占用仍很低，这是文件切片已建立的正常现象，不等于 49 GB 已进入 RAM。
8. 若页面文件当前占用持续上涨几十 GB，停止任务并检查是否仍有 `--disable-mmap`、`--disable-dynamic-vram` 或旧 Desktop 启动参数。
9. 16 GB 物理内存尚未在本项目实测通过；本次成功机器实际为 32 GB。不能把 WSL 显示的 15/16 GB 误当成 Windows 物理内存，也不应承诺 16 GB 必然可跑。

## 12. 跑通后的升级顺序

每次只改一项，并固定 seed：

1. `0.1 MP → 0.2 MP`；
2. MLP `512/1024 → 2048`，观察是否提速；
3. `block_prefetch=disable → keep`，观察峰值是否仍能承受；
4. 最后才增加第二张参考图；
5. 不建议 8GB 机器直接尝试 0.98 MP。

## 13. 验收与留痕

### 13.1 失败记录：为什么以前看起来需要巨大内存（2026-08-31）

- MCP：`Comfy-Org/comfy-mcp 0.10.0`，`comfy-cli 1.19.0`，已注册到 Codex；
- 工作流成功转换为 26 个 API 节点并通过服务端校验；
- Prompt ID：`eb6b1c62-c444-4cd9-a5db-4cd04d7735ca`；
- 失败阶段：两个 VAE 被识别后，`CLIPLoader` 加载 `qwen3vl_32b_minimax_h3_bf16.safetensors`；
- 错误：`Windows fatal exception: access violation`，Windows WER 为 `torch_cpu.dll / c0000005`；
- 堆栈：`torch/storage.py:471 → comfy/utils.py:136 → comfy/sd.py:1534 → nodes.py:1031`；
- 当时页面文件：22 GB；分辨率尚未进入采样，因此降分辨率不能修复这个加载崩溃；
- 结论：这个失败来自错误的整文件加载路线；降分辨率无法修复，因为当时尚未进入采样。

### 13.2 中间失败：CPU VAE 精度不匹配（2026-09-01）

- Prompt ID：`2dd862ef-c444-4d36-aeba-8b3b8e25b8dc`；
- DynamicVRAM 已让 4 步采样完整结束，页面文件当前占用约 1.3 GB；
- Video VAE 解码时报错：`expected m1 and m2 to have the same dtype, float != Half`；
- 原因：`--cpu-vae` 选择 FP32 输入，而官方 Video VAE 是 FP16；
- 修复：删除 `--cpu-vae`，让 Video VAE 和 Audio VAE 分别按各自 FP16/FP32 精度在 DynamicVRAM 路径运行。

### 13.3 RTX 5060 8 GB 完整成功记录（2026-09-01）

| 项目 | 实测值 |
|---|---|
| Prompt ID | `6a28753b-00eb-40e3-ad2f-3fce09db5dac` |
| GPU / 内存 | RTX 5060 8 GB / Windows 32 GB |
| 数值精度 | H3 与 Qwen BF16、Video VAE FP16、Audio VAE FP32；无量化 |
| 输入 | 单张透明底琥珀精华瓶 |
| 输出 | H.264 `256×416`、24 fps、124 帧；AAC 32 kHz 双声道 |
| 时长 / 文件大小 | `5.167 秒` / `530795 字节` |
| 采样 | 4 步，约 `54.7 秒` |
| 总耗时 | `261.72 秒` |
| DynamicVRAM 日志 | Qwen `49118MB Staged`；H3 `38444MB Staged`；Video VAE `4965MB Staged`；Audio VAE `576MB Staged` |
| 页面文件 | 成功运行后 `CurrentUsage ≈ 1282 MB`；约 42 GB 的 `PeakUsage` 是此前失败遗留的本次开机历史峰值 |
| 输出文件 | `ComfyUI-Shared\\output\\ecommerce\\video\\minimax-h3-bf16-streaming-8gb_00001_.mp4` |
| 结果 | 完整生成音视频，服务端状态 `completed` |

测试机的 Desktop `installations.json` 和 Windows-native comfy-cli `default_launch_extras` 已同步为第 7 节参数；Desktop 原配置备份为 `installations.json.bak-before-h3-dynamic`。下载脚本也已在这五个现有文件上逐一核对字节数通过。

画面验收：首、中、尾帧都保留了琥珀玻璃瓶、滴管和主体轮廓，参考图确实生效；低分辨率下标签会在中途生成伪文字，装饰球存在纹理噪点，因此当前结果用于验证链路和资源策略，不作为最终商用质量。

其他电脑复测时填写：

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

只有完整产出可播放的音视频，并记录上述信息，才算“实跑通过”；只看到模型加载或采样进度不算。

## 14. 来源与边界

- [Comfy-Org MiniMax H3 R2V 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json)
- [Comfy-Org MiniMax H3 模型文件](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [ComfyUI MiniMax H3 原生节点](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py)
- [ComfyUI #15424：Windows 大型 CLIP safetensors 访问冲突及 pread 绕过](https://github.com/Comfy-Org/ComfyUI/issues/15424)
- [ComfyUI #15337：MiniMax H3 在 Windows/Blackwell 上禁用异步卸载和 pinned memory 的验证](https://github.com/Comfy-Org/ComfyUI/issues/15337)
- [Comfy-Org/comfy-mcp：本地 MCP 服务](https://github.com/Comfy-Org/comfy-mcp)
- [MiniMax H3 Low VRAM 等价 MLP 分块节点](https://github.com/lericogit/ComfyUI-MiniMaxH3-LowVRAM)
- [MiniMax H3 官方项目](https://github.com/MiniMax-AI/MiniMax-H3)

MiniMax H3 权重受其 Community License 约束。本章只确认上述 RTX 5060 8 GB + Windows 32 GB 的最低规格 BF16 工作流实跑通过；没有验证 16 GB 内存、高清输出、长视频或商用品质。
