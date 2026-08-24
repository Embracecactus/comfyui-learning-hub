# 腾讯云 GPU 云服务器跑 MiniMax H3 实操指南（撰写版）

> 适用：腾讯云 **GPU 云服务器（CVM）**，单卡 **≥24GB 显存**（A10 24G / V100 32G / L20 48G），按量或包年包月。
> 目标：单卡跑通 **ComfyUI + MiniMax H3** 视频 demo；验证可行性、测速、估算成本。
> ⚠️ 本文**按腾讯云 GPU 云服务器撰写**，结构对齐 `tencent-cloud-comfyui-guide.md`；H3 实测步骤**待你在实例上跑通后回填**到第 0 / 11 节。控制台具体选项以腾讯云当前页面为准。
> 与 Cloud Studio 免费版的区别：Cloud Studio 免费是 T4 15G（跑不了 H3，见 `tencent-cloud-comfyui-guide.md` 第 6 节）；本文用**付费的 ≥24G 卡**，能跑 H3。

---

## 0. 实测环境（待购买并跑通后回填）

| 项 | 目标值 / 说明 |
|---|---|
| 平台 | 腾讯云 GPU 云服务器（CVM），实例「运行中」即计费 |
| 实例规格 | **A10 24G**（GNV4）为甜点；**V100 32G**（GN10X）更稳；**L20 48G** 宽松 |
| 镜像 | 选**带 CUDA 的 GPU 公共镜像**（Ubuntu / TencentOS），省去手装驱动 |
| 系统盘 | CBS 云硬盘，**关机/重启都保留**；释放实例并勾选释放云盘才丢（比 DSW 容器持久） |
| ComfyUI | ≥0.30.0（原生含 MiniMax H3 节点） |
| PyTorch / CUDA | `int8_convrot` 权重需 **torch 带 cu130**；CVM 可自行 `pip install torch --index-url ...cu130` |
| 显存门槛 | ≥24GB 直跑；16–24GB 依赖 int8 + nvfp4 量化 + offload；<16GB 没戏 |

> **实测环境（用户当前机器，2026-08-24）**：腾讯云 **A10 24G**（23028 MiB），驱动 580.65 / CUDA 13.0（驱动层），**torch 2.10.0+cu128（CUDA 12.8）**，Python 3.11.1。→ torch **非 cu130**，故 H3 权重用 **`fp8_scaled`** 版（场景 B）；若想用 `int8_convrot`，需先 `pip install -U torch --index-url https://download.pytorch.org/whl/cu130`。

> CVM 优势：系统盘持久（模型下次开机免重下）、环境自定（可装 cu130 torch 跑 int8_convrot）、有公网 IP。代价：按量计费、需自己配安全组/驱动。

---

## 1. 购买与开机（控制台操作）

1. 腾讯云控制台 → **云服务器 CVM** → **新建实例**。
2. 机型选 **GPU 计算型**，规格挑 ≥24G（A10 24G 起步；预算够直接 V100 32G / L20 48G）。
3. 镜像：**公共镜像**里选 Ubuntu / TencentOS，并勾选 **GPU 驱动 / CUDA 预装**（若提供）；否则选普通镜像，开机后手动装驱动（见下方备注）。
4. 存储：系统盘选云硬盘（默认持久），**容量 ≥100GB**（H3 权重 50–80GB + ComfyUI + 系统）。
5. 网络：勾选 **分配公网 IP**；带宽按量计费或包月（demo 用按量小额即可）。
6. 安全组：先放通 **SSH(22)**；Web 端口 8188 后面再开（或用 cloudflared 隧道，不开端口更安全，见第 4 节）。
7. 计费：选**按量计费**（小时结）最灵活；用完**关机**可停 GPU 费（按量且开启「关机不收费」时 GPU 不计费，仅系统盘+IP 仍计）。
8. 开机后，用**控制台登录 / SSH（公网 IP 或 VNC）**进系统。

> 驱动备注：若镜像没预装 CUDA，按腾讯云文档装 NVIDIA 驱动 + CUDA（`nvidia-smi` 能出表即可）。或重装一个「GPU 镜像市场的 CUDA 镜像」最省事。

---

## 2. 环境确认

SSH 进实例后：

```bash
nvidia-smi
free -h
df -h /
python --version
python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

- `nvidia-smi` 出表格 → 确认是 A10/V100/L20、显存大小。
- `free -h` 看内存（H3 offload 需 ≥32GB；V100/A10 实例一般给到）。
- `torch.version.cuda`：`13.0` 可用 `int8_convrot`；否则 `pip install -U torch --index-url https://download.pytorch.org/whl/cu130` 升级后再用 int8。
- 若没装 torch / ComfyUI 还没下，继续第 3 节。

---

## 3. 安装 / 更新 ComfyUI

```bash
cd /workspace
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

> 路径说明：本文 ComfyUI 统一装在 **`/workspace/ComfyUI`**（你的实际环境即此路径）。若你装在别处（如 `~/ComfyUI`、`/mnt/workspace/ComfyUI`、或 CVM 的数据盘），**全文把 `/workspace/ComfyUI` 换成你的实际路径**即可，下面所有命令同理。

- 之前装过就更新：`cd /workspace/ComfyUI && git pull --ff-only && pip install -r requirements.txt`
- 检查版本：`git describe --tags`（≥0.30.0 才有 H3 节点）。
- ⚠️ **别重复 clone**：只保留一个 `/workspace/ComfyUI`，避免多层嵌套副本导致模型目录混乱（同 `tencent-cloud-comfyui-guide.md` 5.1.1 的坑）。

---

## 4. 启动 ComfyUI + 暴露公网

### 4.1 启动

```bash
cd /workspace/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

看到 `To see the GUI go to: http://0.0.0.0:8188` 说明服务起来。后台跑（关终端也能续）：

```bash
cd /workspace/ComfyUI
nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &
tail -f comfy.log
```

- 停实例前先结束进程：`pkill -f "main.py --listen"`（避免卡关机）。

### 4.2 暴露公网（二选一）

**方式 A（推荐，安全）：cloudflared 隧道**——不开安全组端口、不裸奔公网、免注册。

```bash
cd /tmp
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared
./cloudflared tunnel --url http://127.0.0.1:8188
```

出现 `https://xxxxxxxx.trycloudflare.com` 即访问地址（每次重启会变）。详细坑见 `tencent-cloud-comfyui-guide.md` 第 4 节。

**方式 B（直接公网 IP）**：安全组放通 **8188 入站** → 浏览器开 `http://<公网IP>:8188`。
- ⚠️ ComfyUI **无鉴权**，公网裸奔任何人可滥用；demo 可接受，正式用请加反向代理 + 密码（nginx basic auth / `--listen` 配隧道）。

---

## 5. 加载 MiniMax H3 + 下载权重

浏览器 Web UI 内操作（同 DSW 流程）：

1. 左侧 **模板库（Templates）** → **视频（Video）** → **MiniMax H3**。
2. 选 **T2V**（先验证链路）/ **I2V** / **R2V**。
3. 弹窗「缺少模型」→ 点**下载**，权重自动从 `Comfy-Org/MiniMax-H3` 拉取并放对目录。
4. 下载完画布出现完整节点图。

### 5.1 权重组合（先按第 2 步 torch.cuda 选）

**场景 A：`torch.version.cuda == 13.0`**（推荐，CVM 可自行装 cu130）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_int8_convrot.safetensors
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors   ← 无需 Blackwell 显卡
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

**场景 B：`torch.version.cuda != 13.0`**（用 fp8_scaled）
```
models/diffusion_models/ minimax_h3_fl2va_pruned_fp8_scaled.safetensors
models/text_encoders/    qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
models/vae/              minimax_h3_video_vae_fp16.safetensors
models/vae/              minimax_h3_audio_vae_fp32.safetensors
models/loras/            minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
```

要点：
- **文本编码器一律选 `nvfp4_awq`**（约 16GB，无需 Blackwell）；`bf16` 版 ~64GB **别下**。
- **`pruned_` 剪枝版更小**，A10 24G 优先。
- 下载慢：模板库走 HF，可换 `HF_ENDPOINT=https://hf-mirror.com` 或用 CLI 预拉（5.2）。

### 5.2 终端预拉权重（模板库慢时兜底，按场景选）

> 首选仍是 **5.1 的模板库一键下载**（自动放对目录，最稳）。下面仅当模板库太慢时用，需手动指定子目录，且文件名/路径以 HF 仓库实际为准。
> ⚠️ `huggingface-cli` 已**废弃不可用**，新命令是 **`hf`**（同参数）。仓库若 gated（需接受 MiniMax Community License），先 `hf auth login` 登录 HF token 再下。

**先列真实文件路径（避免 wget 404）**：
```bash
HF_ENDPOINT=https://hf-mirror.com hf download Comfy-Org/MiniMax-H3 --dry-run 2>&1 | tail -40
```
（直连 HF 把 `HF_ENDPOINT=` 去掉即可；gated 仓库此处会提示 401/需登录）

**场景 B（fp8_scaled，当前实测 torch cu128）**：
```bash
pip install -q -U "huggingface_hub[cli]"
REPO=Comfy-Org/MiniMax-H3
BASE=/workspace/ComfyUI/models
HF_ENDPOINT=https://hf-mirror.com

hf download "$REPO" minimax_h3_fl2va_pruned_fp8_scaled.safetensors --local-dir "$BASE/diffusion_models"
hf download "$REPO" qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors --local-dir "$BASE/text_encoders"
hf download "$REPO" minimax_h3_video_vae_fp16.safetensors --local-dir "$BASE/vae"
hf download "$REPO" minimax_h3_audio_vae_fp32.safetensors --local-dir "$BASE/vae"
hf download "$REPO" minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors --local-dir "$BASE/loras"
```

下载完校验（每条应在对应子目录，**不要多套一层**）：
```bash
ls -lh /workspace/ComfyUI/models/diffusion_models /workspace/ComfyUI/models/text_encoders /workspace/ComfyUI/models/vae /workspace/ComfyUI/models/loras
```

**场景 A（int8_convrot，需 torch cu130）**：把第一行换成 `minimax_h3_fl2va_pruned_int8_convrot.safetensors` 即可，其余同场景 B。

> 若 `hf download` 报 `File not found`，说明仓库内文件名/路径不同：先去 https://huggingface.co/Comfy-Org/MiniMax-H3 核对实际文件名，或**直接用模板库下载**（它会按正确路径拉，最省心）。
> 体积参考：文本编码器 nvfp4_awq ≈16GB，fp8_scaled 扩散 ≈10–20GB，两个 VAE 几个 GB，turbo LoRA 几百 MB——合计约 **30–40GB**，下前先 `df -h /workspace` 确认磁盘够（≥100GB 为宜）。

> CVM 系统盘持久，**权重下完关机也还在**，下次开机免重下——这是比 DSW 容器大的优势。

---

## 6. 关于显存门槛（A10 24G 够不够）

- **A10 24G（int8_convrot + nvfp4_awq + pruned）可直跑** H3 最小片段（5s / 短边768）。
- 仍 OOM：降分辨率到短边 512 / 时长 3s；或依赖 ComfyUI 自动 offload；或直接上 **V100 32G / L20 48G**。
- <16GB（T4 15G）没戏——见 `tencent-cloud-comfyui-guide.md` 第 6 节。

---

## 7. 跑第一段视频（验证 + 测速）

| 参数 | 值 |
|---|---|
| 分辨率 | **短边 768px**（16:9 → 1344×768） |
| 时长 | **5 秒** @ 24fps |
| 步数 | 开 `turbo_mode`，**8 步** |
| seed | 固定数字（复现用） |

点 **Run**，等完成。测速：
1. 第一次含模型加载 =「冷启动」，**不计入**。
2. 第二次起记**稳态**耗时 `T`（秒）。
3. 公式：`秒/帧 = T / 120`；**总视频时长 ≈ (运行时长 / T) × 5 秒**（运行时长 = 实例开机小时 × 3600）。

> CVM 是**按量计费**不是固定配额：把「60h 配额」换成「成本估算」——**成本 ≈ 实例单价(元/小时) × 开机小时数**（另加公网带宽费）。买前在控制台看 A10/V100 单价填入下表。

---

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| 节点是红的 / 找不到 H3 节点 | ComfyUI <0.30.0，`git pull` 更新后重启 |
| 量化算子报错（int8 相关） | torch 非 cu130，`pip install -U torch --index-url ...cu130` 或换 `fp8_scaled` |
| `CUDA out of memory` | 降分辨率/时长；或升 V100/L20；仍 OOM 见第 6 节 |
| Sage Attention `using pytorch attention instead` | 正常现象，不影响出视频 |
| 模型下载慢 | `HF_ENDPOINT=https://hf-mirror.com` 或 ModelScope |
| 文本编码器体积爆炸 | 下成 `bf16` 版(~64GB)，删掉改 `nvfp4_awq` |
| 公网打不开 | 方式 A：cloudflared 在跑？方式 B：安全组 8188 放通？`curl ... 127.0.0.1:8188` 应 200 |
| `nvidia-smi` 不可用 | 驱动没装；重装 CUDA 镜像或按腾讯云文档装驱动 |
| 公网 IP 裸奔风险 | 用 cloudflared 隧道（方式 A）或加反向代理 + 密码 |

---

## 9. 关键命令速查

```bash
# 环境确认
nvidia-smi
python -c "import torch; print(torch.__version__, torch.version.cuda)"

# 启动 ComfyUI（前台）
cd /workspace/ComfyUI && python main.py --listen 0.0.0.0 --port 8188

# 后台启动
cd /workspace/ComfyUI && nohup python main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &

# 暴露公网（cloudflared，新终端别关）
cd /tmp && ./cloudflared tunnel --url http://127.0.0.1:8188

# 检查服务
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188

# 停 ComfyUI
pkill -f "main.py --listen"

# 预拉权重（走镜像）
HF_ENDPOINT=https://hf-mirror.com hf download Comfy-Org/MiniMax-H3 \
  --local-dir /workspace/ComfyUI/models/MiniMax-H3 \
  --include "*pruned_int8_convrot*" "*nvfp4_awq*" "*.fp16*" "*.fp32*" "*turbo*"
```

---

## 10. 停止实例与计费（省钱 + 防丢）

**CVM「运行中」即计费；关机可停 GPU 费，但系统盘/IP 可能仍计。**

1. 先停 ComfyUI：`pkill -f "main.py --listen"`。
2. 控制台对实例点 **关机**（按量且开「关机不收费」时 GPU 不计费；包年包月照常计）。
3. 不用的公网 IP / 带宽包也释放，避免持续计费。
4. **数据安全**：系统盘(CBS)关机/重启都保留，权重免重下；只有**释放实例并勾选释放云盘**才丢。相比 DSW 容器（关机即清），CVM 持久性更好——可放心关机省费。
5. 彻底不要了再**销毁/释放**实例与云盘。

---

## 11. 实测成功案例（待跑通后回填）

> 购买 A10/V100 实例、跑通第一段 5s 视频后，回填真实值。

### 环境（实测）
- 实例规格：____（A10 24G / V100 32G / L20 48G）
- 镜像 / 驱动 / CUDA：____
- ComfyUI：v____
- torch：`__.__ +cu___`（定 int8/fp8）

### 第一段视频
| 项 | 值 |
|---|---|
| 模板 | T2V |
| 权重组合 | int8_convrot + nvfp4_awq（或 fp8_scaled） |
| 分辨率 | 1344 × 768 |
| 时长 | 5s @ 24fps |
| 步数 | turbo 8 步 |
| 稳态耗时 T | ____ 秒 |
| 单价 | ____ 元/小时（控制台查） |
| 成本估算 | 单价 × 开机小时 |

---

## 关键参考链接

- 官方本地部署教程：https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3
- H3 官方 GitHub：https://github.com/MiniMax-AI/MiniMax-H3
- ComfyUI 重打包权重：https://huggingface.co/Comfy-Org/MiniMax-H3
- 腾讯云 GPU 云服务器：https://cloud.tencent.com/product/gpu
- 同仓库对照：
  - `tencent-cloud-comfyui-guide.md`（Cloud Studio 免费 T4，Z-Image-Turbo，已验证）
  - `h3-dsw-a10-guide.md`（阿里云 PAI DSW A10 24G，H3）
  - `minimax-h3-dsw-manual-guide.md`（H3 手动细指南）

> 注意：MiniMax H3 受 Community License（地域/用途限制）约束；CVM 公网暴露务必加访问限制，避免被滥用持续扣费。
