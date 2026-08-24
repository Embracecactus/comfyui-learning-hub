# MiniMax H3 + ComfyUI 在阿里云 PAI DSW 手动操作指南

> 面向：手动一步步操作（不依赖一键脚本）。适合首次登录 DSW 的用户。
> 预计总耗时：首次约 1–2 小时（含权重下载）。已备 `scripts/deploy_comfyui_h3_dsw.sh`，嫌麻烦可直接 `bash scripts/deploy_comfyui_h3_dsw.sh` 走自动化，本指南与其内容一致。
> 重要前提：**ComfyUI 必须 ≥ 0.30.0**；H3 权重推荐 `int8_convrot DiT + nvfp4_awq 文本编码器`（需 torch 带 **cu130**，否则用 `fp8_scaled` 版）。

---

## 第 0 步：开通 DSW 实例（控制台操作）

1. 打开阿里云控制台 → **机器学习平台 PAI** → **DSW 实例**（或从天池 Notebook 入口进入）。
2. 点击 **创建实例**，规格按下表选：

   | 配置项 | 建议值 | 说明 |
   |---|---|---|
   | GPU | 单卡 **≥24GB 显存**（如 A10 24G / V100 32G / A100 40G+） | 官方没给最低值；24GB 是社区"甜点线"，<16GB 基本没戏 |
   | 系统内存 | **≥32GB**，有 64GB 更好 | offload 要把层卸到内存 |
   | 系统盘 | **选「云盘」** | 临时盘停止即丢数据 |
   | 挂载存储 | 建议另挂 **OSS 或 NAS**（挂载点如 `/mnt/data`） | 放权重，实例删了也不丢 |
   | 预装镜像 | PyTorch GPU 镜像 | 自带 CUDA/cuDNN |

3. **付费模式**：公共资源组按量后付费，**实例「运行中」就开始扣 GPU 小时**，跟你开没开浏览器无关。不开就用，**用完手动停止**。
4. 等状态变为 **运行中**，点 **打开** 进入 JupyterLab。

> ⚠️ 若开了「自定义服务 / NAT+EIP / 全球加速」会**额外计费且停止后仍收费**，demo 阶段别开。

---

## 第 1 步：打开 Terminal

在 JupyterLab 左侧 Launcher 里点 **Terminal**（没有就在菜单 `File → New → Terminal`）。后续所有命令都在这个终端里跑。

先确认硬件（照抄即可）：

```bash
nvidia-smi
free -h
df -h /mnt/workspace
```

- `nvidia-smi` 看 GPU 型号和显存，记下来（后面判断用）。
- `free -h` 看内存，`df -h` 看磁盘余量（H3 权重预留 50–80GB）。

---

## 第 2 步：安装 ComfyUI

```bash
cd /mnt/workspace
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

- 如果之前装过：`cd /mnt/workspace/ComfyUI && git pull --ff-only` 更新。
- 确认版本 ≥ 0.30.0（原生内置 H3 节点）：

```bash
git describe --tags || git log --oneline -1
```

---

## 第 3 步：检查 torch 的 CUDA 版本（关键）

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

- 输出形如 `2.x.x+cu130 13.0` → **满足**，下载权重时选 `int8_convrot` 版。
- 若是 `cu121 / cu124` 等 → **不满足**，下载权重时选 **`fp8_scaled`** 版 DiT（官方建议），否则量化算子会报错。
- 若 `torch` 没装或版本很旧，先升级：

```bash
pip install -U torch --index-url https://download.pytorch.org/whl/cu130
```

（DSW 到海外源可能慢，可换清华源或继续用自带的。）

---

## 第 4 步：启动 ComfyUI 并打开 Web UI

```bash
cd /mnt/workspace/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

- 看到日志里出现 `To see the GUI go to: http://127.0.0.1:8188`。
- **在 JupyterLab 界面点这个 `http://127.0.0.1:8188` 链接**（它会被 DSW 转成代理链接），浏览器即打开 ComfyUI 画布。
- 想关掉当前终端也能继续跑（后台模式）：

```bash
cd /mnt/workspace/ComfyUI
nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &
tail -f comfy.log   # 看日志；Ctrl+C 只看日志不影响服务
```

> 停止实例前记得先结束进程（`pkill -f "main.py --listen"`），否则实例会卡在「停止中」。

---

## 第 5 步：加载 MiniMax H3 工作流 + 下载权重

全部在浏览器 Web UI 里操作：

1. 左侧边栏点 **模板库（Templates）**。
2. 展开 **视频（Video）** 分类，找到 **MiniMax H3**，选一个模板：
   - **T2V**：文生视频
   - **I2V**：首/末帧图生视频（fl2va）
   - **R2V**：多模态参考生视频（ref2va）
3. 点模板后弹出「缺少模型」提示 → 点 **下载/确认**，权重会自动从 `Comfy-Org/MiniMax-H3` 拉取并放到正确目录（不用手动摆位置）。
4. 下载完成后画布上会出现完整节点图。

**权重选择组合**（先按第 3 步确认 `torch.cuda` 版本，再挑一组）：

**场景 A：`torch.cuda == 13.0`**（可跑 int8_convrot，推荐）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_int8_convrot.safetensors
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors   ← 无需 Blackwell 显卡
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

**场景 B：`torch.cuda != 13.0`**（cu121/cu124 等，用 fp8_scaled）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_fp8_scaled.safetensors  ← 把 int8 换成 fp8
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

要点：
- **pruned_ = 剪枝版，更小**，显存紧时优先；无 pruned 前缀是完整版。
- **文本编码器一律选 `nvfp4_awq`**：最小，且官方明确不需要 Blackwell 显卡；`bf16` 版约 64GB 量级（⚠️ 估算，页面未列体积）**别下**。
- 要 **I2V/R2V** 时再补 `ref2va_pruned_int8_convrot`（A）/ `ref2va_pruned_fp8_scaled`（B）+ 对应 ref2v turbo LoRA；先下 fl2va（T2V/I2V 共用）+ nvfp4 文本编码器就能跑。
- 估算体积（⚠️ 未证实）：nvfp4 文本编码器 ~16GB，pruned int8/fp8 扩散 ~10–20GB，两个 VAE 几个 GB。**别全量下载**，按需挑。
- **最省事**：直接让模板库自动下载（第 5 步流程），它会按所选模板自动放对目录。

> 模板下载慢：DSW 直连 HF 可能很慢。可换 `H,F_ENDPOINT=https://hf-mirror.com`（国内镜像）重试，或改用 ModelScope 渠道。

---

## 第 6 步：跑最小片段（先验证链路，再量速）

在画布上按下面参数设置 **KSampler/采样** 与输出节点：

| 参数 | 值 | 说明 |
|---|---|---|
| 分辨率 | 用默认「预览」尺寸，**短边 768px**（16:9→1344×768） | 别选 1.0 百万像素档（会超 768×1344 上限） |
| 时长 | **5 秒** | 24fps，按 17 帧块对齐 |
| 采样步数 | 开 `turbo_mode`，用 **8 步** LoRA（或 4 步） | 提速用 |
| seed | 固定数字 | 复现用；换图改 seed |

点右上角 **Run（播放按钮）**，等它跑完。

**测速（为算 60h 产出）**：
1. 第一次跑含模型加载，记作「冷启动」，**不计入**。
2. 第二次开始记**稳态**耗时 `T`（秒）——从点 Run 到视频完成。
3. 代入公式：
   - `秒/帧 = T / 120`（5s × 24fps = 120 帧）
   - 60h 可出片段数 ≈ `216000 / T`
   - 总视频时长 ≈ `片段数 × 5 秒`

举例：若 `T = 600s`（10 分钟一条 5s 片段），则约 360 条 ≈ 30 分钟视频。`T` 越大说明 offload 拖累越重、产出越少。

---

## 第 7 步：显存不够 / 报错怎么办

| 现象 | 处理 |
|---|---|
| `CUDA out of memory` | 降低分辨率 / 时长；显存 16–24GB 时依赖自动分层卸载(offload)续命，但仍 OOM 就**别死磕**，见下方"退回 API 节点" |
| 量化算子报错（int8 相关） | torch 不是 cu130，回第 3 步改用 `fp8_scaled` 权重 |
| Sage Attention 相关提示 | 提示 `Input tensors must be ... float16 or bfloat16 ... using pytorch attention instead` 是**正常现象**，不影响出图 |
| 模型下载失败/超慢 | 换 `hf-mirror.com` 或 ModelScope 镜像重下 |
| 节点是红的 / 找不到 H3 节点 | ComfyUI 版本 <0.30.0，`git pull` 更新后重启服务 |

**退回官方 API 节点（零本地 GPU，兜底方案）**：
1. 登录 Comfy 账户（Web UI 右上角）或配置 MiniMax API Key。
2. 改用 **API 节点**（`MiniMaxH3...` 云端版，来自 MiniMax 合作节点），在服务器上执行、按秒计费。
3. 优点：不占你 60h 本地配额、可出 2K。缺点：要付费、不满足"本地 demo"目标。

---

## 第 8 步：停止实例与清理（省钱）

1. 先停 ComfyUI 进程：`pkill -f "main.py --listen"`（避免实例卡「停止中」）。
2. 回 DSW 控制台，对实例点 **停止**（立即停止扣费；**重启才恢复**）。
3. 检查有没有开 NAT+EIP / 全球加速 / 自定义服务——**它们停止后仍收费**，demo 阶段没开最好，开了就删。
4. 权重放 OSS/NAS 的话，下次重启实例不用重新下载；放系统盘则注意云盘「停止超 15 天且未扩容会清空」。

---

## 快速复查清单

- [ ] 实例：单卡 ≥24GB / RAM ≥32GB / 云盘系统盘
- [ ] `nvidia-smi` 确认显存；`free -h` 确认内存
- [ ] `torch.cuda == 13.0`？是→int8_convrot；否→fp8_scaled
- [ ] `git clone ComfyUI` + `pip install -r requirements.txt` 成功
- [ ] `python main.py --listen 0.0.0.0 --port 8188` 后点 `127.0.0.1:8188` 链接打开 UI
- [ ] ComfyUI ≥ 0.30.0
- [ ] 模板库加载 H3 工作流，权重按弹窗下载完成
- [ ] 跑 5s / 短边768 / turbo 8 步 的最小片段成功
- [ ] 记下稳态 T，算 片段数=216000/T
- [ ] 用完停止实例；确认无 NAT+EIP/GA 持续计费
- [ ] 确认 MiniMax H3 Community License 合规（自用 demo 一般没问题）

---

## 关键参考链接

- ComfyUI 官方本地部署教程：`https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3`
- H3 官方 GitHub：`https://github.com/MiniMax-AI/MiniMax-H3`
- ComfyUI 重打包权重：`https://huggingface.co/Comfy-Org/MiniMax-H3`
- DSW 帮助文档：`https://help.aliyun.com/zh/pai/dsw-overview`
