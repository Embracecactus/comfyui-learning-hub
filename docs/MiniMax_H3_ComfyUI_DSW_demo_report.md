# MiniMax H3 + ComfyUI 在阿里云 PAI DSW 单卡 Demo 级部署报告

> 调研日期：2026-08-20
> 目标：在阿里云 PAI DSW（天池 Notebook 探索者版）单卡 GPU 实例上，以最小成本跑通 ComfyUI + MiniMax H3 并测速，评估「60 GPU 小时」配额的实际产出。
> 受众：具备 ML 部署经验（熟悉 offload / 量化）的用户。
> 结论分级：✅ 官方可信源 ｜ 🟡 社区口径（未获官方背书）｜ ❓ 未证实（不可信/待核实）。

---

## 1. 摘要（Bottom Line）

- **可行路径明确**：ComfyUI **≥ 0.30.0** 起**原生内置** MiniMax H3 节点，无需任何自定义节点；权重来自官方重打包仓库 `Comfy-Org/MiniMax-H3`（含 int8 / nvfp4 量化版本）。这是单卡 demo 唯一推荐的本地路径（路径 A）。
- **单卡能跑，但有门槛**：官方未公布最低显存；社区口径「24GB 单卡是甜点线」（🟡 未证实），官方降门槛手段是 **int8 DiT + nvfp4 文本编码器 + 分层 offload**。显存 <16GB 本地跑通概率极低，建议直接走官方 API 节点（路径 B，零本地 GPU）。
- **关键环境坑**：int8_convrot 权重需 **PyTorch 带 cu130（CUDA 13.0）**，否则改用 `fp8_scaled` 版。
- **60h 产出取决于实测速度**：用 `片段数 ≈ 216000 / T`（T 为单条 5s 片段稳态耗时秒）反推；offload 会显著拖慢、减少产出。
- **DSW 访问简单**：启动 ComfyUI 后点击终端里的 `http://127.0.0.1:8188` 即可经 DSW 内置代理在浏览器打开，无需额外网络配置。

---

## 2. 环境调研：阿里云 PAI DSW（✅ 官方文档）

| 项 | 结论 | 来源 |
|---|---|---|
| 预装框架 | 官方镜像内置 PyTorch / TensorFlow；GPU 镜像预装对应 CUDA/cuDNN | DSW 概述 |
| 终端 | JupyterLab 的 Terminal 标签，可直接 `git clone` / `pip install` / 启服务 | DSW |
| Web UI 访问 | 启动服务后，终端输出的 `http://127.0.0.1:PORT` 变为**可点击代理链接**，经 DSW 网关打开（SD WebUI 教程实证） | DSW 快速启动 |
| 公网访问 | 需「自定义服务 + NAT+EIP」，最多 5 个；NAT/EIP **停止后仍计费**，不用即删 | DSW 访问配置 |
| 工作目录 | 默认 `/mnt/workspace` | DSW |
| 持久化 | **云盘系统盘**：停 <15天/重启/变配保留，换镜像可能重置；**临时盘**：停即丢。权重建议挂 **OSS/NAS/CPFS**（如 `/mnt/data`），实例删后仍保留 | DSW FAQ |
| 计费 | 公共资源组后付费，实例「运行中」即计费，与是否开浏览器无关；必须手动停止 | DSW 计费 |
| 出网 | 默认公有网关免费出网（共享带宽，速度无保证），`pip`/`git` 默认可用 | DSW 网络 |
| 海外模型 | HF 直连通常慢；可用全球加速 GA（计费）或改 ModelScope / PAI 内部 OSS 镜像 | DSW 网络 |

**未证实项**：探索者版具体「60 GPU 小时」配额（官方免费页未写明，以控制台为准）；`nohup` 后台进程稳定性保证；官方推荐 pip 国内镜像源。

---

## 3. 模型调研：MiniMax H3 在 ComfyUI 中的集成（✅ 官方源）

### 3.1 官方地址
- 官方 GitHub：`https://github.com/MiniMax-AI/MiniMax-H3`
- 官方模型卡（HF）：`https://huggingface.co/MiniMaxAI/MiniMax-H3`
- ComfyUI 本地部署官方教程：`https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3`
- ComfyUI API 节点教程（云端）：`https://docs.comfy.org/zh/tutorials/partner-nodes/minimax/minimax-h3`
- 官方重打包权重（ComfyUI 用）：`https://huggingface.co/Comfy-Org/MiniMax-H3`
- 工作流模板：T2V / I2V / R2V 见 `Comfy-Org/workflow_templates`

> ⚠️ SEO/营销文泛滥（如 `minimaxh3.run`、`*.csdn.net`、`post.smzdm.com` 等标题含「8G 显存也能跑」），**硬件结论不可直接采信**，仅作社区信号。

### 3.2 集成路径
- **路径 A（推荐，本地推理）**：ComfyUI ≥ 0.30.0 **原生内置**节点 `MiniMaxH3ImageToVideo`(fl2va) / `MiniMaxH3ReferenceToVideo`(ref2va) / 文生视频节点。模板库一键加载工作流，按弹窗从 `Comfy-Org/MiniMax-H3` 下载权重，**不走 SGLang/vLLM/Diffusers 桥接**。
- **路径 B（云端 API 节点）**：在 MiniMax 服务器执行，需登录 Comfy 账户/API，按秒计费，输出最高 2K；适合无 GPU 验证，不满足本地 demo 目标。
- **非推荐**：原始仓库的 SGLang（`sglang serve ... --ulysses-degree 4`，参考示例 **4 卡**）、vLLM、Diffusers 是「裸」推理服务；社区节点 `goohai/Goohai-MiniMax-H3_Integration` 非官方、非必需。

### 3.3 硬件与量化（官方已证实）
- 官方**未公布最低显存数值**；SGLang 示例用 4 卡，说明 BF16 完整推理是重负载。
- 量化版本（Comfy-Org 重打包）：
  - DiT 扩散：`*_pruned_int8_convrot.safetensors`（int8+剪枝，最小组合之一）；备选 `bf16` / `fp8_scaled`。
  - 文本编码器：`qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（NVFP4-AWQ，**不需 Blackwell**）。
  - VAE：视频 fp16 / 音频 fp32；可选 Turbo/Lightning LoRA（8步/4步）。
- 🟡 社区口径：24GB 单卡 + INT8 DiT + 自动分层卸载「可跑」；8G 能跑属营销标题 ❓ 不可信（仅文本编码器量化即 ~16GB 量级）。

**权重选择组合**（按 `torch.cuda` 版本二选一，文件放对应 `models/` 子目录）：

| 文件 | 场景 A：cu130 | 场景 B：非 cu130 |
|---|---|---|
| `models/diffusion_models/` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `minimax_h3_fl2va_pruned_fp8_scaled.safetensors` |
| `models/text_encoders/` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（无需 Blackwell） |
| `models/vae/` | `minimax_h3_video_vae_fp16.safetensors` | 同左 |
| `models/vae/` | `minimax_h3_audio_vae_fp32.safetensors` | 同左 |
| `models/loras/` | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | 同左 |

要点：`pruned_`=剪枝版（更小），显存紧时优先；文本编码器一律选 `nvfp4_awq`（最小、无需 Blackwell，`bf16` 版 ~64GB 量级别下）；I2V/R2V 再补 `ref2va_pruned_int8_convrot`（A）/ `ref2va_pruned_fp8_scaled`（B）+ 对应 ref2v turbo LoRA；体积估算（⚠️ 未证实）：nvfp4 ~16GB、pruned int8/fp8 ~10–20GB、VAE 各几个 GB。**最省事用模板库 UI 自动下载**（自动放对目录）。

### 3.4 Demo 可调性与坑
- 原生画布短边 **768px**（16:9→1344×768）；可缩小「百万像素」加速；时长 5–15s（24fps，按 17 帧块对齐）；turbo_mode 8/4 步。低分辨率/短时长 demo 官方明确支持。
- **版本**：ComfyUI 必须 ≥ 0.30.0。
- **cu130 坑**：int8_convrot 需 `torch` 带 cu130；否则用 `fp8_scaled`（官方建议）。
- **分辨率上限**：勿选 1.0 百万像素档（得 1376×768，超 768×1344 面积上限）；保持 32 倍数。
- **Sage Attention**（约 2×）：需匹配 wheel + KJNodes `Patch Sage Attention KJ`；控制台 float16/bfloat16 回退提示为正常现象。
- **2K 输出**：仅官方 API 的 Regenerate-2K，**未证实本地单卡可出 2K**。
- **许可证**：MiniMax H3 Community License Agreement（有地域/用途限制，商用需申请）。

---

## 4. 可行性决策树（结合 offload / 量化）

```
nvidia-smi 看显存
 ├─ ≥24GB  → int8 DiT + nvfp4 文本编码器，直跑（🟡 社区称可跑，建议实测最短片段）
 ├─ 16–24GB → int8_convrot + nvfp4 + 分层 offload，可能可行但无官方保证
 └─ <16GB   → 本地单卡跑通概率极低 → 直接走路径 B 官方 API 节点（零本地 GPU）
另：torch.version.cuda == 13.0 ？
 ├─ 是 → 用 int8_convrot 权重
 └─ 否 → 改用 fp8_scaled 权重
```

**核心权衡**：offload 到系统内存可续命低显存，但 PCIe 搬运使吞吐暴跌，直接减少 60h 内可出片段数。offload 失败/反复报错时，**别死磕**——退回 API 节点验证效果，把配额留给有产出的推理。

---

## 5. Demo 实施方案

1. **开通实例**：单卡 ≥24GB 显存、RAM ≥32GB（建议 64GB+）、**云盘**系统盘、预留 50–80GB；另挂 OSS/NAS 放权重。
2. **硬件确认**：`nvidia-smi` / `free -h` / `df -h` / 查 `torch.version.cuda`。
3. **装 ComfyUI**：`git clone` + `pip install -r requirements.txt` + `python main.py --listen 0.0.0.0 --port 8188`；点终端 `127.0.0.1:8188` 代理链接开 UI；确认版本 ≥0.30.0。
4. **接 H3**：模板库 → 视频 → MiniMax H3 → 选 T2V/I2V/R2V → 按弹窗从 `Comfy-Org/MiniMax-H3` 下权重（int8_convrot DiT + nvfp4_awq 文本编码器 + 2 VAE + 可选 Turbo LoRA）。
5. **跑最小片段量速**：预览分辨率（短边 768）/ 5s / 24fps / 开 turbo 8 步。首次含加载记为冷启动；第二次起测稳态 T 秒。
6. **反推产出**：`片段数 ≈ 216000 / T`，`总时长 ≈ 片段数 × 5s`（GPU 实际运行秒）。

---

## 6. 风险与省时清单

- ComfyUI 必须 ≥0.30.0；int8_convrot 需 cu130，否则 fp8_scaled。
- 分辨率勿超 768×1344 面积上限，保持 32 倍数。
- Sage Attention 回退提示正常；装错 wheel 反而慢。
- 先确认显存 / cu 版本**再**下权重，避免下错版本白等。
- 权重放 OSS/NAS，停/启实例不重下。
- 不用实例**立即手动停止**；删 NAT+EIP/GA 防持续计费。
- 确认 MiniMax H3 Community License 合规。

---

## 7. 可勾选检查清单

- [ ] 实例：单卡 ≥24GB 显存 / RAM ≥32GB / 云盘系统盘 / 预留 50–80GB
- [ ] 已挂 OSS/NAS 持久化权重
- [ ] 跑 `nvidia-smi` / `free -h` / `df -h` / 查 `torch.version.cuda`
- [ ] 显存判定：≥24GB 直跑；16–24GB 备 int8+nvfp4+offload；<16GB 走 API 节点
- [ ] `torch.cuda==13.0`？是→int8_convrot；否→fp8_scaled
- [ ] clone ComfyUI + 装依赖 + `python main.py --listen 0.0.0.0 --port 8188`
- [ ] 点 `127.0.0.1:8188` 代理链接开 Web UI；版本 ≥0.30.0
- [ ] 模板库加载 H3 工作流，按弹窗从 `Comfy-Org/MiniMax-H3` 下权重
- [ ] 权重组合：int8_convrot DiT + nvfp4_awq 文本编码器 + 2 VAE（+Turbo LoRA）
- [ ] 跑最小片段：预览 768 / 5s / 24fps / turbo 8 步
- [ ] 记稳态 T，算 秒/帧、片段数=216000/T
- [ ] 不用即停实例；删 NAT+EIP/GA；确认 License 合规

---

## 8. 参考源与可信度

**✅ 可信（官方）**
- `MiniMax-AI/MiniMax-H3`（官方 GitHub）
- `Comfy-Org/MiniMax-H3`（ComfyUI 重打包权重）
- `docs.comfy.org/zh/tutorials/video/minimax/minimax-h3`（官方本地部署教程）
- 阿里云 PAI DSW 帮助文档（概述 / FAQ / 访问配置 / 网络 / SD WebUI 快速启动）

**🟡 社区口径（未获官方背书）**
- 24GB 单卡甜点线；INT8 DiT + 分层卸载可跑。

**❓ 未证实 / 不可信**
- 最低显存具体值、各权重精确 GB 数、60 GPU 小时配额、「8G 可跑」、GGUF 支持、本地出 2K、后台进程稳定性保证、官方推荐 pip 镜像。
