# MiniMax H3 量化模型：通用低显存自适应工作流

这一章解决的不是“让某一张 5060 能跑”，而是先用检测器按显卡算子能力、显存、系统内存和磁盘条件给出保守候选，再由用户导入对应的 NVFP4 或 INT8 工作流。工作流运行后，MLP 窗口与预取才会继续动态调整。

配套文件：

- [NVFP4 量化低显存工作流](workflows/ecommerce-minimax-h3-quantized-nvfp4-low-vram.json)
- [INT8 量化低显存工作流](workflows/ecommerce-minimax-h3-quantized-int8-low-vram.json)
- [通用硬件检测器](../../scripts/detect_minimax_h3_quant_profile.py)
- [Windows 断点续传下载脚本](../../scripts/download_minimax_h3_quantized_windows.cmd)
- [本项目自带的自适应内存节点](../../custom_nodes/comfyui_adaptive_memory)
- [恢复 Windows 系统管理分页文件脚本](../../scripts/restore_windows_pagefile_system_managed.ps1)

旧的 [BF16 磁盘流式工作流](workflows/ecommerce-minimax-h3-bf16-streaming-8gb.json)只保留为已经跑通的历史基线，不再是小白首选。测试机上的两份 BF16 大权重已经为量化路线腾出磁盘；要重跑旧工作流必须重新下载。

## 1. 先说结论

量化只解决“权重有多大”，不能单独解决低显存运行。完整方案有四层：

1. 按 GPU 原生算子能力选择 NVFP4 或 INT8 权重；
2. 按实时空闲显存计算 H3 MLP 每次处理多少 token；
3. 在 Qwen 编码、DiT 采样、VAE 解码三个阶段之间定向卸载已经用完的模型；
4. 从 `0.1 MP、5 秒、4 步` 起跑，再逐项提高分辨率。

本项目没有把某个显卡名称写进节点。`MiniMaxH3AdaptiveMemory` 读取实际剩余显存和内存，并用 H3 的真实维度估算 SwiGLU 临时张量预算。它只约束 MLP 窗口，不是整个 H3 的显存上限；attention、packed `h`、CUDA workspace 和 VAE 仍要通过真实运行验收。

## 2. 为什么“模型文件只有 15GB”仍可能 OOM

一次生成会遇到三类内存：

| 类型 | 例子 | 量化是否直接减少 |
|---|---|---|
| 权重 | Qwen、H3 DiT、VAE 参数 | 是 |
| 激活 | attention、MLP 中间张量、latent | 否，通常仍是 FP16/BF16 |
| 调度缓冲 | CUDA workspace、预取块、视频解码 tile | 否 |

所以不能用模型文件大小直接推断显存需求。自适应节点会把 H3 MLP 的 token 维度拆成多个窗口；数学运算、权重和 token 都没有被省略，只是牺牲一部分速度换取更低峰值。

## 3. 先让检测器推荐模型，不要猜

ComfyUI Desktop 必须使用当前实例自己的 Python：

```text
ComfyUI/.venv/Scripts/python.exe
```

`standalone-env/python.exe` 是 Desktop 的管理环境，不是模型运行环境。

在仓库根目录执行，实例名按自己的电脑修改：

```bat
"C:\Users\你的用户名\AppData\Local\Comfy-Desktop\ComfyUI-Installs\你的实例\ComfyUI\.venv\Scripts\python.exe" scripts\detect_minimax_h3_quant_profile.py
```

上面的用户名与实例目录都是占位符，不能原样复制。检测器只打印候选，不会自动替你导入工作流或下载模型。

检测器只依据实际硬件信息：

- NVIDIA compute capability；
- CUDA/PyTorch 运行时；
- 显存大小；
- Windows 物理内存；
- `comfy-kitchen` 的 CUDA backend 是否提供实际加载路径调用的原生算子；
- 任一已启用 backend 是否提供必要的嵌入表回退算子。

只有 CUDA 版本、SM 下限、已启用的 `comfy-kitchen` CUDA backend 和所需 capability 同时通过，检测器才输出 `supported=true`。SM 7.0 不会再被归入 SM 7.5 的 INT8 候选。

当前保守矩阵：

| 设备能力 | 文本/视觉编码器 | 工作流 | 状态 |
|---|---|---|---|
| NVIDIA SM 10 或更高 | NVFP4 AWQ | `quantized-nvfp4-low-vram` | 推荐候选 |
| NVIDIA SM 7.5、8.x、8.9 | INT8 ConvRot | `quantized-int8-low-vram` | 必须短片实测 |
| NVIDIA SM 6.x 或更早 | 无 | 无 | 当前不承诺 |
| AMD gfx11/gfx12、部分 CDNA | INT8 ConvRot | 实验候选 | 需 ROCm、Triton 3.7+ 和完整验证 |
| Intel/CPU | 无 | 无 | 当前不推荐本地 H3 |

NVFP4 不是“所有 NVIDIA 都更省”的通用格式。硬件没有原生 NVFP4 算子时，强行选择它可能报错或走低效回退。

这里没有根据文件名中的 `AWQ` 猜算子。对官方 safetensors 文件头和当前 ComfyUI 加载路径的核对结果是：

- NVFP4 Qwen 线性层记录为 `format=nvfp4, full_precision_matrix_mult=true`，当前路径需要 CUDA `dequantize_nvfp4`；
- 同一文件的嵌入表记录为 `int8_tensorwise`，需要任一已启用 backend 提供 `dequantize_int8_embedding`；
- INT8 DiT 和 INT8 Qwen 线性层记录为 `int8_tensorwise + convrot=true`，需要 CUDA `int8_linear`；
- 因此检测器不会仅因存在名字相似的 `gemv_awq_w4a16` 就把 NVFP4 路线标为可用。

如果显卡属于 SM 10+，但当前安装缺少 NVFP4 解码或嵌入回退能力，而 CUDA `int8_linear` 可用，检测器会自动改推 INT8 工作流。这样牺牲约 10.67 GiB 磁盘占用换取可运行性，不会把“NVFP4 不可用”误报成“整台机器不可用”。

## 4. 两套量化模型有什么区别

两套工作流共用：

```text
diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors
vae/minimax_h3_video_vae_fp16.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors
loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
```

只替换 Qwen3-VL 文本/视觉编码器：

| 档位 | 文件 | 文件大小约 | 完整五文件约 |
|---|---|---:|---:|
| NVFP4 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.61 GiB | 41.38 GiB |
| INT8 | `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 25.28 GiB | 52.04 GiB |

扩散模型约 19.53 GiB。视频 VAE、音频 VAE 和 Turbo LoRA 保留官方精度。

官方 Hugging Face LFS 身份如下；`x-linked-etag` 就是文件 SHA-256：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 20,970,379,616 | `9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15,687,142,551 | `35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6` |
| `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 27,141,342,152 | `bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923` |
| `minimax_h3_video_vae_fp16.safetensors` | 5,207,808,496 | `7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522` |
| `minimax_h3_audio_vae_fp32.safetensors` | 605,254,808 | `8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48` |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | 1,956,193,000 | `5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c` |

下载脚本先做逐文件字节数闸门。需要进一步人工校验时，在 PowerShell 执行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath "C:\你的\ComfyUI-Shared\models\对应目录\文件名.safetensors"
```

## 5. 下载：支持断点续传和大小校验

在 Windows CMD 的仓库根目录执行：

Desktop 默认共享模型目录会通过 `%LOCALAPPDATA%` 自动定位，不绑定用户名。下面显式传入第一个参数，是为了让非默认安装位置的小白看清模型会写到哪里；路径请换成自己的实际目录。

```bat
set HF_ENDPOINT=https://hf-mirror.com
scripts\download_minimax_h3_quantized_windows.cmd "C:\你的\ComfyUI-Shared\models" nvfp4
```

检测器推荐 INT8 时，把最后一个参数改为：

```bat
scripts\download_minimax_h3_quantized_windows.cmd "C:\你的\ComfyUI-Shared\models" int8
```

脚本行为：

- 使用 `curl.exe -C -` 从 `.download` 文件续传；
- 每次断流都新建一个 curl 进程并重新读取当前文件长度，避免内部 retry 重复追加旧 Range；
- 每个文件默认允许 100 次外层重连；可在运行前设置 `H3_MAX_DOWNLOAD_ATTEMPTS` 调整，但不建议并发启动第二个下载器；
- 只有 curl 退出码严格等于 `0` 才进入完成校验，外部中止返回的负退出码不会被误判成功；
- 每个目标文件都有单写者锁；不要同时打开两个下载窗口写同一模型；
- 网络中断后重新运行同一命令即可；如果提示 stale lock，先确认任务管理器中没有对应 `curl.exe` 再删除锁目录；
- 从 WSL 或自动化工具启动 Windows 批处理时，外层会话退出不一定表示子 `curl.exe` 已退出。不要绕过现有锁直接启动另一种下载器；先在任务管理器确认 `curl.exe` 消失，并观察 `.download` 文件长度不再变化；
- 五个文件逐一核对官方字节数；
- 大小完全正确才改成正式 `.safetensors` 文件名；
- 已存在且大小正确的 VAE/LoRA 会跳过。

只检查下载地址，不下载模型：

```bat
set H3_VERIFY_ONLY=1
scripts\download_minimax_h3_quantized_windows.cmd "C:\你的\ComfyUI-Shared\models" nvfp4
set H3_VERIFY_ONLY=
```

## 6. 安装本项目自己的自适应节点

将仓库里的整个目录：

```text
custom_nodes/comfyui_adaptive_memory
```

复制到当前实例：

```text
ComfyUI/custom_nodes/comfyui_adaptive_memory
```

然后重启 ComfyUI。节点搜索中应能看到：

```text
MiniMax H3 Adaptive Memory
H3 Release Encoders After Conditioning
H3 Release DiT After Sampling
H3 VAE Decode Tiled and Release
H3 VAE Decode Audio and Release
H3 Reference Video Frames (24 FPS)
```

最后一个节点供[第 10 章的对标视频工作流](10-映海爆款带货视频本地复刻.md)使用：它根据源视频真实帧率重采样到 H3 的 24 fps 时间轴，并把帧数对齐为 `17n + 5`。单商品图工作流不会经过它。

这套工作流不再依赖外部 `ComfyUI-MiniMaxH3-LowVRAM`。旧节点可以保留给旧工作流，但不要把两个 H3 MLP 分块节点串在一起，否则会被新节点明确拒绝。

## 7. 自研优化一：实时显存分块

`MiniMaxH3AdaptiveMemory` 不读取“5060”“4090”之类的型号表。第一次进入每个扩散 forward 时，它会：

1. 读取当前 CUDA 空闲显存；
2. 留出 `reserve_vram_mb` 给 attention、采样器、Windows 桌面和 CUDA workspace；
3. 根据 H3 的 `hidden=5376`、`ffn=14336` 和当前激活精度估算每个 token 的 SwiGLU 临时内存；
4. 在 `min_chunk_tokens` 与 `max_chunk_tokens` 之间选出本次窗口；
5. 同一个 forward 的 50 个 H3 block 共用该决定，避免每层来回抖动。

四个 profile：

| profile | 目标 | 典型用途 |
|---|---|---|
| `auto_stable` | 峰值优先 | 6–8GB 参数设计目标；每种机器仍需实跑 |
| `auto_balanced` | 显存与速度平衡 | 12–16GB 参数设计目标 |
| `auto_speed` | 尽量放大窗口 | 24GB 及以上参数设计目标 |
| `manual` | 固定窗口 | 对比测试和排错 |

量化权重影响模型驻留；自适应分块影响激活峰值。两者解决的是不同问题。

## 8. 自研优化二：三阶段定向卸载

工作流现在按以下顺序建立强依赖：

```text
Qwen + 视频/音频 VAE 编码参考素材
  ↓ H3ReleaseAfterConditioning
只保留 CONDITIONING + LATENT
  ↓
H3 DiT 4 步采样
  ↓ H3ReleaseAfterSampling
只保留采样后的 LATENT
  ↓
视频 VAE 分块解码后卸载
  ↓ released 布尔屏障
音频 VAE 解码后卸载
```

两个释放节点不是“无连接的清缓存按钮”。它们把真正的条件或 latent 作为输入输出，因此 ComfyUI 必须先完成上一个阶段，才能卸载该阶段的模型。

两个阶段释放节点还被标记为不可复用缓存的副作用节点。否则第二次用相同输入排队时，ComfyUI 可能复用上次输出而跳过卸载动作。

视频解码节点还会在释放动作成功返回后输出一个很小的 `released=true`，音频解码节点必须收到它才会运行；若关闭视频 `release`，音频节点会明确报错。这个屏障不传整批视频帧，能保证“视频解码与释放调用在音频解码前完成”。Windows 驱动、mmap 与页缓存的实际驻留峰值仍以日志和监测为准。

释放使用 ComfyUI 的定向 `unload_model_and_clones()`，不会粗暴清空所有全局模型。小白不要从这些模型输出再接绕过释放屏障的并行支路；本工作流中的 VAE 只会在采样结束后按依赖重新加载用于解码。额外分支可能增加重复 I/O 和峰值，必须重新验收。

## 9. 自研优化三：预取只在真的可用时开启

旧工作流把 `block_prefetch=keep` 写死，但如果启动参数包含 `--disable-async-offload`，ComfyUI 的异步流数量就是 0，“保留预取”实际上不会创建预取队列。

新节点的 `prefetch_mode=auto` 会同时检查：

- 至少有一个异步卸载流；
- 预留显存之上仍有足够余量；
- 系统可用内存足以承受提前读取下一 block。

任何一项不满足就关闭预取，并在日志中写明原因。它用于降低显存和页面文件抖动风险，但没有测量磁盘吞吐，也不代替真实 A/B 验收。

## 10. 模型格式先看 GPU/Native ops，I/O 模式再看系统内存

所有档位都保留：

```text
--enable-dynamic-vram --disable-smart-memory --reserve-vram 1.0 --vram-headroom 0.5 --disable-pinned-memory --preview-method none
```

不想手工判断时，在管理员权限不必要的普通 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_comfyui_h3_quantized.ps1 `
  -InstanceName "你的实例目录名" -ModelProfile nvfp4
```

请在仓库根目录执行。脚本默认会停止该实例现有的 ComfyUI 进程再按新参数启动；不会停止独立的模型下载器。

脚本会按物理内存选择 `RamAssisted` 或 `DiskStreaming`，默认使用稳定的同步卸载档。INT8 工作流把 `-ModelProfile` 改为 `int8`。

### 10.1 稳定首跑

在上面的参数后添加：

```text
--disable-async-offload
```

此时自适应节点会自动关闭 block prefetch。先证明完整短片可运行，再做速度 A/B 测试。

### 10.2 物理内存放不下最大单阶段模型

再添加：

```text
--fast-disk
```

自动判断不是“总模型文件多大”，而是同时检查总物理内存和当前可用内存。脚本采用的保守启发式为：总内存至少是最大阶段 `+8 GiB`，当前可用内存至少是最大阶段 `+4 GiB`；这不是已经证明的安全线。

| 组合 | 最大阶段约 | I/O 候选门槛 |
|---|---:|---:|
| NVFP4 Qwen + INT8 DiT | 19.53 GiB | 总 RAM ≥27.53 GiB 且当前可用 ≥23.53 GiB，才候选内存辅助 |
| INT8 Qwen + INT8 DiT | 25.28 GiB | 总 RAM ≥33.28 GiB 且当前可用 ≥29.28 GiB，才候选内存辅助 |

16GB 内存只能列为磁盘流式实验候选。32GB 也不能仅凭总容量断言可用内存辅助：浏览器、桌面程序和页缓存占用较高时，Auto 会退回 `--fast-disk`。

### 10.3 速度实验，不是默认值

稳定首跑成功后，可把 `--disable-async-offload` 替换为：

```text
--async-offload 1
```

节点会在余量允许时做一 block ahead 预取。Windows、驱动、PyTorch 与显卡组合差异很大；若出现原生崩溃、显存尖峰或磁盘更慢，立即退回稳定首跑参数。

不要添加：

| 参数 | 原因 |
|---|---|
| `--novram` | 会绕开当前依赖的 DynamicVRAM 路径 |
| `--disable-dynamic-vram` | 关闭逐模块动态加载 |
| `--disable-mmap` | 容易把大文件转成整文件加载，推高 RAM/分页文件 |
| `--cpu-vae` | H3 Video VAE 精度路径可能出现 `float != Half` |

## 11. Windows 分页文件：恢复系统管理

分页文件是内存不足时的安全网，不是 H3 的“额外高速内存”。固定 80GB 会长期占磁盘空间，也可能掩盖错误的整文件加载路径。

推荐在管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\restore_windows_pagefile_system_managed.ps1
```

然后重启 Windows。只有重启后，旧的固定页面文件大小才会真正释放并由系统重新管理。

查看状态：

```powershell
Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile
Get-CimInstance Win32_PageFileUsage |
  Select-Object Name, AllocatedBaseSize, CurrentUsage, PeakUsage
```

`AutomaticManagedPagefile` 应为 `True`。`PeakUsage` 是本次开机以来的历史峰值，不能单独证明当前工作流正在使用同样多的分页文件。

## 12. 第一次运行

1. 重启 ComfyUI，使新模型和自定义节点生效。
2. 导入检测器推荐的 NVFP4 或 INT8 工作流。
3. 在 `Picture 1` 重新选择一张商品图。
4. 确认所有模型节点和五个自研节点都不是红色。
5. 保持以下首跑设置：

   ```text
   9:16
   0.1 megapixels（约 256×416）
   5 秒
   一张参考图
   ref_image_size = match
   Turbo LoRA = true
   4 steps
   Adaptive profile = auto_stable
   reserve_vram_mb = 1024
   prefetch_mode = auto
   H3 两个阶段 release = true
   Video VAE tile = 256
   ```

6. 关闭其他 AI 软件、游戏和浏览器视频。
7. 点击一次运行；不要并发排多个 H3 任务。

输出目录：

```text
ComfyUI-Shared/output/ecommerce/video
```

## 13. 每个关键节点做什么

| 节点 | 职责 |
|---|---|
| `UNETLoader` | 加载 Ref2VA pruned INT8 ConvRot 扩散模型 |
| `CLIPLoader` | 加载检测器选出的 NVFP4 或 INT8 Qwen3-VL |
| `MiniMaxH3AdaptiveMemory` | 依据实时显存限制 MLP 激活窗口，并条件控制预取 |
| `MiniMaxH3ReferenceToVideo` | 把提示词、商品图、视频/音频参考编码为条件与联合 latent |
| `H3ReleaseAfterConditioning` | 条件编码完成后定向卸载 Qwen 和参考 VAE |
| `LoraLoaderModelOnly` | 应用官方 4 步 Turbo LoRA |
| `SamplerCustomAdvanced` | 执行四步 H3 DiT 采样 |
| `H3ReleaseAfterSampling` | 采样完成后、VAE 解码前卸载 DiT 及其 clones |
| `H3VAEDecodeTiledRelease` | 分块解码视频，卸载视频 VAE 后发出 `released` 屏障 |
| `H3VAEDecodeAudioRelease` | 等待视频释放屏障，再解码音频并卸载音频 VAE |
| `CreateVideo` / `SaveVideo` | 合并并保存本地 MP4 |

## 14. OOM、内存爆满或磁盘 100% 怎么处理

一次只改一项：

1. 确认没有误选第二张参考图，且 `ref_image_size=match`。
2. 确认是 `0.1 MP、5 秒、4 步`。
3. 确认两个阶段释放节点都是 `release=true`。
4. 保持 `profile=auto_stable`，把 `max_chunk_tokens` 从 4096 降到 2048。
5. MLP 仍 OOM 时，把 `min_chunk_tokens` 降到 512、`max_chunk_tokens` 降到 1024。
6. Video VAE OOM 时，把 `tile_size=256` 降到 192；不要添加 `--cpu-vae`。
7. 系统内存不足时添加 `--fast-disk`；磁盘会更忙，但避免整阶段塞进物理内存。
8. 内存足够却长期磁盘 100% 时，关闭任务，去掉 `--fast-disk` 做同规格 A/B；不要靠扩大固定分页文件解决。
9. 若 `prefetch=keep` 但日志写着 async stream 为 0，说明预取根本没有生效；改回 `auto`。
10. 页面文件持续上涨几十 GB 时，检查是否误加 `--disable-mmap` 或关闭了 DynamicVRAM。

模型下载期间磁盘占用高与推理阶段磁盘抖动不是同一个问题，先看占用进程和 ComfyUI 日志再判断。

## 15. 跑通后的升级顺序

固定 seed，每次只改一项：

1. `0.1 MP → 0.2 MP`；
2. `auto_stable → auto_balanced`；
3. 稳定参数下比较 `--disable-async-offload` 与 `--async-offload 1`；
4. 再增加第二张参考图；
5. 最后才尝试 0.4MP 以上或更长视频。

不要用“成功加载模型”当验收。必须完整得到可播放、有画面和声音的 MP4。

## 16. 复测留痕模板

```text
日期：
ComfyUI / PyTorch / CUDA 或 ROCm：
GPU / compute capability / 显存：
系统内存 / 分页文件策略：
量化组合：NVFP4 / INT8
启动参数：
自适应 profile / 实际日志 chunk：
prefetch 日志及原因：
分辨率 / 帧数 / 步数：
Qwen 编码耗时：
每步采样耗时：
VAE 解码耗时：
总耗时：
峰值显存 / 内存 / 磁盘：
输出文件：
是否完成：
错误原文：
```

## 17. 当前验证边界

已确认：

- Windows 32GB + NVIDIA 8GB 的旧 BF16 工作流完整生成过 `256×416、124 帧、4 步` 音视频，证明原生 H3 链路可运行；
- 当前 ComfyUI `.venv` 能导入本项目五个新节点；
- 自适应策略与硬件选择器已有自动化测试；
- 三套派生工作流通过节点/链接结构校验；
- 本机 NVFP4 组合的五个模型已完整下载，逐文件 SHA-256 与官方 LFS 身份一致；
- 服务端预检返回 `valid=true`、`0 errors`、`0 warnings`；
- RTX 5060 8GB + Windows 32GB 已用 NVFP4 工作流完整生成 `256×416、5.167 秒、24 fps、4 步` 的 H.264 + AAC 短片，服务端总执行 `43.96 秒`；
- 实跑日志显示 MLP 窗口会按现场资源从 `4096` 自动缩到 `1792` token，并依次释放 Qwen/参考 VAE、DiT、视频 VAE、音频 VAE；稳定首跑禁用了异步流，所以预取按设计关闭。

这证明上述一台机器的 **NVFP4 低分辨率首跑规格** 已实跑通过，不代表所有 8GB 显卡都能跑。当前开机周期仍保留旧的 `81920 MB` 分页文件分配，因此也不能据此声称“8GB 显存 + 32GB 内存且无需分页文件”。Windows 重启并由系统重新管理分页文件后、INT8 档、AMD 和其他 NVIDIA 架构仍要分别复测。

本次输出位于测试机：

```text
C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output\ecommerce\video\minimax-h3-quantized-nvfp4-low-vram_00001_.mp4
```

画面和声音均可解码；0.1 MP 是“跑通链路”规格，样片仍有标签文字变形和运动拖影，不能当作最终电商质量基准。

本次命令、结果与未完成项见[2026-09-01 量化自适应内存验证记录](verification/2026-09-01-minimax-h3-quantized-adaptive-memory.md)。

## 18. 后续电商模型剪枝怎么做

低显存运行优化与模型剪枝分两阶段：

1. 先固定一个已经完整跑通的官方量化基线，保存提示词、输入图、seed、耗时与结果；
2. 再准备覆盖瓶罐、服饰、饰品、家电等品类的电商验证集；
3. 对 DiT block、FFN 通道或条件分支做结构敏感度评估；
4. 剪枝后需要针对商品身份、文字布局、材质和运镜重新训练或校准；
5. 用相同基线同时比较模型大小、速度、显存和商品一致性。

没有验证集和微调就直接删层，通常只是得到更小但不可控的模型。本章目前完成的是量化权重的通用运行时调度，不宣称已经完成电商剪枝。

## 19. 来源与许可

- [MiniMax H3 官方项目](https://github.com/MiniMax-AI/MiniMax-H3)
- [ComfyUI MiniMax H3 指南](https://docs.comfy.org/tutorials/video/minimax/minimax-h3)
- [Comfy-Org MiniMax H3 R2V 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json)
- [Comfy-Org MiniMax H3 模型文件](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [ComfyUI MiniMax H3 原生节点](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py)

MiniMax H3 权重受其 Community License 约束。仓库内自适应节点是运行时调度代码，不重新分发模型权重，也不改变上游模型许可。
