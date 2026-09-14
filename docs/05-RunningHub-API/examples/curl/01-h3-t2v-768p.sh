#!/usr/bin/env bash
# MiniMax-H3 文生视频 768P — RunningHub 标准模型 API(单任务直出)
# 验证状态:参数 schema 已核实(官方 models_registry.json 2026-09-13);
#          通道需企业级-共享 API Key(个人 Key 实测 1014,2026-09-13)。
# 价格状态:平台侧价格未公开;MiniMax 官方锚点 ¥0.50/成片秒(见费用报告)。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=<企业级-共享 Key>}"

BASE="https://www.runninghub.cn/openapi/v2"     # 国际站: https://www.runninghub.ai/openapi/v2

# 0) 可选:先拿官方预估价(不创建任务不扣费)
curl -sS -X POST "$BASE/price-preview/minimax/hailuo-h3/text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"一只橙色猫在雨后的城市屋顶上缓慢行走,电影感镜头","resolution":"768P","duration":"5","ratio":"16:9"}'

# 1) 提交任务(异步,立即返回 taskId)
TASK_ID=$(curl -sS -X POST "$BASE/minimax/hailuo-h3/text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"一只橙色猫在雨后的城市屋顶上缓慢行走,电影感镜头","resolution":"768P","duration":"5","ratio":"16:9"}' \
  | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["taskId"])')
echo "taskId=$TASK_ID"

# 2) 轮询查询(5 秒间隔;终态 SUCCESS/FAILED/CANCEL;usage 内含费用字段)
curl -sS -X POST "$BASE/query" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d "{\"taskId\":\"$TASK_ID\"}"
