export const meta = {
  name: 'comfyui-h3-dsw-demo',
  description: '调研 MiniMax H3 在阿里云 PAI DSW 单卡 GPU 上以 demo 级跑通 ComfyUI 的官方集成方式与实操清单',
  phases: [
    { title: 'Research', detail: '并行调研 H3 官方集成方式 与 DSW 跑 ComfyUI 要点' },
    { title: 'Synthesize', detail: '综合成 demo 级可勾选检查清单' },
  ],
}

phase('Research')
log('并行调研 H3 官方集成 + DSW 实操要点（返回纯文本，不做 schema 校验）')

const research = await parallel([
  () => agent(
    '你是调研助手。目标：找出 MiniMax H3 模型在 ComfyUI 中运行的【官方/可信】集成方式，用于在一台阿里云 PAI DSW 单卡 GPU 实例上以 demo 级别跑通。\n\n' +
    '请通过 web 搜索与抓取，重点确认并写成一份中文调研报告（不要输出 JSON，直接写条理清晰的中文报告）：\n' +
    '1. MiniMax H3 的官方仓库/文档地址（GitHub、官方博客、HuggingFace）。注意 2026-08 前后出现大量 SEO/营销文章，必须区分官方源与垃圾文，只采信可验证的官方或高可信来源，对无法验证的说法明确标注「未证实」。\n' +
    '2. ComfyUI 集成方式：官方节点、社区自定义节点（给仓库名），还是走 SGLang/vLLM/Diffusers 再桥接？给出具体安装命令。\n' +
    '3. 最小硬件与显存：官方最低 GPU 显存、是否支持单卡、是否需要多卡并行；量化（int8/int4/GGUF）与 offload 支持情况。\n' +
    '4. 资源规模：模型权重文件大小、是否支持低分辨率/短时长 demo 推理。\n' +
    '5. 已知坑：常见报错、版本要求（如 ComfyUI >= 0.30.0）。\n\n' +
    '只返回可验证信息，在报告末尾列出你实际访问的源 URL 清单。对不确定内容用「未证实」标注，不要编造命令或链接。',
    { label: 'H3官方集成', phase: 'Research' }
  ),
  () => agent(
    '你是调研助手。目标：找出在【阿里云 PAI DSW（DataScience Workshop / 天池 Notebook 探索者版）】上运行 ComfyUI 的实操要点，用户要在那里用单卡 GPU（约 60 GPU 小时配额）以 demo 级跑生成式模型。\n\n' +
    '请通过 web 搜索与抓取，写成一份中文调研报告（不要输出 JSON，直接写条理清晰的中文报告）：\n' +
    '1. DSW 环境：默认是否已有 Python/PyTorch/CUDA？JupyterLab 终端如何打开？能否后台常驻进程？\n' +
    '2. 访问 ComfyUI Web UI：DSW 是否提供端口代理/转发？给出启动 ComfyUI 并能在浏览器打开的具体做法（--listen 0.0.0.0、端口、代理 URL 等）。\n' +
    '3. 持久化：实例停止后系统盘/工作目录是否保留？几十 GB 权重建放哪（OSS 挂载、/mnt 等）？如何避免重复下载。\n' +
    '4. 计费与确认：运行才计 GPU 小时；如何确认 GPU 型号显存（nvidia-smi）与系统内存（free -h）。\n' +
    '5. 网络：DSW 内能否 pip install / git clone / 从 HuggingFace 或国内镜像下载模型？有无已知限制或推荐镜像源。\n\n' +
    '只返回可验证信息，在报告末尾列出你实际访问的源 URL 清单；无法确认的标注「未证实」，不要编造命令。',
    { label: 'DSW跑ComfyUI', phase: 'Research' }
  ),
], { allowAllFailures: true })

phase('Synthesize')
log('综合为 demo 级检查清单')
const a = research[0]
const b = research[1]
const guide = await agent(
  '把两份调研结果综合成一份【demo 级】可操作步骤清单，给一位有 ML 部署经验的用户，让他在阿里云 PAI DSW 单卡 GPU（60 GPU 小时）上以最小成本跑通 ComfyUI + MiniMax H3 并测速。\n\n' +
  '调研A（H3 官方集成）：\n' + String(a) + '\n\n' +
  '调研B（DSW 跑 ComfyUI）：\n' + String(b) + '\n\n' +
  '产出中文 Markdown，结构清晰、可直接照做，包含：\n' +
  '1. 【0. 先决条件】开通 DSW 实例的规格选择建议（GPU 型号、显存、系统内存、存储）。\n' +
  '2. 【1. 开实例后硬件确认】nvidia-smi / free -h 等命令，判断能否跑 H3（结合 offload/量化）。\n' +
  '3. 【2. 装 ComfyUI】DSW 终端具体命令（clone、装依赖、启动并能在浏览器访问 Web UI）。\n' +
  '4. 【3. 接 H3】按可信的官方/社区方式装 H3 节点与下载权重（具体命令/链接；若无官方 ComfyUI 集成，说明替代路径如 SGLang/vLLM，并给 demo 级最小运行方式）。\n' +
  '5. 【4. 跑最小片段量速】推荐最低分辨率/最短时长参数，测出 秒/帧 或 秒/片段，并给出如何反推 60h 能出多少内容。\n' +
  '6. 【5. 风险与省时】已知坑、offload/量化取舍、避免 60h 烧在环境踩坑上的建议。\n' +
  '7. 【6. 检查清单】浓缩成可勾选 checklist。\n\n' +
  '语气：技术精确、不啰嗦、不过度科普。对调研中「未证实」项如实标注，不要替用户做绝对判断，给出「能跑的条件 + 代价 + 实测建议」。',
  { label: '综合检查清单', phase: 'Synthesize' }
)

return { research, guide }
