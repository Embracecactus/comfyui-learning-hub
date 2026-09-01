# MiniMax H3 量化自适应内存验证记录（2026-09-01）

## 目标

把 MiniMax H3 低显存方案从“某张显卡的一组固定参数”改为可复用的运行时策略：

- 根据 GPU 原生算子选择 NVFP4 或 INT8；
- 根据实时剩余显存计算 H3 MLP token 窗口；
- 在 Qwen、DiT、VAE 三个阶段之间定向卸载；
- 分开记录结构验证和完整短片验证，不沿用 BF16 成功结论。

## 当前测试环境

```text
GPU: NVIDIA GeForce RTX 5060
compute capability: 12.0
VRAM: 7.96 GiB
Windows RAM: 约 32 GiB
PyTorch: 2.12.1+cu130
CUDA runtime: 13.0
ComfyUI: 0.33.4
Python: ComfyUI/.venv/Scripts/python.exe
```

该机器只是本次实测样本，策略代码没有按 `RTX 5060` 字符串分支。

## 发现的旧方案问题

旧的 `MiniMaxH3LowVRAM` 节点只有固定的 2048、4096、8192、32768 token 档位，不读取实时显存或内存。

测试机旧启动参数包含 `--disable-async-offload`。此时 ComfyUI `NUM_STREAMS=0`，核心不会创建 block prefetch queue，因此工作流写 `block_prefetch=keep` 也没有实际预取。新方案将“预取开关”和“异步流是否存在”一起判断。

## 新增实现

代码目录：

```text
custom_nodes/comfyui_adaptive_memory/
├── adaptive_policy.py
├── runtime.py
├── nodes.py
└── __init__.py
```

注册节点：

```text
MiniMaxH3AdaptiveMemory
H3ReleaseAfterConditioning
H3ReleaseAfterSampling
H3VAEDecodeTiledRelease
H3VAEDecodeAudioRelease
```

资源阶段：

```text
Qwen + reference VAEs
  ↓ release encoders
H3 DiT sampling
  ↓ release DiT and clones
video VAE decode → release
  ↓ explicit Boolean release barrier
audio VAE decode → release
```

屏障只传递一个布尔依赖，不传递视频帧；三份派生工作流都已检查为 `video decode output 1 → audio decode input 2`。视频节点只有启用并完成 release 才返回 `true`，否则音频节点拒绝运行。它验证的是执行顺序；驱动、mmap 和页缓存的实际驻留仍须实跑监测。

两个阶段释放节点的 `fingerprint_inputs()` 固定返回 `NaN`，明确告诉 ComfyUI 这两个节点具有资源回收副作用；重复排队不会因缓存命中而跳过 Qwen/VAE 或 DiT 的卸载。

## 策略边界

`MiniMaxH3AdaptiveMemory` 只修改 H3 DiT block 的 MLP forward：

- 已核对当前 ComfyUI `comfy/ldm/minimax/model.py`：采样主干创建 `h=[layout.seq_len, hidden_size]`，MLP 沿最后一个 hidden 维逐 token 计算；
- 实现不再把第 0 维写死为 token，而是把所有 leading dimensions 展平为 token rows，因此未来出现 `[batch, tokens, hidden]` 也不会悄悄失效；
- 最后一维不是检测到的 H3 hidden size 时直接报错，避免版本变化后生成错误结果。

- 使用原始 MLP 权重和原始算子；
- 只沿 token 维分块；
- 不跳层、不删 token、不近似 attention；
- 不改 seed、采样器、scheduler 或 LoRA；
- 不把量化权重恢复成 BF16 常驻副本。

窗口估算使用 H3 的真实 `hidden_size`、`ffn_hidden_size`、激活元素大小、当前 CUDA free VRAM 和用户预留值。权重精度与激活精度分开计算。

## 已完成验证

### 官方 LFS 身份快照

2026-09-01 对 `Comfy-Org/MiniMax-H3` 六个候选文件做 HEAD 检查，记录 `x-linked-size` 和作为 SHA-256 的 `x-linked-etag`：

```text
INT8 DiT       20970379616  9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779
Qwen NVFP4     15687142551  35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6
Qwen INT8      27141342152  bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923
video VAE       5207808496  7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522
audio VAE        605254808  8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48
Turbo LoRA      1956193000  5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c
```

本机 NVFP4 组合下载完成后，再用 `sha256sum` 顺序读取五个实际文件。结果与上表逐字一致：

```text
INT8 DiT       9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779
Qwen NVFP4     35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6
video VAE      7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522
audio VAE      8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48
Turbo LoRA     5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c
```

本机没有下载更大的 Qwen INT8 兼容权重；它的值仅是上游候选身份快照。哈希完成后未留下 `.download` 或 `.download.lock`，C 盘约剩 `76 GiB`。

### 下载器断流回归

- 镜像断流实测发现，同一个 `curl --retry ... -C -` 进程可能重复使用最初的 Range 偏移并追加重复字节；
- 预期 `20,970,379,616` 字节的扩散权重被大小闸门拦截为 `28,331,920,346` 字节，没有进入最终模型名；
- 两个遗留写者尚未停止时，损坏临时文件最终增长到 `29,266,086,874` 字节；停止精确 PID 后已删除该临时文件，并从 0 重新下载；
- 下载器已改成每个文件默认最多 100 次、可配置的外层重试；每次重新启动 `curl -C -`，从而重新读取当前 `.download` 长度；
- 另发现两个旧批处理曾同时写同一个临时文件；下载器现为每个目标创建原子锁目录，第二个写者会立即失败；
- 外部停止 curl 还可能在 Windows 返回负退出码；现仅把严格的退出码 `0` 视为成功，且用 localhost ping 代替在重定向 stdin 下会立即失败的 `timeout`；
- 从 WSL 向 Windows 下载会话发送 `Ctrl+C` 时，外层会话虽然退出，子 `curl.exe` 仍可能继续写。一次切换下载链路的实测因此把临时文件写到 `22,337,763,001` 字节；大小闸门再次阻止改名。确认文件长度停止变化后，将它精确截回切换前的 `19,145,459,637` 字节边界，再由唯一的 WSL `curl` 续传，最终得到官方期望的 `20,970,379,616` 字节。以后不能只凭外层会话退出判断 Windows 子进程已经停止，必须再观察文件长度稳定或检查进程；
- 已增加回归测试，禁止再次把 curl 内部 retry 与续传组合使用，并要求保留单写者锁、严格退出码和可配置重试预算。

### 磁盘清理留痕

为量化路线删除了测试机上可重新下载、已被替代的两份 BF16 权重：

```text
diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors
text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors
```

逻辑文件大小合计约 `91.73 GB`。停止仍持有旧 mmap 的 BF16 ComfyUI 进程后，Windows `Get-PSDrive C` 的可用空间从 `48.68 GiB` 回升到 `92.03 GiB`；随后删除上述 `29,266,086,874` 字节的损坏下载临时文件。2026-09-01 复核时，新的正确临时文件为 `4,955,865,286` 字节、单个 curl 写者、锁目录存在，C 盘可用 `112.02 GiB`。这些是不同时间点的快照，不能用逻辑文件大小直接推算实际释放量。没有删除 SDXL、Wan、Flux、H3 VAE、Turbo LoRA 或当前量化下载。旧 BF16 工作流 JSON 仍保留作历史基线，但要重跑必须重新下载这两份权重。

### 1. 自动化回归测试

仓库根目录执行：

```bash
python3 -m pytest -q tests
```

```text
25 H3 tests passed
36 repository tests passed
```

其中 25 项覆盖本次 H3 自适应策略、硬件检测器、下载器和工作流拓扑；连同原有商品布局测试共 36 项。

不要把命令写成不带路径的 `python3 -m pytest -q`：本仓库还包含一份上游
`ComfyUI/tests/`，它的集成测试需要额外的 `websocket` 依赖和推理基线目录。本次误扫
上游目录时在收集阶段因这些可选条件缺失而停止；限定为项目自己的 `tests/` 后为
`36 passed`，两者不是同一个测试边界。

覆盖：

- 低空闲显存选择小窗口；
- 增加显存后扩大窗口，但不读取 GPU 名称；
- 手工窗口受上下限约束；
- 无异步流时强制关闭预取；
- 系统内存不足时自动关闭预取；
- SM 10+ 选择 NVFP4；
- SM 8.9 选择 INT8；
- SM 7.0 不会误判成 SM 7.5 候选；
- CUDA Native backend 或必需 capability 缺失时不会标记 supported；
- 当前可用 RAM 不足时即使总 RAM 达标也退回磁盘流式；
- 旧 NVIDIA 不宣称支持；
- AMD 实验路径不标记为已支持；
- 物理内存独立决定内存辅助或磁盘流式模式。

### 2. 真实 ComfyUI 环境导入

使用当前实例 `.venv` 导入后，五个节点全部注册成功；同时确认当前 `unload_model_and_clones` 支持 `all_devices` 参数，音频解码节点会在视频释放屏障为 `false` 时拒绝执行。

### 3. 数值等价小样

在当前 ComfyUI `.venv` 中直接实例化原生 `comfy.ldm.minimax.model.MLP`，用 257-token 窗口分别检查实际 H3 使用的二维 packed token 和额外三维输入兼容性：

```text
input=(1300, 64)    output=(1300, 64)    max_abs=4.470348e-08  allclose=True
input=(2, 650, 64)  output=(2, 650, 64)  max_abs=1.490116e-08  allclose=True
```

差值来自不同 GEMM 批大小的浮点舍入；没有跳过 token、层或 attention，也没有改变输出形状。

### 4. H3 模型补丁

构造两层小型 `MiniMaxH3Model`，外包进 `ModelPatcher` 后调用 `MiniMaxH3AdaptiveMemory.execute()`，返回 `NodeOutput`，说明 H3 类型校验、模型 clone、逐 block MLP object patch 和 diffusion wrapper 注册成功。

### 5. 工作流结构

以下三条派生工作流均通过静态校验：

```text
ecommerce-minimax-h3-quantized-nvfp4-low-vram.json
ecommerce-minimax-h3-quantized-int8-low-vram.json
ecommerce-minimax-h3-bf16-streaming-8gb.json
```

每条均为：

```text
31 top-level nodes
41 top-level links
0 broken subgraphs
```

阶段依赖复核结果：

- 条件释放节点必须先收到 `MiniMaxH3ReferenceToVideo` 的 conditioning 与 latent，所以不会在 Qwen/VAE 编码前执行；
- 采样释放节点必须先收到 `SamplerCustomAdvanced` 的 samples，并持有最终 LoRA/switch 后的 MODEL，所以不会在采样前执行；
- 视频和音频解码收到同一个释放后 latent；
- 视频 VAE 节点完成解码与定向卸载后输出布尔屏障；音频 VAE 节点必须收到这个 `true` 屏障才会解码，因此两者不会按拓扑并发驻留；
- 两个 VAE 解码节点各自在完成后定向卸载自己的 VAE。

### 6. 当前机器检测结果

```text
Workflow profile: quantized-nvfp4-low-vram
Adaptive node: auto_stable
Chunk range: 1024-4096
VRAM reserve: 1024 MiB
Prefetch: auto
I/O mode: ram-assisted
First run: 0.1 MP / 5 seconds / 4 steps
```

上面是较早资源快照。2026-09-01 最新检测输出为：

```text
Torch: 2.12.1+cu130
CUDA runtime: 13.0
Compute capability: 12.0
VRAM: 7.96 GiB
System RAM: 31.11 GiB
Available RAM: 16.93 GiB
comfy-kitchen: 0.2.31, CUDA backend enabled
Workflow profile: quantized-nvfp4-low-vram
I/O mode: disk-streaming
Supported: true
```

可用 RAM 会随文件缓存和桌面程序变化；本轮多个快照在 `10.76–16.93 GiB` 之间，全部都应选择磁盘流式。修正版同时检查总 RAM 和当前可用 RAM，因当前可用内存不足以覆盖 `19.53 GiB` 最大模型阶段再加安全余量，所以从早先的 `ram-assisted` 正确退回磁盘流式。

为避免按文件名猜测算子，还对三个官方 safetensors 文件头做了 Range 读取：

```text
NVFP4 Qwen: 350 个 55-byte 线性层量化配置，代表值：
{"format": "nvfp4", "full_precision_matrix_mult": true}

NVFP4 Qwen embedding: 1 个 29-byte 配置：
{"format": "int8_tensorwise"}

INT8 Qwen: 350 个 72-byte 线性层量化配置，代表值：
{"format": "int8_tensorwise", "convrot": true, "convrot_groupsize": 256}

INT8 DiT: 200 个 72-byte 线性层量化配置，代表值同上。
```

结合当前 ComfyUI `mixed_precision_ops` 与 `linear_input_act` 调用路径，NVFP4 档要求 CUDA backend 的 `dequantize_nvfp4`、`int8_linear`，以及任一已启用 backend 的 `dequantize_int8_embedding`；INT8 档要求 CUDA `int8_linear`。`gemv_awq_w4a16` 虽存在于当前安装，却不是这些官方权重元数据对应路径的通过条件。若 SM 10+ 缺少 NVFP4 专属能力但仍有 `int8_linear`，检测器会退到 INT8 Qwen；相应降级与共同算子缺失均有自动化测试。检测器输出本身仍只代表候选配置；本机 NVFP4 档的完整渲染证据记录在下一节。

### 7. Windows 分页文件

已将 `AutomaticManagedPagefile` 恢复为 `True`，并确认 `Win32_PageFileSetting` 已无遗留固定大小条目。2026-09-01 只读复核时 `C:\pagefile.sys` 的当前 `AllocatedBaseSize` 仍为 `81920 MB`，因此本次启动周期中的旧 80GB 分配尚未缩小；需要 Windows 重启后才会由系统重新计算。本次没有擅自重启用户电脑。

### 8. NVFP4 完整短片实跑

服务由仓库启动器以 `DiskStreaming + Stable` 档启动。实际参数包括：

```text
--enable-dynamic-vram
--disable-smart-memory
--reserve-vram 1
--vram-headroom 0.5
--disable-pinned-memory
--preview-method none
--fast-disk
--disable-async-offload
```

首跑工作流：

```text
docs/04-电商AI工作流/workflows/ecommerce-minimax-h3-quantized-nvfp4-low-vram.json
prompt_id: c6681c75-f625-416a-85ff-5ea4f69fbbb1
server validation: valid=true, 0 errors, 0 warnings
```

关键服务端日志：

```text
Qwen/Text Encoder: 14956 MB staged dynamic
Adaptive memory: released H3 text/reference encoders before sampling
MiniMax H3: 19995 MB staged dynamic, 50 blocks patched
chunk=4096, scratch~454 MiB, free VRAM=5599 MiB, available RAM=3115 MiB
chunk=1792, scratch~198 MiB, free VRAM=2837 MiB, available RAM=3299 MiB
prefetch=off (async offload has no active stream)
Adaptive memory: released H3 DiT before VAE decode
Video VAE: 4965 MB staged, released after tiled decode
Audio VAE: 576 MB staged, released after decode
Prompt executed in 43.96 seconds
```

这说明自适应窗口不是写死的显卡型号档位：同一次任务中，它会因现场可用资源从 `4096` 缩到 `1792` token。稳定档没有异步 stream，预取按设计关闭；这不是预取失效。

输出复核：

```text
Windows: C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output\ecommerce\video\minimax-h3-quantized-nvfp4-low-vram_00001_.mp4
size: 517870 bytes
sha256: 09b538f8cd9abd0a5dff965be467afb7fb8c33b968a52897e34d5f6311f78d68
video: H.264, 256x416, 24 fps
audio: AAC, 32000 Hz, stereo
duration: 5.167 seconds
```

MP4 可正常解码，包含画面和声音。中间帧目视检查中，琥珀色滴管瓶主体仍居中可辨，但低分辨率下右侧标签有文字变形，左侧有橙色运动拖影。因此这次验收只证明链路与资源调度成功，不把它写成最终电商画质验收。

任务完成后采样到约 `7.27 GB` 空闲显存和 `4.48 GB` 可用系统内存；主动释放缓存后约为 `7.27 GB` 和 `7.54 GB`。这些只是节点间/任务后的离散快照，不是连续峰值监测。当前开机周期仍有旧的 80GB 分页文件分配，所以本轮也不能证明重启后较小的系统管理分页文件一定足够。

## 尚未完成与结论边界

截至本记录更新时：

- 没有连续采集峰值显存、峰值系统内存和磁盘吞吐；已有数据是服务日志与离散快照；
- Windows 重启后，系统管理分页文件重新计算状态下尚未复测；
- INT8 兼容工作流尚未在 SM 7.5/8.x/8.9 机器上实跑；
- AMD 路线仍是实验候选。

因此当前结论是：**RTX 5060 8GB + Windows 32GB 的 NVFP4、0.1 MP 首跑基线通过**；不能扩写成“所有低显存设备、INT8 或无大分页文件环境均已通过”。

## 完整验收条件

只有同时满足以下条件，才把某一硬件组合标记为实跑通过：

1. 模型字节数或 SHA-256 校验通过；
2. 服务端工作流校验通过；
3. 完成 Qwen 编码、四步 DiT、视频 VAE 和音频 VAE；
4. 输出可播放且含画面和声音的 MP4；
5. 保存实际 chunk、prefetch 原因和可获得的资源快照；若宣称峰值，则必须使用连续采样；
6. 结果不使用 BF16 历史 run 的时间或资源数据冒充。
