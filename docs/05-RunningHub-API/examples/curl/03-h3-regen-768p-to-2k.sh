#!/usr/bin/env bash
# MiniMax-H3 Regeneration:768P 源视频 → 2K 成片(官方两阶段路线的第 2 步)。
# 完整 2K 总价 = 第 1 步(768P 生成,见 01 号示例)+ 本步。两个 taskId 同属
# 一条成片链路,须合并对账;本步单独价格不等于 2K 全程价。
# 源视频硬约束(官方文档 api-498427804):含音轨、24fps、尺寸被 32 整除、
# 面积 ≤768×1344、107–362 帧、仅 MP4;prompt 必须与生成源视频时的最终提示词一致。
# 验证状态:schema 已核实(官方文档+注册表);价格未公开(MiniMax 锚点:
# 输出 ¥0.30/秒 + 输入视频重新计费 ¥0.30/秒)。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=<企业级-共享 Key>}"

BASE="https://www.runninghub.cn/openapi/v2"
# 0) 如 768P 源视频在本地,先上传(个人/企业 Key 均可用)
SOURCE_URL=$(curl -sS -X POST "$BASE/media/upload/binary" \
  -H "Authorization: Bearer $RH_API_KEY" -F "file=@./h3_768p_source.mp4" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["download_url"])')

# 1) 提交再生成任务(resolution 枚举仅 "2K")
curl -sS -X POST "$BASE/minimax/hailuo-h3/regeneration-text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d "{\"prompt\":\"<与生成 768P 源视频时完全一致的最终提示词>\",\"baseVideoUrl\":\"$SOURCE_URL\",\"resolution\":\"2K\"}"
# → taskId 后用 $BASE/query 轮询;该 taskId 与 768P 任务的 taskId 一起入账。
