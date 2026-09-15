#!/usr/bin/env bash
# MiniMax-H3 文生视频 768P — RunningHub 标准模型 API(单任务直出)
# 验证状态:参数 schema 已核实(官方 models_registry.json,快照 SHA256 于
#          2026-09-14 复检一致);通道需企业级-共享 API Key(个人 Key 实测
#          1014,2026-09-13)。2026-09-14 起账户算力值耗尽,提交会先遇 414。
# 价格状态:平台侧价格未公开;MiniMax 原厂参考价 ¥0.50/成片秒(非平台报价)。
# 完整流程 = 预估(可选) → 提交 → 轮询到终态 → 下载;单次 query 不等于终态。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=<企业级-共享 Key>}"

BASE="https://www.runninghub.cn/openapi/v2"     # 国际站: https://www.runninghub.ai/openapi/v2
PROMPT='{"prompt":"一只橙色猫在雨后的城市屋顶上缓慢行走，电影感镜头","resolution":"768P","duration":"5","ratio":"16:9"}'

# 0) 可选:官方预估价(不创建任务不扣费;个人 Key 返回 1014)
curl -sS -X POST "$BASE/price-preview/minimax/hailuo-h3/text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d "$PROMPT"; echo

# 1) 提交任务(异步,立即返回 taskId)
TASK_ID=$(curl -sS -X POST "$BASE/minimax/hailuo-h3/text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d "$PROMPT" | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["taskId"])')
echo "taskId=$TASK_ID" | tee /tmp/rh_last_task_id

# 2) 轮询到终态(5 秒间隔,上限 20 分钟;本地超时≠平台任务失败,保留 taskId 续查)
for i in $(seq 1 240); do
  STATUS=$(curl -sS -X POST "$BASE/query" \
    -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
    -d "{\"taskId\":\"$TASK_ID\"}")
  S=$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')
  echo "[$i] $S"
  case "$S" in
    SUCCESS) echo "$STATUS" | python3 -m json.tool; break ;;
    FAILED|CANCEL) echo "$STATUS" | python3 -m json.tool; exit 4 ;;
  esac
  sleep 5
done
