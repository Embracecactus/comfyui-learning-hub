# 免费 GPU 算力选择清单（跑 ComfyUI + MiniMax H3）

> 调研日期：2026-08-21 ｜ 面向中国大陆用户
> 可信度图例：✅=官方可查证 ｜ ⚠️=需实测（以平台当日为准） ｜ ❓=未证实（来源冲突/软文/未核实）

---

## 1. 先做这一步：核查天池 GPU 配额/实例

- 登录天池 Notebook `tianchi.aliyun.com/notebook-ai/`，看实例列表是否只剩 CPU 实例。
- 「资源包/配额」页确认 60h GPU 是否仍在（有效期至 2026-12-31；积分 ≥200 可再领 +30h）。
- 若 GPU 实例丢失：点「新建实例」看是否还有 GPU 规格可选；或到 `pai.console.aliyun.com` → DSW → 实例列表核对。
- 常见原因：免费额度用尽（**额度用尽后会自动按量计费**，A10 约 ¥8/时，第三方）、试用到期、实名认证问题。
- 若已开通按量付费且配额耗尽，创建 GPU 实例即开始扣费，别误开。

## 2. 国内渠道

| 平台 | GPU/配额 | 费用 | 跑 ComfyUI | 注意点 |
|---|---|---|---|---|
| **天池 DSW 探索者版** ⚠️ | GPU 60h + 积分200赠30h；型号❓（旧手册 P100 16G，已过时） | 0 元；额度尽后自动按量 | 可装（无 sudo）；端口转发/外网 ⚠️ | GPU 实例当前异常待核查；16G 需量化+offload |
| **ModelScope Notebook** ✅ | NVIDIA 24G + AMD 192G（MI300X 100h，2026-08 第三方）；免费额度规则 ⚠️ | 0 元 | **可，官方 cloudflared 教程已验证**（8188→trycloudflare 公网） | NVIDIA 24G 刚够 H3；AMD 192G 需先验 ROCm 兼容性 ❓；释放后数据自存 |
| **ModelScope 创空间** ⚠️ | xGPU 免费共享 GPU，每日配额 ❓ | 0 元 | 可（社区现成 ComfyUI 应用） | 重型视频模型受共享配额限制 |
| **百度 AI Studio** ❓ | 8 点/日 或 100h/月任务制（**冲突未证实**）；V100 16G / B1-V150S 32G | 0 元 | 受限（无 root、飞桨生态），只能 Fork 现成项目 | 2026 政策收紧 |
| **腾讯云 Cloud Studio** ⚠️ | 每月 **10000 分钟 GPU**（T4 16G，多篇 2026 教程证实） | 0 元 | 可（社区一键模板） | T4 16G 需量化勉强跑 H3 ❓ |
| **阿里云 ECS/免费试用中心** ✅ | 160+ 产品试用；ECS 300 元/1 个月；GPU 免费型号 ❓ | 0 元首月 | 需自装 | 免费档通常无 GPU |
| **阿里云 FC 函数计算** ✅ | 一键部署 ComfyUI 模板；新用户免费额度**不含 GPU** | GPU 按量 | 可（发布为 Serverless API） | 适合 DIY 挂 API |
| **阿里云百炼** ✅ | 每模型约 100 万 tokens（仅抵 API 推理） | 0 元（限 tokens） | ❌ 非 ComfyUI 托管 | 对跑工作流无直接帮助 |
| **AutoDL** ⚠️ | 4090 24G ≈2.1~3.4 元/h、A100-80G ≈5.98 元/h | 付费低价 | **完全自由**（SSH+端口转发官方文档） | 热门卡缺货排队 |
| **智星云** ⚠️ | 4090 1.35 元/h 起；新用户 500 元券 ❓ | 付费低价 | 完全自由 | 券额需实测 |
| **算家云** ⚠️ | 4090 低至 1.24~1.3 元/h | 付费低价 | 完全自由 | 第三方报价 |
| **OpenBayes** ⚠️ | 新用户赠 GPU 时长（历史约 4h 4090） | 0 元（活动） | 现成 ComfyUI/FLUX 镜像 | 当前活动额度需实测 |

## 3. 海外渠道（含大陆访问难度）

| 平台 | GPU/配额 | 费用 | 跑 ComfyUI | 大陆访问 | 注意点 |
|---|---|---|---|---|---|
| **Google Colab** ⚠️ | T4 16G 为主（不承诺型号）；单 notebook ≤12h | 0 元 | 可行（社区一键 notebook；Flux 需 GGUF 约 2min/图） | **高**：需代理+新号风控 | 空闲断连、可能拿不到 GPU；禁 SSH/分布式 |
| **Kaggle** ✅ | **每周 30h**（周一重置）；P100 16G 为主，偶见 T4/T4×2 | 0 元 | 可行（现成 "MiniMax H3 on Kaggle" notebook） | **低**：可直连；reCAPTCHA 需辅助；GPU 需 +86 手机验证 | **开 Internet 双倍扣时**；单会话 12h；60min 无操作回收 |
| **HF ZeroGPU** ✅ | RTX Pro 6000 Blackwell 48G/96G；免费 **5 min/天**（PRO 40 min） | 0 元 | 仅兼容 **Gradio SDK**，ComfyUI 需转纯 Python | 中：直连慢，建议代理 | 免费账户限 2 个 Space、注册满 30 天 |
| **GitHub Codespaces** ✅ | 每月 120 core-hours + 15GB-month | 0 元 | **无 GPU**，CPU 极慢 | 中 | 仅适合代码开发 |
| **Lightning AI** ⚠️ | 免费 4-CPU Studio + 一次性 credits（约 22h T4） | 0 元 | 可 | ❓ | 赠额促销性、会变 |

## 4. ComfyUI 云服务（一键/免配置）

| 平台 | 免费额度 | GPU | H3 支持 | 注意点 |
|---|---|---|---|---|
| **Comfy Cloud**（comfy.org 官方）✅ | **免费 5 次真实 GPU 运行，无需信用卡** | RTX 6000 Pro Blackwell 96G | ✅ **官方上线**：T2V/I2V/R2V，2K+原生音频 | 海外站需代理 ⚠️；积分制只扣活跃 GPU 时间；Standard $16/月起 |
| **RunComfy** ✅ | **无免费额度**，按量先充值 | T4 $0.79–0.99/h、H200 $7.66–9.59/h | ✅ 模型库已收录 H3 + 可自装任意节点 | 需代理；Pro $19.99/月 |
| **Replicate** ❓ | 注册赠 $10 ❓ | 按次 | ❌ H3 未证实；节点白名单受限 | 自由度低 |
| **ModelScope 创空间** ⚠️ | xGPU 共享 GPU 免费 | 免费共享 | ❓ 未证实 | 国内直连 |
| **腾讯云 Cloud Studio** ⚠️ | 每月 10000 分钟 T4 | T4 16G | ❓ 需量化勉强跑 | 国内直连 |
| **Segmind** ✅ | 无真免费档（$10 起充） | 自有 Pixelflows | ❓ 未证实 | 非标准 ComfyUI 生态 |
| **ComfyUI Web** ❓ | 自称有免费方案，额度 ❓ | $9.99/月起 | ❓ | 第三方站，谨慎 |

## 5. 推荐路径（最低成本跑通 H3 demo）

1. **先看效果（0 元，最快）**：**Comfy Cloud 官方 5 次免费**验证 H3 demo（官方预装、2K+原生音频，无需信用卡）。⚠️ 大陆需代理，先实测通不通。
2. **长期免费跑（0 元）**：**ModelScope Notebook NVIDIA 24G** → 官方 cloudflared 教程起 ComfyUI → 装 H3 节点/权重。24G 刚好原生跑。
3. **补充额度**：**天池 60h**（若找回）只做小批量试跑；注意额度用尽自动按量计费的风险。
4. **16G 环境降级**（Kaggle/T4/天池 P100）：H3 走 **GGUF/INT8 量化 + offload** 压到 ~12–16G；I2V 起步、768p、5s 短片段；速度慢一个量级，短 demo 可接受；量化算子不兼容就回退 24G。
5. **兜底（确定性最高）**：**AutoDL/智星云/算家云 4090 24G**（1.3~3.4 元/h，完整 SSH+端口转发），一次 demo 几块钱。

> 一句话：**Comfy Cloud 5 次免费先验效果 → ModelScope 24G 长期免费跑 → 16G 量化降级 → 4090 时租兜底。**

---

## 关键链接

- 天池：`https://tianchi.aliyun.com/notebook-ai/`
- ModelScope ComfyUI 教程：`https://www.modelscope.cn/headlines/article/429`
- ModelScope ComfyUI 一键部署：`https://github.com/SoonerOrLater-NewBest/modelscope-comfyui`
- 腾讯云 Cloud Studio：`https://ide.cloud.tencent.com/`
- Comfy Cloud：`https://comfy.org/zh-CN/cloud`；H3 专题：`https://comfy.org/zh-CN/minimax-h3`
- RunComfy：`https://www.runcomfy.com/pricing`；模型库：`https://www.runcomfy.com/models`
- Kaggle GPU 文档：`https://www.kaggle.com/docs/efficient-gpu-usage`
- HF ZeroGPU：`https://huggingface.co/docs/hub/spaces-zerogpu`
- AutoDL SSH 端口转发：`https://www.autodl.com/docs/ssh_proxy/`
