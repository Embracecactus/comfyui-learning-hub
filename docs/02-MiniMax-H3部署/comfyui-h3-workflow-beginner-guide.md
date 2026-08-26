# ComfyUI MiniMax H3 工作流逐节点详解（新手版）

> 配套阅读：[腾讯云 H3 部署](h3-tencent-gpu-cvm-guide.md)、[腾讯云 ComfyUI 基础](tencent-cloud-comfyui-guide.md)
> 目标读者：懂 ML 基本概念（扩散模型、量化、显存），但**第一次用 ComfyUI** 的人
> 本文逐节点拆解你截图里那个 **MiniMax H3 fl2va（首末帧图生视频）** 工作流，照着读一遍就能理解每条线、每个参数的含义

---

## 0. 这是什么（一句话）

ComfyUI 是一个**节点式**的 AI 图像/视频生成界面。你把不同的"处理单元"（节点）用线连起来，组成一个**工作流（workflow）**；数据从左流到右，最终出图或出视频。

你截图里这个工作流的功能是：**给一张产品图（透明游戏鼠标）+ 一段详细描述 → 生成 5 秒带立体声的产品展示视频**，模型用 MiniMax H3。

---

## 1. ComfyUI 三个核心概念

理解这三样，整张截图就看得懂了：

### 1.1 节点（Node）
屏幕上那些**方框**就是节点。每个节点只做一件事：
- `Load Image`（加载图像）：从硬盘读一张图
- `MiniMaxH3ImageToVideo`（H3 主节点）：吃图 + 提示词，跑 H3 模型，出视频
- `Save Video`（保存视频，默认在画布最右或自动保存）：把生成的视频写盘

### 1.2 连线（Connection）
节点之间那些**细线**就是连线，传递数据。规则：
- 从一节点的**输出**（右侧小圆点）出发
- 连到另一节点的**输入**（左侧小圆点）
- 一根线只传一种类型的数据（图像/视频/数字/模型...），类型不匹配连不上

### 1.3 参数（Widget）
节点**内部**的输入框、下拉、滑动条——你调它们控制节点行为，比如提示词、步数、种子、模型选择。

### 颜色约定（看连线小圆点）
- 🟢 **绿色** = 图像（IMAGE）或视频（VIDEO）—— 这是 H3 主节点和 Load Image 用的
- 🔵 **蓝色** = 数值/整数（INT/FLOAT）—— 分辨率、步数、时长
- 🟡 **黄色/橙色** = 模型（MODEL）/ 条件（CONDITIONING）/ 潜在空间（LATENT）
- ⚪ **白色/灰色** = 字符串（STRING）、开关（BOOLEAN）、下拉（COMBO）

你截图里 Load Image 出来的那根**蓝绿色细线**，从 `IMAGE` 输出连到右边 H3 节点的 `first_frame`（VIDEO 输入）——尽管一端标 IMAGE、另一端标 VIDEO，H3 节点内部会自动把它当作首帧用（按官方说明，fl2va 模式接 first_frame/last_frame 即可）。

---

## 2. 节点逐一拆解（按位置）

### 2.1 最左：`Note: Model Links`（模型清单注释）
**这不是节点，是一个"便签"**（右键画布 → Add Note / 添加注释，纯文字说明）。它列出了这个工作流**需要的全部模型文件**以及它们应该放的目录：

| 类型 | 文件 | 放哪 |
|---|---|---|
| Input Assets（输入素材） | `transparent_rgb_gaming_mouse.png` | `input/`（你截图里 Load Image 加载的就是它） |
| vae | `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` |
| vae | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` |
| diffusion_models | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/` |
| text_encoders | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` |
| loras | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | `models/loras/` |
| loras | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` | `models/loras/` |

下面那张**目录树缩略图**画出了 ComfyUI 期望的文件摆放位置。**少了哪个文件，UI 加载时会在对应模型字段显示红字「missing」**。

### 2.2 左中：`Note: MiniMax H3`（模型介绍注释）
另一个便签。内容翻译要点：

- **MiniMax H3 是什么**：通用、**全模态**生成模型——能看文字/图像/视频/音频，能生成**带原生立体声**（人声/音效/音乐）的视频，最长约 15 秒、最多 2K 分辨率。
- **本工作流做什么**：调用 `MiniMaxH3ImageToVideo` 节点，支持两种模式：
  - **t2va**（text-to-video-audio）：没接图时，**纯文生视频+音频**
  - **fl2va**（first/last-frame-image-to-video）：接了 first_frame 和/或 last_frame 时，**图生视频**（你截图就是这种）
- **关键输入**（下面 H3 主节点的字段）：
  - `first_frame` / `last_frame`：可选**关键帧**（首帧/末帧）
  - `prompt`：用一段话**同时描述画面、动作、音频**（H3 把它们打包处理）
  - `width` / `height`：H3 原生画布 768×768，**最长边上限 768×1344**，必须是 32 的倍数
  - `duration`（秒）：会被换算成帧数，按 17 帧一块对齐（17k+5）在 24fps 下

### 2.3 红色框左：`加载图像`（Load Image）
最基础的输入节点。
- **图像**：当前已加载 `transparent_rgb_gaming_mouse.png`（透明背景的游戏鼠标产品图）
- **选择文件上传**：换图按钮
- 右侧输出 `IMAGE`（绿点）→ 一根线连到右边 H3 主节点的 `first_frame` 输入

> 如果你想做 **t2va（纯文生视频）**，把 Load Image 删掉、不接 first_frame 即可，节点会自动切成 t2va 模式。

### 2.4 `分辨率选择器`（自定义/小工具节点）
把"宽高比 + 像素总量"换算成具体的 width / height，避免手算。
- **宽高比**：1:1 (Square) → 出正方形
- **百万像素**：0.4 → 大约 40 万像素（0.4 Mpx）
- **倍数**：32 → 输出尺寸取 32 的整数倍（H3 硬性要求）

结果：会输出两个 INT（宽、高）。看 2.6 的表能查 0.4 Mpx 在 16:9 下是 864×480。

> 这种"小工具"节点是 ComfyUI 的精髓——**把常用计算抽出来、可视化、可复用**。不需要的可以删，自己在 H3 节点上手填 width/height 也行。

### 2.5 蓝色选中框：`Use Image Size` / `缩放图像（像素）`（图像尺寸工具）
你截图里**蓝框高亮选中**说明你正在编辑这个节点。功能：
- 读取图像的**原始尺寸**（你那张鼠标图原始多大）
- 按 `像素数量` 比例（0.90 = 90%）**缩放**
- 缩放算法：nearest-exact（一种重采样方式，H3 通常用 bilinear/lanczos 也行）
- 步长 32
- `获取图像尺寸` 子节点：再把缩放后的 width/height 输出

这串节点链路是：**Load Image → 缩放 → 拿到对齐 32 的尺寸 → 喂给 H3 主节点的 width/height 输入**。这样你换图就自动按比例对齐，不用手改。

### 2.6 `Note: Size Settings Reference`（尺寸速查表）
便签里那张**megapixels / Aspect / Output** 三列表，是 0.2–0.98 Mpx × 16:9 的实际像素数：
- 0.2 → 608×352
- 0.4 → 864×480
- 0.6 → 1056×608
- 0.8 → 1216×672
- **0.98 → 1344×768（官方 768p 上限）**

挑一个填进"分辨率选择器"的百万像素就行。

### 2.7 右侧红框：`MiniMax H3` 主节点（核心）
**这是整个工作流的心脏**。它把图 + 提示词 + 模型 + 参数全吃进去，跑 H3，出视频。逐个字段解释（按你截图里看到的顺序）：

| 字段 | 截图里的值 | 含义 |
|---|---|---|
| `first_frame` | （来自 Load Image 的线） | 首帧图。接了就是 fl2va 模式；不接就是 t2va |
| `last_frame` | （空） | 末帧图。**不接**=只给定首帧（first-frame-to-video）；**接**=首末帧都给定（fl2v） |
| `prompt` | （右侧大段文字：editorial tech product film, transparent gaming mouse...） | **画面+动作+音效**的混合描述（见 3.1） |
| `width` / `height` | （来自"Use Image Size"链） | 输出视频分辨率。必须是 32 倍数，且 ≤ 768×1344 |
| `duration` | **5.0** 秒 | 视频时长 |
| `noise_seed` | **757358868076805** | 随机种子。**固定它** → 同配置必出同一段视频；改它 → 换内容 |
| `unet_name` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | **主模型**（扩散/UNet）。**见第 4 节** |
| `clip_name` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | **文本编码器**（理解 prompt），约 16GB，无需 Blackwell |
| `vae_name` | `minimax_h3_video_vae_fp16.safetensors` | **视频 VAE**（像素↔潜空间转换） |
| `audio_vae` | `minimax_h3_audio_vae_fp32.safetensors` | **音频 VAE**（H3 独有，给视频配立体声） |
| `turbo_mode` | **false** | 加速开关。**关**也用了 turbo LoRA，见下 |
| `lora_n...` | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | **Turbo LoRA**：小模型，叠在主模型上让 8 步就出好结果（通常要 30+ 步） |
| `turbo_model_strength` | **1.00** | LoRA 强度（0–1）。1.0 = 全开 |
| `turbo_steps` | **8** | 采样步数。配合 turbo LoRA 用 8 步就能稳定出片 |

> **turbo_mode=false 的含义**：你截图里 turbo_mode 是关，但 **lora 字段照样加载了 turbo LoRA，turbo_steps=8 也在跑**。H3 这个工作流的设计是：把 LoRA 加载交给 unet_name 流程，turbo_mode 是另一种"是否启用 turbo 推理路径"的开关（可能涉及 sampler 切换）。新手阶段先按默认值跑，能出片就 OK。

---

## 3. 关键概念深一点讲

### 3.1 Prompt（提示词）怎么写
H3 的 prompt 和 SD/Flux 不一样——它**把画面和音频塞在同一段话里**。看截图那段 prompt 的结构（拆开看）：

```
[画面风格]  editorial tech product film. The transparent gaming mouse from
           <Picture 1> in its original scene: a pitch-black studio void
           with a dark, subtle reflective surface. ...
[动作/运镜]  Drift by dynamic fencers silver blue and warm neon orange ...
            slow, deliberate push-in to reveal the intricate circuitry. ...
[材质/光影]  The environment is constant throughout: 80% P. 01 to 1.6 ...
[音频]       deep pulsing sub-bass room tone, sharp tactile mechanical
            clicks, a sweeping glassy whoosh on cuts, and a rising
            electronic swell that resolves to near-silence on the final
            fade. Pensive, weightless; a few seconds above the dark
            reflective surface, rotating in a slow, precise orbit...
```

**写法要点**：
- 一段话写到底，不要分"positive/negative"（H3 工作流里没有 negative prompt）
- 画面 + 动作 + 音效 顺序写，模型会自己解析
- 关键帧（first_frame/last_frame）不用在 prompt 里描述图本身——模型会看图，prompt 只描述**它要"动起来"的过程和声音**

### 3.2 Seed（种子）为什么重要
- `noise_seed` 是个 18 位的巨大整数，**决定初始噪声**。
- 同一组参数 + 同 seed → 必出**像素级一致**的视频
- 想要"换一张但类似风格" → 改 seed 末几位；想要"完全换内容" → 改大数
- 出片好但又想微调 → **只改 prompt，固定 seed**；出片风格不理想 → 改 seed

### 3.3 步数（Steps）vs Turbo
- 普通扩散：30–50 步
- 配 turbo LoRA：4–8 步就能出好结果（速度提升 4–8 倍）
- 你截图 turbo_steps=8 + turbo LoRA + 强度 1.0 = **快模式**

### 3.4 分辨率和时长的硬性约束
- **width × height** ≤ 768 × 1344，且都是 32 倍数（768, 800, 832, ..., 1344）
- **duration**（秒）会被换算成 24fps 下的帧数，按 **17k+5** 对齐：
  - 5s → 120 帧 → 不满足 17k+5（17×7+5=124）→ 实际会被 snap 到 7.0s（124帧）
  - 想严格 5s 看到的是 H3 内部 snap 后的值
  - 短边 768 是"甜点"——再小模型质量降，再大容易 OOM

### 3.5 模型字段（unet / clip / vae）到底在选什么
- **unet_name**（主扩散模型）：学过的"画风/内容"主力。**这是显存大头**（21G/卷）
- **clip_name**（文本编码器）：把 prompt 文字翻译成模型能懂的向量。15.7G，**总是被 offload 到内存**（吃 RAM）
- **vae_name**（视频 VAE）：像素 ↔ 潜空间 编/解码
- **audio_vae**：H3 独有，处理音频维度
- **lora**：小插件模型，叠在主模型上微调行为。这里是 turbo LoRA

---

## 4. 关键警告：你这台机器要先改这个

Model Links 注释和工作流里 `unet_name` 字段都用了：
```
minimax_h3_fl2va_pruned_int8_convrot.safetensors
```
这个 `int8_convrot` 量化算子**只支持 torch 带 CUDA 13.0（cu130）**。

**你环境实测是** `torch 2.10.0+cu128`（CUDA 12.8），跑 int8_convrot 会报量化算子错误。

**两条路任选**：
- **A. 换模型**（推荐，省时间）：把 `unet_name` 字段改成
  `minimax_h3_fl2va_pruned_fp8_scaled.safetensors`（fp8_scaled，兼容 cu128）。
  H3 节点通常在 unet_name 字段直接下拉切换，或在模型选择框里搜 fp8_scaled。
- **B. 升级 torch**：另开终端跑
  ```
  pip install -U torch --index-url https://download.pytorch.org/whl/cu130
  ```
  再重启 ComfyUI（`pkill -f "main.py --listen"` 后重起）。耗时长、且可能让 ComfyUI 其它依赖打架。

**跑之前先确认模型目录里有 fp8_scaled 文件**（你之前 5.2 节 wget 的是 fp8_scaled，44.5GB 那一组是对的）：

```bash
ls -lh /workspace/ComfyUI/models/diffusion_models
# 应有 minimax_h3_fl2va_pruned_fp8_scaled.safetensors  ~21G
```

如果只有 int8_convrot 那个文件、没下 fp8_scaled，就得跑第 5 节的下载命令补上。

---

## 5. 怎么跑（一步步）

**前提**：第 4 节的 `unet_name` 已切到 `pruned_fp8_scaled`，且 5 个权重文件都在 `models/` 对应子目录。

1. **确认 ComfyUI 在跑**（一个终端）：
   ```bash
   cd /workspace/ComfyUI && python main.py --lowvram --listen 0.0.0.0 --port 8188
   ```
   （A10 24G + 21G 扩散模型，必须加 `--lowvram` 自动 offload，否则 OOM）

2. **确认 cloudflared 在跑**（另一个终端，给公网 URL）：
   ```bash
   cd /tmp && ./cloudflared tunnel --url http://127.0.0.1:8188
   ```
   打开打印的 `https://xxx.trycloudflare.com` 链接。

3. **加载这个工作流**（两种方式）：
   - **方法 A**：ComfyUI 启动后默认空白 → 左侧 `Templates`（模板库）→ `Video` → `MiniMax H3` → 选 `fl2va`（first/last-frame）→ 弹出下载模型的弹窗（如还没下过会自动下）→ 画布出现完整工作流。
   - **方法 B**：从 `output/` 目录或别处**打开已保存的 JSON 工作流文件**（双击或拖入画布）。

4. **调整参数**（你截图里那些）：
   - 改 `unet_name` → `minimax_h3_fl2va_pruned_fp8_scaled.safetensors`（**必做**）
   - 检查 `first_frame` 有没有接图（你截了鼠标图 ✓）
   - 提示词按你需求改
   - `duration` 默认 5s 可改
   - `noise_seed` 想固定就留默认，想换就改

5. **点右上角 `Run`（执行按钮）**，开始跑。日志窗口/控制台会打印进度。H3 视频生成一次大约 **5–20 分钟**（A10 24G + lowvram 估）。

6. **出片后**：H3 节点通常直接连 `Save Video`/`Preview` 节点自动保存到 `output/`，或在节点上右键 `Open image/video` 直接预览。

---

## 6. 常见问题 / 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 字段红字 `missing model` | 权重没下载/放错目录 | 见 Model Links Note + 第 4 节 |
| `ModuleNotFoundError: ... int8_convrot` / 量化算子报错 | torch 非 cu130 跑了 int8_convrot | 第 4 节：换 fp8_scaled 或升 torch |
| `CUDA out of memory` | 显存不够 | `pkill` 后用 `--lowvram` 重启；或降分辨率到 0.3 Mpx / 时长 3s |
| 出片很慢 | 正常现象 | H3 5s 视频 + A10 24G + lowvram 通常 5–20 分钟，看具体参数 |
| 视频没声音 | `audio_vae` 没接/没下载 | 检查 vae 字段；fp8_scaled 场景下 audio_vae 一致 |
| 提示词改了但画面不变 | seed 锁得太死 + 模型对提示词敏感度低 | 改 seed；或在 prompt 前加更明确的关键词 |
| 想换首末帧 | Load Image 节点复制一份，第二个 Load Image 接到 `last_frame` | 末帧不接 = 只给定首帧 |
| 想做纯文生视频（t2va） | 删 Load Image 节点 / 断开 first_frame 连线 | 节点自动切 t2va 模式 |

---

## 7. 进阶：想自己改工作流

- **想固定尺寸不依赖图**：删除 `Use Image Size` 整条链路，H3 节点的 width/height 字段手填 32 倍数（例 768×768、1024×576）
- **想换 LoRA**：`lora_n...` 字段下拉选，4 步版速度更快（`...turbo_4step_v1.0_768p...`）；注意 4 步版质量略降
- **想加负面提示**：H3 工作流**没有 negative prompt 节点**——H3 模型设计上就不需要
- **想存中间帧**：在 H3 节点输出后接 `VHS_VideoCombine` 节点，可调 fps / 格式 / 路径

---

## 8. 导出与分享工作流 JSON

搭好 / 跑通工作流后，把它存成 `.json` 分享给别人、或自己下次一键复用。

### 8.1 导出到本地文件
顶部菜单 **`Workflow`（工作流）→ `Export`**：
- 浏览器下载一个 `.json`（带节点布局），最适合分享、再导入。
- 想用程序 / API 调用才选 **`Export (API Format)`**（纯 API 格式、无布局）。
- 另有 **`Workflow → Save`（Ctrl+S）**：存到**当前实例本地**（实例里能重开），但**不会下载到你电脑**——想带走用 `Export`。

### 8.2 别人怎么用（在你的 trycloudflare 网站上）
1. 对方浏览器打开你的 `https://xxx.trycloudflare.com` 链接。
2. 顶部 `Workflow → Open`（或 `Load`）选 JSON；更直接：把 JSON **拖到画布**松手即加载。
3. 加载后 `unet_name` 默认还是 `int8_convrot`（模板默认值），对方也得切成 `fp8_scaled` 才能跑（除非他是 cu130 环境）。

### 8.3 两个关键提醒
- **JSON 不含权重**：它只记录工作流结构 + 引用的模型文件名。44.5GB 权重不在 JSON 里。对方 `models/` 里必须有同名文件，否则照样报「缺失模型」——分享 JSON 同时要对方自己下权重（或用模板库一键下）。
- **JSON 不是模型备份**：它只是「菜谱」，不是「食材」。

### 8.4 进 git 版本管理（可选）
想让工作流也进本仓库：把导出的 `.json` 放进仓库的 `workflows/` 目录提交即可（仓库根目录下建一个 `workflows/` 放工作流 JSON）。配合 `docs/` 里的说明，别人 clone 后能直接 `Open` 复用。

---

## 9. 示例提示词：男朋友给冰冰过生日

H3 提示词把**画面 + 动作 + 音效**写在同一段里，没有 negative prompt。下面给一个可直接粘进 `prompt` 字段的优化版（英文为主，Qwen3-VL 对英文描述更稳；也附中文版）。

**英文（推荐）**：
```
A heartwarming birthday scene. Bingbing (a young woman with long hair) sits at a
softly lit dinner table; her boyfriend walks into frame holding a small cake with a
single lit candle, warm fairy lights and a few balloons behind them, shallow depth of
field, cinematic 35mm look. He leans in, smiles, and gently presents the cake; soft
candlelight flickers across their faces, she covers her mouth in happy surprise then
leans closer to blow the candle; slow, tender push-in on their faces, subtle handheld
warmth. Audio: a quiet intimate room tone, the soft crackle of the candle flame, a faint
hum of the birthday tune, gentle genuine laughter, and a warm swelling acoustic guitar
motif that resolves as she blows out the candle.
```

**中文**：
```
温馨的生日场景。冰冰（长发年轻女孩）坐在暖光餐桌前；男朋友端着插着一根蜡烛的小蛋糕走入画面，
背景有串灯和几个气球，浅景深，电影感 35mm 质感。他俯身微笑，轻轻递上蛋糕；烛光在两人脸上摇曳，
冰冰惊喜地捂嘴，随后凑近吹灭蜡烛。缓慢温柔的推近，轻微手持呼吸感。
音频：私密安静的房间底噪、蜡烛火焰的细微噼啪、隐约的生日歌哼唱、真诚的轻笑，
以及一段温暖的木吉他旋律在吹灭蜡烛时收束。
```

**优化点**：画面给美术锚点（暖光/串灯/气球/浅景深/35mm）；动作写成连贯序列（走入→递蛋糕→捂嘴惊喜→吹蜡烛）；指定运镜（slow push-in + handheld）；音效独立成句（烛火/生日歌/轻笑/木吉他）让 H3 原生立体声出氛围；全程无 negative prompt。

**用法**：
- **有冰冰的照片** → 用 fl2va（I2V）：照片作 `first_frame`，prompt 描述照片之后的动作；照片最好是"吹蜡烛前"状态。
- **没有照片** → 用 t2va（T2V）：断开 `first_frame` 连线，prompt 不变，模型自己生成整幅画面。
- 参数：duration 5s、百万像素 0.4（A10 显存紧可降到 0.3）、seed 固定可复现。

---

## 关键参考链接

- H3 工作流本地部署：[腾讯云 GPU CVM 实操版](h3-tencent-gpu-cvm-guide.md)
- ComfyUI 基础：[Z-Image-Turbo 完整流程](tencent-cloud-comfyui-guide.md)
- H3 官方文档：https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3
- H3 官方 GitHub：https://github.com/MiniMax-AI/MiniMax-H3
- Comfy-Org 权重仓库：https://huggingface.co/Comfy-Org/MiniMax-H3
