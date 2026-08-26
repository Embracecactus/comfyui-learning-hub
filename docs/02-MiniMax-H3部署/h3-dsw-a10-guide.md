# 阿里云 PAI DSW（A10 24G）跑 MiniMax H3 实操指南（实测版）

> 适用：阿里云 PAI DSW（天池探索者版，**60 GPU 小时**额度，实测选 **A10 24GB**，3.3 机时/小时，剩余约 18.16 机时）
> 目标：单卡跑通 **ComfyUI + MiniMax H3** 视频 demo；验证可行性、测速、估算 60h 产出。
> 本文命令**待你启动 A10 实例后逐条实测**，实测值会回填到第 0 / 11 节。ComfyUI 必须 **≥0.30.0**（原生内置 H3 节点）。

---

## 0. 实测环境（待启动 A10 后回填）

| 项 | 目标值 / 说明 |
|---|---|
| 平台 | 阿里云 PAI DSW，实例「运行中」即扣 GPU 小时 |
| 工作目录 | `/mnt/workspace`（DSW 默认挂载，容器重启会清，**务必用完停实例**） |
| GPU | **A10，24GB 显存**（选卡界面选 A10，3.3 机时/小时） |
| ComfyUI | ≥0.30.0（原生含 MiniMax H3 节点） |
| PyTorch / CUDA | 取决于 DSW 镜像；`int8_convrot` 权重需 **torch 带 cu130**，否则用 `fp8_scaled` 版 |
| 显存门槛 | ≥24GB 直跑；16–24GB 依赖 int8 + nvfp4 量化 + offload；<16GB 基本没戏（见第 6 节） |

> ⚠️ DSW 容器**关机数据会清**：代码/模型默认在 `/mnt/workspace`，停实例后文件可能丢。关键产物（H3 权重、工作流 JSON）要么**不关机一直烧机时**，要么**下完立刻传 OSS / ModelScope 备份**。本文第 10 节给停止与备份建议。

---

## 1. 环境确认

在 JupyterLab 的 **Terminal**（Launcher → Terminal）里跑：

```bash
nvidia-smi
free -h
df -h /mnt/workspace
python --version
python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

- `nvidia-smi` 出表格 → 确认是 A10、显存 24GB，记下型号。
- `free -h` 看内存（H3 offload 需要 ≥32GB，A10 实例一般给到）。
- `df -h` 看磁盘余量（H3 权重预留 **50–80GB**）。
- `torch.version.cuda`：`13.0` 可用 `int8_convrot`；否则用 `fp8_scaled`（见第 5 节）。

---

## 2. 安装 / 更新 ComfyUI

```bash
cd /mnt/workspace
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

- 之前装过就更新：`cd /mnt/workspace/ComfyUI && git pull --ff-only && pip install -r requirements.txt`
- 检查版本：`git describe --tags`（≥0.30.0 才有 H3 节点）。
- ⚠️ **别重复 clone**：避免多层嵌套副本导致模型目录混乱（同腾讯云那份的坑，见 `tencent-cloud-comfyui-guide.md` 5.1.1）。只保留一个 `/mnt/workspace/ComfyUI`。

---

## 3. 启动 ComfyUI

```bash
cd /mnt/workspace/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

看到 `To see the GUI go to: http://0.0.0.0:8188` 说明服务起来。

- 这个终端**别关**；或后台跑（关终端也能续）：
  ```bash
  cd /mnt/workspace/ComfyUI
  nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &
  tail -f comfy.log   # 看日志；Ctrl+C 只看日志不影响服务
  ```
- 停实例前先结束进程，避免实例卡「停止中」：`pkill -f "main.py --listen"`

---

## 4. 打开 Web UI（DSW 内置代理，不用 cloudflared）

DSW 自带 Web 代理，**不需要** cloudflared 隧道（和腾讯云不同）。

- 终端里出现的 `http://127.0.0.1:8188` **链接可直接点**，DSW 会转成代理地址在浏览器打开 ComfyUI 画布。
- 若没渲染：确认服务在跑 `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188`（应返回 200）。

> 对比腾讯云那份第 4 节：那里用 cloudflared 是因为 Cloud Studio 不自带稳定代理；DSW 直接点链接即可，更简单。

---

## 5. 加载 MiniMax H3 + 下载权重

全部在浏览器 Web UI 内操作：

1. 左侧 **模板库（Templates）** → 展开 **视频（Video）** → 找到 **MiniMax H3**。
2. 选模板：**T2V**（文生视频）/ **I2V**（图生视频）/ **R2V**（参考生视频）。先选 **T2V** 验证链路。
3. 弹窗「缺少模型」→ 点 **下载/确认**，权重自动从 `Comfy-Org/MiniMax-H3` 拉取并放对目录（**不用手动摆位置**，比腾讯云那份手动 wget 省事）。
4. 下载完画布出现完整节点图。

### 5.1 权重组合（先按第 1 步确认 torch.cuda 再选）

**场景 A：`torch.version.cuda == 13.0`**（推荐，可跑 int8_convrot）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_int8_convrot.safetensors
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors   ← 无需 Blackwell 显卡
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

**场景 B：`torch.version.cuda != 13.0`**（cu121/cu124 等，用 fp8_scaled）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_fp8_scaled.safetensors  ← 把 int8 换成 fp8
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

要点：
- **文本编码器一律选 `nvfp4_awq`**：最小（约 16GB），官方明确**不需要 Blackwell 显卡**；`bf16` 版约 64GB 量级**别下**。
- **`pruned_` = 剪枝版更小**，显存紧优先；A10 24G 建议 pruned 版。
- 下载慢：模板库走 HF，DSW 直连可能慢。可换镜像重试，或用 `huggingface-cli` 预拉（见 5.2）。
- 想 **I2V/R2V** 再补 `ref2va_pruned_*` + 对应 turbo LoRA；先 fl2va（T2V/I2V 共用）+ nvfp4 就能跑。

### 5.2 可选：终端预拉权重（模板库慢时兜底）

```bash
pip install -q -U "huggingface_hub[cli]"
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download Comfy-Org/MiniMax-H3 \
  --local-dir /mnt/workspace/ComfyUI/models/MiniMax-H3 \
  --include "*pruned_int8_convrot*" "*nvfp4_awq*" "*.fp16*" "*.fp32*" "*turbo*"
```

- `HF_ENDPOINT=https://hf-mirror.com` 走国内镜像；或在 ModelScope 找同权重的镜像源。
- 若 torch 非 cu130，把 `int8_convrot` 换成 `fp8_scaled`。

---

## 6. 关于显存门槛（A10 24G 够不够）

- **A10 24G 在「int8_convrot + nvfp4_awq 量化 + pruned 剪枝」组合下可直跑** H3 的最小片段（5s / 短边768）。
- 若仍 OOM：
  - 降分辨率到 **短边 512** 或时长缩到 **3s**；
  - 依赖 ComfyUI 自动 offload（层卸到内存）续命；
  - 或升级到 **V100 32G**（3.6 机时/小时）更稳。
- <16GB（如 T4 15G）基本没戏——见 `tencent-cloud-comfyui-guide.md` 第 6 节。

---

## 7. 跑第一段视频（先验证链路，再测速）

在画布上设置采样 / 输出节点参数：

| 参数 | 值 | 说明 |
|---|---|---|
| 分辨率 | **短边 768px**（16:9 → 1344×768） | 别选百万像素档（超 768×1344 上限） |
| 时长 | **5 秒** | 24fps，按 17 帧块对齐 |
| 采样步数 | 开 `turbo_mode`，用 **8 步** LoRA | 提速用 |
| seed | 固定数字 | 复现用；换视频改 seed |

点右上角 **Run（播放按钮）**，等跑完。

**测速（为算 60h 产出）**：
1. 第一次跑含模型加载，记作「冷启动」，**不计入**。
2. 第二次起记**稳态**耗时 `T`（秒）——从点 Run 到视频完成。
3. 公式：
   - `秒/帧 = T / 120`（5s × 24fps = 120 帧）
   - **60h 可出片段数 ≈ `216000 / T`**（60h = 216000 GPU 秒）
   - 总时间 ≈ 片段数 × 5 秒

举例：若 `T = 600s`（10 分钟一条 5s），约 **360 条 ≈ 30 分钟视频**。`T` 越大说明 offload 拖累越重、产出越少。

---

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| 节点是红的 / 找不到 H3 节点 | ComfyUI <0.30.0，`git pull` 更新后重启服务 |
| 量化算子报错（int8 相关） | torch 不是 cu130，回第 1 步改用 `fp8_scaled` 权重 |
| `CUDA out of memory` | 降分辨率/时长；或换 V100 32G；仍 OOM 见第 6 节退回 API 节点 |
| Sage Attention 提示 `using pytorch attention instead` | **正常现象**，不影响出视频 |
| 模型下载失败/超慢 | 模板库重下；或 `HF_ENDPOINT=https://hf-mirror.com` 用 CLI 预拉（5.2）；或 ModelScope |
| 文本编码器体积爆炸 | 下成了 `bf16` 版（~64GB）；删掉改下 `nvfp4_awq` 版 |
| `nvidia-smi` 不可用 | 实例没选 GPU 规格，回控制台确认选了 A10 |
| 链接点了打不开 UI | 服务在跑？`curl ... 127.0.0.1:8188` 应 200；或重开 Terminal 重启 `main.py` |

**退回官方 API 节点（零本地 GPU 兜底）**：Comfy 账户登录或配 MiniMax API Key，改用云端 API 节点，按秒计费、不占 60h 本地配额，但需付费、不满足「本地 demo」目标。

---

## 9. 关键命令速查

```bash
# 环境确认（含 torch CUDA 版本，定 int8/fp8）
nvidia-smi
python -c "import torch; print(torch.__version__, torch.version.cuda)"

# 启动 ComfyUI（前台）
cd /mnt/workspace/ComfyUI && python main.py --listen 0.0.0.0 --port 8188

# 后台启动
cd /mnt/workspace/ComfyUI && nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &

# 看日志
tail -f /mnt/workspace/ComfyUI/comfy.log

# 检查服务
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188

# 停 ComfyUI（停实例前先跑，避免卡「停止中」）
pkill -f "main.py --listen"

# 终端预拉权重（慢时兜底，走镜像）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download Comfy-Org/MiniMax-H3 \
  --local-dir /mnt/workspace/ComfyUI/models/MiniMax-H3 \
  --include "*pruned_int8_convrot*" "*nvfp4_awq*" "*.fp16*" "*.fp32*" "*turbo*"
```

---

## 10. 停止实例与备份（省钱 + 防丢）

**DSW 实例「运行中」就开始扣 GPU 小时，跟开没开浏览器无关。**

1. 先停 ComfyUI：`pkill -f "main.py --listen"`（避免实例卡「停止中」）。
2. 回 DSW 控制台 → 对实例点 **停止**（立即停止扣费；重启才恢复）。
3. ⚠️ 检查有没有开 **NAT+EIP / 全球加速 / 自定义服务**——它们**停止后仍收费**，demo 阶段没开最好，开了就删。
4. **数据防丢**：容器重启 `/mnt/workspace` 可能清空。两条路任选：
   - 不关机一直烧机时（A10 3.3 机时/小时，18.16 机时 ≈ 5.5 小时实算）；
   - 或下完权重立刻传 **OSS / NAS / ModelScope 仓库** 备份，下次挂载免重下。

---

## 11. 实测成功案例（待跑通后回填）

> 启动 A10、跑通第一段 5s 视频后，把真实提示词、参数、耗时、`T`、片段数估算填到这里。

### 环境（实测）
- GPU：A10 24GB（待回填驱动 / CUDA）
- ComfyUI：v____（待回填）
- torch：`__.__ +cu___`（待回填，定 int8/fp8）

### 第一段视频
| 项 | 值 |
|---|---|
| 模板 | T2V（文生视频） |
| 权重组合 | int8_convrot + nvfp4_awq（或 fp8_scaled，待回填） |
| 分辨率 | 1344 × 768（短边768） |
| 时长 | 5s @ 24fps |
| 步数 | turbo 8 步 |
| 稳态耗时 T | ____ 秒（待回填） |
| 60h 产出估算 | 片段数 ≈ 216000 / T = ____ 条 |

### 说明
- 待回填：是否 OOM、是否触发 offload、A10 24G 实测够不够、换 V100 是否更稳。

---

## 关键参考链接

- 官方本地部署教程：https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3
- H3 官方 GitHub：https://github.com/MiniMax-AI/MiniMax-H3
- ComfyUI 重打包权重：https://huggingface.co/Comfy-Org/MiniMax-H3
- DSW 帮助文档：https://help.aliyun.com/zh/pai/dsw-overview
- 同仓库腾讯云版（Z-Image-Turbo）：`tencent-cloud-comfyui-guide.md`
- 同仓库手动指南（更细）：`minimax-h3-dsw-manual-guide.md`
- 一键脚本：`scripts/deploy_comfyui_h3_dsw.sh`

> 注意：MiniMax H3 受 Community License（地域/用途限制）约束；实例用完请手动停止，避免 NAT+EIP/GA 等独立计费项持续扣费。
