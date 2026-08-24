# 腾讯云 Cloud Studio 跑 ComfyUI 实操指南（已验证版）

> 适用：腾讯云 Cloud Studio（云 IDE workspace，免费 GPU 额度，实测 Tesla T4 15GB）
> 目标：跑起 ComfyUI，用 Z-Image-Turbo / SDXL 学习工作流；**注意 T4 15G 跑不了 MiniMax H3**（见第 6 节）。
> 本文只收录**实测通过**的步骤。

---

## 0. 实测环境

| 项 | 值 |
|---|---|
| 工作目录 | `/workspace`（容器，非 root 专属） |
| Python | 3.11.1（`/root/.pyenv/versions/3.11.1`）✅ ≥3.9 |
| ComfyUI | v0.33.0 ✅ ≥0.30.0（原生含 MiniMax H3 节点） |
| PyTorch | 2.10.0+cu128（CUDA 12.8） |
| GPU | Tesla T4，15GB 显存，驱动 570 / CUDA 12.8 |

---

## 1. 环境确认

```bash
nvidia-smi
python --version
python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

- `nvidia-smi` 能出表格 → 有 GPU；记下显存大小。
- Python ≥3.9 才能装 ComfyUI 依赖（3.7 会报 `comfyui-frontend-package` 装不上）。

---

## 2. 安装 / 更新 ComfyUI

```bash
cd /workspace
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

- 之前装过就更新：`cd /workspace/ComfyUI && git pull --ff-only && pip install -r requirements.txt`
- 检查版本：`git describe --tags`（≥0.30.0 才有 H3 节点；v0.33.0 满足）。
- ⚠️ **别重复 clone**：本机实测因多次 clone 出现三层嵌套副本（`/workspace/ComfyUI/ComfyUI/ComfyUI/`），导致模型目录混乱、UI 报缺失。**只保留一个副本**（见 5.1.1），或 clone 后记准你自己那个目录。

---

## 3. 启动 ComfyUI

```bash
# 从“运行中的实例”目录启动（实测是最深层副本 /workspace/ComfyUI/ComfyUI/ComfyUI，见 5.1.1）
cd /workspace/ComfyUI/ComfyUI/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

看到 `To see the GUI go to: http://0.0.0.0:8188` 说明服务起来了。
- 这个终端**别关**；或后台跑：
  ```bash
  nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &
  ```

---

## 4. 用 cloudflared 暴露公网地址（实测可行）

Cloud Studio 的「端口」面板可以不用，cloudflared 隧道最稳、免注册。

### 4.1 下载官方二进制（实测命令）

⚠️ **不要用 `pip install cloudflared`**——PyPI 上那个 `cloudflared`（1.0.0.2，作者 SigireddyBalaSai）是第三方工具包，**不包含二进制**，装了也找不到 `cloudflared` 命令。官方二进制在 GitHub Releases。

```bash
cd /tmp
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared
./cloudflared --version
```

- 下载完 `ls /tmp` 应看到 `cloudflared`（约 38MB）。
- 显示 `cloudflared version 2026.8.2 ...` 即成功。
- **一次只跑一条命令**，避免长命令被终端换行拆断（拆断的症状：`command not found: -O`、`chmod` 只打印帮助信息、`permission denied`）。

### 4.2 启动隧道（实测命令，在 /tmp 下用相对路径）

```bash
cd /tmp
./cloudflared tunnel --url http://127.0.0.1:8188
```

等 5–10 秒出现：

```
Your quick Tunnel has been created! Visit it at:
https://xxxxxxxx.trycloudflare.com
```

用浏览器打开这个 `https://...trycloudflare.com` 即 ComfyUI 界面。

**注意**：
- 隧道窗口**别关**，关了 URL 立即失效；ComfyUI 服务（`main.py`）也要保持运行。
- 该 URL 是**公开**的，任何人拿到都能访问，别放敏感内容；demo 用途足够。
- 免注册、免费，但无 uptime 保证。
- **每次重启隧道 URL 都会变**，以当次终端打印的为准。

---

## 5. 出第一张图（Z-Image-Turbo，实测路径）

### 5.1 模型下载（重要：别用 UI 的「全部下载」）

⚠️ **实测踩坑**：模板里的「全部下载」会经浏览器**直链下到你本地电脑**，而不是云端服务器。正确做法是**在云端终端手动下载**到对应 `models/` 子目录。

三个文件都在 `Comfy-Org/z_image_turbo` 仓库的 **`split_files/` 子目录**下：

| 仓库内路径 | 大小 | 目标目录 |
|---|---|---|
| `split_files/diffusion_models/z_image_turbo_bf16.safetensors` | 11.46 GB | `models/diffusion_models/` |
| `split_files/text_encoders/qwen_3_4b.safetensors` | 7.49 GB | `models/text_encoders/` |
| `split_files/vae/ae.safetensors` | 319.77 MB | `models/vae/` |

**推荐：wget 直链**（`-O` 直接平铺到目标文件，不会多套一层目录；`-c` 断点续传）。**目标目录直接用运行实例的 models**（`/workspace/ComfyUI/ComfyUI/ComfyUI/models/`，见 5.1.1），一次到位，省去后面再 mv：

```bash
wget -c "https://hf-mirror.com/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors" -O /workspace/ComfyUI/ComfyUI/ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors
wget -c "https://hf-mirror.com/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" -O /workspace/ComfyUI/ComfyUI/ComfyUI/models/text_encoders/qwen_3_4b.safetensors
wget -c "https://hf-mirror.com/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors" -O /workspace/ComfyUI/ComfyUI/ComfyUI/models/vae/ae.safetensors
```

（或 `hf download`，但文件路径**必须带 `split_files/`**，且 `--local-dir` 会保留子目录结构，需要再 `mv` 平铺到目标目录。）

下完验证（一次一条）：
```bash
ls -lh /workspace/ComfyUI/ComfyUI/ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors
ls -lh /workspace/ComfyUI/ComfyUI/ComfyUI/models/text_encoders/qwen_3_4b.safetensors
ls -lh /workspace/ComfyUI/ComfyUI/ComfyUI/models/vae/ae.safetensors
```

说明：
- ⚠️ **关键坑**：仓库文件在 `split_files/` 下，路径不带这层会报 `Error: File not found in repository`（和镜像无关，别取消镜像）。
- `HF_ENDPOINT=https://hf-mirror.com` 或直接写 `hf-mirror.com` 域名即国内镜像（腾讯云直连 HF 慢）。
- 三个文件共约 19GB，下载完成（有进度条、可断点续传）后**刷新 ComfyUI 页面**，「缺失模型」和「无效输入」消失。

### 5.1.1 放对目录（关键坑：多层嵌套副本）

⚠️ **实测踩坑**：这台机器上 ComfyUI 被克隆了**三层**（`/workspace/ComfyUI`、`/workspace/ComfyUI/ComfyUI`、`/workspace/ComfyUI/ComfyUI/ComfyUI`）。**运行中的实例是最深层那个**（启动日志里 `custom_nodes` 路径含 `/workspace/ComfyUI/ComfyUI/ComfyUI/`），它只读 `/workspace/ComfyUI/ComfyUI/ComfyUI/models/`。模型放到别的层，UI 会一直报「缺失模型」。

排查（确认运行实例读哪个 models 目录）：
```bash
find /workspace -maxdepth 4 -name "models" -type d
ls -l /proc/$(pgrep -f "main.py" | head -1)/cwd
```

修复：5.1 的 wget 已**直接写到运行实例目录**，不用再搬。若你的文件已经下到了别处（如更早版本写的 `/workspace/ComfyUI/models/`），用下面的 `mv` 搬到正确目录（`mv` 省磁盘，避免 20GB 重复），再重启 ComfyUI 刷新页面：
```bash
mkdir -p /workspace/ComfyUI/ComfyUI/ComfyUI/models/vae \
         /workspace/ComfyUI/ComfyUI/ComfyUI/models/text_encoders \
         /workspace/ComfyUI/ComfyUI/ComfyUI/models/diffusion_models
mv /workspace/ComfyUI/models/vae/ae.safetensors /workspace/ComfyUI/ComfyUI/ComfyUI/models/vae/
mv /workspace/ComfyUI/models/text_encoders/qwen_3_4b.safetensors /workspace/ComfyUI/ComfyUI/ComfyUI/models/text_encoders/
mv /workspace/ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors /workspace/ComfyUI/ComfyUI/ComfyUI/models/diffusion_models/
```

建议：**删掉多余的嵌套副本，只留运行中的那个**，避免以后再次放错目录。

### 5.2 跑第一张图

1. 模板库 → 图片 → **Z-Image-Turbo**（Text to Image）模板。
2. 三个模型就位后，填提示词（支持中英文），点 **Run**。
3. T4 15G 跑 bf16（11.46GB）显存较紧：若报 `CUDA out of memory`，降分辨率到 **512×512**，或用 `--lowvram` 重启 ComfyUI。
4. 仍 OOM → 换量化版省显存：扩散换 `z_image_turbo_nvfp4.safetensors`，文本编码器换 `qwen_3_4b_fp8_mixed.safetensors`。

---

## 6. 关于 MiniMax H3（T4 跑不了，先说清楚）

- **T4 15G 不满足 H3 最低门槛**：最小文本编码器（Qwen3-VL-32B 的 `nvfp4_awq`）≈16GB 就已超过 15GB 显存，fp8_scaled 扩散模型也要 ~10–20GB。
- 即便量化 + offload 硬跑，几乎整个模型常驻内存、每层走 PCIe 搬运，速度是**小时级/片段**，demo 意义为零。
- H3 的正确环境：**≥24GB 单卡**（ModelScope 免费 24G / AutoDL 等 4090 24G 时租），或 **Comfy Cloud 官方 5 次免费运行**（Blackwell 96G）。
- T4 上就用 **Z-Image-Turbo / SDXL / Flux 量化版**练手。

---

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| `command not found: cloudflared` | 二进制没装对：先 `ls /tmp \| grep cloudflared` 确认文件在，再 `cd /tmp && chmod +x cloudflared` |
| `permission denied: /tmp/cloudflared` | 文件没执行权限：`cd /tmp && chmod +x cloudflared` |
| `chmod` 只打印帮助信息 | 命令被拆断（chmod 后没带参数）：一次只粘一条命令 |
| 命令被拆断（`command not found: -O` 等） | 一次只粘一条命令，长 URL 分步跑 |
| 网页打不开 | ① ComfyUI 终端在跑？`curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188` 应返回 200；② cloudflared 终端在跑？关了会失效 |
| 模板「全部下载」下到本地电脑 | 取消浏览器下载；改为在云端终端手动下载（见 5.1） |
| `hf` / `huggingface-cli` 报 deprecated | 新版用 `hf` 命令，语法一样：`hf download <repo> <文件> --local-dir <目录>` |
| `Error: File not found in repository` | 仓库文件在 `split_files/` 子目录，路径要带 `split_files/`（见 5.1）；与镜像无关，别取消镜像 |
| 模型文件在，但 UI 仍报「缺失模型」 | 放错目录了：这台机有**三层嵌套副本**，运行实例只读最深层 `/workspace/ComfyUI/ComfyUI/ComfyUI/models/`，把文件 `mv` 过去并重启（见 5.1.1） |
| `pip install cloudflared` 后命令不存在 | 那是第三方包，`pip uninstall -y cloudflared` 卸掉，按 4.1 下载官方二进制 |
| 模型下载慢 | HF 直连慢，可设 `HF_ENDPOINT=https://hf-mirror.com` 重试，或改 ModelScope 渠道 |

---

## 8. 关键命令速查

```bash
# 环境确认
nvidia-smi

# 启动 ComfyUI（前台；用运行实例目录，实测为最深层副本）
cd /workspace/ComfyUI/ComfyUI/ComfyUI && python main.py --listen 0.0.0.0 --port 8188

# 后台启动
cd /workspace/ComfyUI/ComfyUI/ComfyUI && nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &

# 暴露公网（新终端，别关）
cd /tmp && ./cloudflared tunnel --url http://127.0.0.1:8188

# 检查服务
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188
```

---

## 9. 关闭/重启工作区：要不要重来？（实测结论）

**环境与数据会保留，进程不会，URL 会变。**

| 项 | 停止后 | 说明 |
|---|---|---|
| 代码 / pip 环境 / pyenv | ✅ 保留 | 存在工作区磁盘 |
| 模型（约 19GB） | ✅ 保留 | 不用重新下载 |
| ComfyUI / cloudflared 进程 | ❌ 被杀 | 需重新启动 |
| trycloudflare URL | ❌ 会变 | 每次起隧道生成新地址 |

**快速恢复（重开工作区后 4 步）**：

```bash
# 1) 启动 ComfyUI（后台，用运行实例目录）
cd /workspace/ComfyUI/ComfyUI/ComfyUI
nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &

# 2) 起隧道（新终端，别关）
cd /tmp
./cloudflared tunnel --url http://127.0.0.1:8188

# 3) 用新打印的 https://xxx.trycloudflare.com 打开 UI
```

- 唯一例外：**删除工作区**（或免费额度长期过期被平台回收）才会丢数据，以控制台提示为准。
- 检查服务：`curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188`（应返回 200）。

---

## 10. 实测成功案例（Z-Image-Turbo，腾讯云 T4）

第一次完整跑通的工作流记录，作为后续出图参考。

### 提示词
```
Latina female with thick wavy hair, harbor boots and pastel houses behind. Breezy seaside light, warm tones, cinematic close-up.
```

### 参数
| 项 | 值 |
|---|---|
| 模型（unet） | `z_image_turbo_bf16.safetensors` |
| 文本编码器（clip） | `qwen_3_4b.safetensors` |
| VAE | `ae.safetensors` |
| 分辨率 | 1024 × 1024 |
| 步数（steps） | 8 |
| 种子（seed） | 438971436169610 |
| 设备 | Tesla T4 15GB（CUDA 12.8） |

### 结果
- **耗时**：65.17 秒
- **输出文件**：`z-image-turbo_00001_.png`（1024×1024 PNG）
- **画面**：人物肖像（卷发、海港靴、背景彩色房屋、海边暖色调、近景特写），质量稳定，T4 单卡可跑

### 说明
- 8 步是 Z-Image-Turbo 的**典型配置**（本就为少量步数设计）；用更少步数（如 4 步）速度会更快但质量略降。
- 1024×1024 在 T4 15G 上没报 OOM（bf16 11.46GB + qwen3 4B 文本编码器 + ae VAE 略接近上限但可运行）。若换更高分辨率（如 1280×1280）有 OOM 风险，按 5.2 的建议降分辨率或加 `--lowvram`。
- 想复现同一张图：**固定 seed 即可**（`438971436169610`）；换图改 seed。
- 生成的图片默认保存在 `output/` 目录，可在 Save Image 节点改路径。
