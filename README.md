# ComfyUI 学习与 MiniMax H3 部署资料

包含面向零基础的 ComfyUI 系统学习手册，以及在阿里云 PAI DSW 单卡 GPU 实例上跑通 **ComfyUI + MiniMax H3** 的调研与部署资料。

派生自外部开源模板的文件及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

> 背景：用户拥有阿里云天池 PAI DSW 探索者版 **60 GPU 小时**（至 2026-12-31），目标是验证 MiniMax H3 单卡可行性、实测速度并估算配额产出。

## 目录结构

```
docs/
├── 01-新手入门/
│   ├── README.md                           # 新手资料入口
│   ├── ComfyUI-系统学习手册/               # 9 章教程 + 节点手册 + 全量节点索引
│   ├── ComfyUI-小白上手学习指南.md          # 快速入门版
│   ├── images/                             # 新手文档共享图片
│   └── examples/                           # 示例工作流
├── 02-MiniMax-H3部署/                      # H3 调研、部署与逐节点工作流资料
├── 03-GPU资源参考/                         # 免费/低成本 GPU 算力参考
└── 04-电商AI工作流/                        # 商品图、参考图编辑、换装与视频路线

scripts/
├── deploy_comfyui_h3_dsw.sh                # 一键部署：硬件确认→装 ComfyUI→启动→提示接 H3
├── h3_demo_workflow.js                     # 生成报告所用的动态工作流脚本（溯源用）
├── derive_flux2_klein_reference_workflow.mjs # 从官方模板派生双参考商品主图工作流
└── validate_comfy_workflow.mjs              # 静态检查工作流节点、连线和子图引用
```

## 文档怎么用

| 场景 | 看哪个 |
|---|---|
| **从零系统学习 ComfyUI，逐节点查资料** | [ComfyUI 零基础学习手册](docs/01-新手入门/ComfyUI-系统学习手册/README.md)（安装→基础工作流→进阶→排错，含 639 个内置节点索引） |
| **腾讯云 GPU 云服务器（≥24G）跑 H3** | [腾讯云 H3 指南](docs/02-MiniMax-H3部署/h3-tencent-gpu-cvm-guide.md)（撰写版，0–11 节，待实测回填） |
| 阿里云 PAI DSW（A10 24G）跑 H3 | [阿里云 DSW A10 指南](docs/02-MiniMax-H3部署/h3-dsw-a10-guide.md)（对齐本结构，实测版） |
| **ComfyUI 新手**看不懂 H3 工作流 | [H3 工作流逐节点指南](docs/02-MiniMax-H3部署/comfyui-h3-workflow-beginner-guide.md)（节点/连线/参数逐项讲解） |
| 想知道"能不能跑、怎么取舍" | [H3 DSW 调研报告](docs/02-MiniMax-H3部署/MiniMax_H3_ComfyUI_DSW_demo_report.md)（含可行性决策树、60h 产出公式） |
| 第一次上手 H3，一步步点 | [H3 手动操作指南](docs/02-MiniMax-H3部署/minimax-h3-dsw-manual-guide.md)（第 0–8 步 + 排错表 + 复查清单） |
| 想省事直接跑 | `scripts/deploy_comfyui_h3_dsw.sh`（在 DSW Terminal 执行 `bash scripts/deploy_comfyui_h3_dsw.sh`） |
| 腾讯云 Cloud Studio 免费 T4 练手 | [腾讯云 ComfyUI 指南](docs/02-MiniMax-H3部署/tencent-cloud-comfyui-guide.md)（Z-Image-Turbo，已验证） |
| 查找免费/低成本 GPU | [GPU 资源参考](docs/03-GPU资源参考/free-gpu-compute-list.md) |
| 搭建参考图驱动的电商商品主图 | [电商 AI 工作流项目](docs/04-电商AI工作流/README.md)（含参考站实测、差异记录和可复现 JSON） |

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
