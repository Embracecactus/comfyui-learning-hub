# ComfyUI × MiniMax H3（阿里云 PAI DSW）项目索引

在阿里云 PAI DSW 单卡 GPU 实例上，以 demo 级跑通 **ComfyUI + MiniMax H3** 的调研与部署资料。

> 背景：用户拥有阿里云天池 PAI DSW 探索者版 **60 GPU 小时**（至 2026-12-31），目标是验证 MiniMax H3 单卡可行性、实测速度并估算配额产出。

## 目录结构

```
docs/                                # 文档
├── h3-dsw-a10-guide.md                    # 【首选实操】阿里云 PAI DSW（A10 24G）跑 MiniMax H3（实测版，对齐腾讯云那份结构）
├── MiniMax_H3_ComfyUI_DSW_demo_report.md   # 调研报告（结论分级：官方/社区/未证实）
├── minimax-h3-dsw-manual-guide.md          # 手动操作指南（逐步照着做，比 A10 版更细）
├── free-gpu-compute-list.md                # 免费 GPU 算力选择清单（国内/海外/ComfyUI 云服务）
└── tencent-cloud-comfyui-guide.md          # 腾讯云 Cloud Studio 跑 ComfyUI（已验证版，Z-Image-Turbo）

scripts/                             # 脚本
├── deploy_comfyui_h3_dsw.sh                # 一键部署：硬件确认→装 ComfyUI→启动→提示接 H3
└── h3_demo_workflow.js                     # 生成报告所用的动态工作流脚本（溯源用）
```

## 文档怎么用

| 场景 | 看哪个 |
|---|---|
| **现在就照着在 A10 上跑** | `docs/h3-dsw-a10-guide.md`（对齐腾讯云版结构，0–11 节，含回填位） |
| 想知道"能不能跑、怎么取舍" | `docs/MiniMax_H3_ComfyUI_DSW_demo_report.md`（含可行性决策树、60h 产出公式） |
| 第一次上手，一步步点（更细） | `docs/minimax-h3-dsw-manual-guide.md`（第 0–8 步 + 排错表 + 复查清单） |
| 想省事直接跑 | `scripts/deploy_comfyui_h3_dsw.sh`（在 DSW Terminal 执行 `bash scripts/deploy_comfyui_h3_dsw.sh`） |

## 核心结论（速览）

- **路径 A（推荐）**：ComfyUI ≥ 0.30.0 原生内置 H3 节点，模板库一键加载 + 从 `Comfy-Org/MiniMax-H3` 下权重，单卡即可跑。
- **显存门槛**：≥24GB 直跑；16–24GB 依赖 int8 + nvfp4 量化 + offload；<16GB 基本没戏，走官方 API 节点兜底。
- **最大环境坑**：`int8_convrot` 权重需 torch 带 **cu130**，否则换 `fp8_scaled` 版。
- **60h 产出公式**：`片段数 ≈ 216000 / T`（T = 单条 5s 片段稳态耗时秒）。

## 关键链接

- 官方本地部署教程：https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3
- H3 官方 GitHub：https://github.com/MiniMax-AI/MiniMax-H3
- ComfyUI 重打包权重：https://huggingface.co/Comfy-Org/MiniMax-H3
- DSW 帮助文档：https://help.aliyun.com/zh/pai/dsw-overview

> 注意：MiniMax H3 受 Community License（地域/用途限制）约束；实例「运行中」即计费，用完请手动停止，避免 NAT+EIP/GA 等独立计费项持续扣费。
