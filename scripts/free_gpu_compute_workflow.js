export const meta = {
  name: 'free-gpu-compute-research',
  description: '调研国内/海外免费 GPU 算力渠道与现成 ComfyUI 云服务，综合成可执行清单',
  phases: [
    { title: 'Research', detail: '三路并行：国内免费算力 / 海外免费算力 / ComfyUI 现成云服务' },
    { title: 'Synthesize', detail: '综合成「免费算力选择清单 + 最低成本跑通 H3 demo」' },
  ],
}

phase('Research')
log('三路并行调研免费算力渠道')

const research = await parallel([
  () => agent(
    '你是调研助手。目标：调研【国内】面向个人/AI 开发者的【免费或低成本】GPU 算力渠道。用户在中国大陆，想跑 ComfyUI + MiniMax H3（视频生成，≥24GB 显存才好用）。\n\n' +
    '请通过 web 搜索与抓取，核实 2026-08 现状：\n' +
    '1. 阿里云天池 PAI DSW 探索者版免费 GPU 配额：如何领取/续用、GPU 实例类型、配额耗尽怎么办。\n' +
    '2. ModelScope 魔搭社区免费算力（创空间 / Notebook / PAI-DSW 免费试用）：GPU 型号与时长的实际规则。\n' +
    '3. 百度 AI Studio（飞桨）：每日免费 GPU 时长、GPU 型号（V100/A100/3090 等）、能否跑 ComfyUI（非飞桨框架是否可用、有无终端/ssh）。\n' +
    '4. 其他国内渠道：腾讯云/华为云/阿里云新用户免费试用、AutoDL/智星云等低价卡（标注是否真免费、价格量级）。\n' +
    '5. 各渠道运行 ComfyUI 的可行性：是否提供 Jupyter 终端、能否装自定义节点/端口转发。\n\n' +
    '输出中文报告，区分「官方可查证」与「需实测/未证实」，报告末尾附你实际访问的 URL 清单。不要编造配额数字，无法确认就标「未证实」。',
    { label: '国内免费算力', phase: 'Research' }
  ),
  () => agent(
    '你是调研助手。目标：调研【海外】免费 GPU 算力渠道。用户在中国大陆，需要考虑可访问性与注册难度，目标跑 ComfyUI 与 AI 生成 demo。\n\n' +
    '请通过 web 搜索与抓取，核实 2026-08 现状：\n' +
    '1. Google Colab 免费版：GPU 型号（T4 还是其他）、免费额度规则、从中国大陆访问是否可行（是否需代理/账号限制）。\n' +
    '2. Kaggle：每周免费 GPU 时长、GPU 型号（T4/P100 等）、跑 ComfyUI 的可行性。\n' +
    '3. Hugging Face Spaces / 免费 Notebook：免费 GPU 规则与时长。\n' +
    '4. 其他：GitHub Codespaces、Deepnote、Lightning AI、OpenBayes 等的免费额度（标注是否真有免费层）。\n' +
    '5. 各渠道从中国大陆访问的限制（网络、手机号/邮箱注册、支付要求）。\n\n' +
    '输出中文报告，区分「官方可查证」与「需实测」，报告末尾附实际访问的 URL 清单。配额数字不确定就标「未证实」。',
    { label: '海外免费算力', phase: 'Research' }
  ),
  () => agent(
    '你是调研助手。目标：调研【现成跑 ComfyUI 的免费/低成本云服务】，用户想省去自己配环境的麻烦。\n\n' +
    '请通过 web 搜索与抓取，核实 2026-08 现状：\n' +
    '1. 国内：ModelScope 创空间上的 ComfyUI、阿里云百炼、腾讯云 AI 相关产品、各种「ComfyUI 云服务」的免费额度或新用户试用。\n' +
    '2. 海外：RunComfy、ComfyUI 官方云（Comfy Cloud）、Replicate、HuggingFace 上的 ComfyUI Space、Segmind 等：免费额度与计费方式。\n' +
    '3. 这些云 ComfyUI 是否支持 MiniMax H3 这类视频模型（或自带模型库/能否加载社区节点）。\n\n' +
    '输出中文报告，区分「免费额度」「按量付费」「试用」，报告末尾附实际访问的 URL 清单；不确定就标「未证实」。',
    { label: 'ComfyUI云服务', phase: 'Research' }
  ),
], { allowAllFailures: true })

phase('Synthesize')
log('综合成免费算力选择清单')
const guide = await agent(
  '把三份调研结果综合成一份「免费 GPU 算力选择清单」给用户。用户画像：在中国大陆、有 ML 部署经验（懂 offload/量化）、目标是在 ComfyUI 上跑 MiniMax H3 demo（视频生成，≥24GB 显存最佳），手头有阿里云天池 60h GPU 配额但当前 GPU 实例异常（只剩 CPU 实例）。\n\n' +
  '调研A（国内）：\n' + String(research[0]) + '\n\n' +
  '调研B（海外）：\n' + String(research[1]) + '\n\n' +
  '调研C（ComfyUI 云服务）：\n' + String(research[2]) + '\n\n' +
  '输出中文 Markdown：\n' +
  '1. 【先做这一步】核查天池 GPU 配额/实例是否还能恢复（给出控制台操作步骤）。\n' +
  '2. 【国内渠道】表格：平台 | GPU/配额 | 费用 | 能否跑 ComfyUI | 获取方式 | 注意点（网络/持久化/合规）。\n' +
  '3. 【海外渠道】表格：标注从中国大陆访问的难度。\n' +
  '4. 【ComfyUI 云服务】表格：一键/免配置方案。\n' +
  '5. 【推荐路径】结合免费资源现实，给出「最低成本跑通 H3 demo」的一条建议路径（含显存不够时的降级）。\n' +
  '6. 【可信度】每个渠道标注：官方可查证 / 需实测 / 未证实。\n\n' +
  '语气：技术精确、不啰嗦。配额数字不确定就写「未证实」，不要编造。',
  { label: '综合清单', phase: 'Synthesize' }
)

return { research, guide }
