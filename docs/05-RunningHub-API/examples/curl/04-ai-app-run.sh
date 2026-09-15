#!/usr/bin/env bash
# AI 应用路线(个人消费级 Key 即可用)——本仓库 2026-09-12 已实测成功的一条
# H3 2K 链路。webappId=2083105376052006914 "Minimax H3 文生视频工作流"
# (官方应用市场应用,按实际用量计费:平台币 + 第三方模型费)。
# 实测记录(2026-09-12):2K/5s/16:9 → SUCCESS,2560×1440@24fps 5.167s 带音轨;
# usage: consumeCoins=7, thirdPartyConsumeMoney=3.85。
# 2026-09-14 起同应用被 414(账户算力值耗尽,任务未创建零扣费),充值即恢复。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=<个人或企业 Key>}"

ORIGIN="https://www.runninghub.cn"   # 工作流/AI 应用族接口在主域,无 /openapi/v2 前缀

# 1) 提交 AI 应用任务(nodeInfoList 字段名来自应用的 apiCallDemo 节点信息)
TASK_ID=$(curl -sS -X POST "$ORIGIN/task/openapi/ai-app/run" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "apiKey": "'"$RH_API_KEY"'",
    "webappId": "2083105376052006914",
    "nodeInfoList": [
      {"nodeId": "1", "fieldName": "prompt",     "fieldValue": "一只橙色猫在雨后的城市屋顶上缓慢行走,电影感镜头"},
      {"nodeId": "1", "fieldName": "resolution", "fieldValue": "2K"},
      {"nodeId": "1", "fieldName": "duration",   "fieldValue": "5"},
      {"nodeId": "1", "fieldName": "ratio",      "fieldValue": "16:9"}
    ]
  }' | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["data"]["taskId"])')
echo "taskId=$TASK_ID"

# 2) 轮询到终态(5 秒间隔,单次 query 不等于终态;本地超时≠平台失败)
for i in $(seq 1 240); do
  R=$(curl -sS -X POST "$ORIGIN/openapi/v2/query" \
       -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
       -d "{\"taskId\":\"$TASK_ID\"}")
  S=$(echo "$R" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')
  echo "[$i] $S"
  case "$S" in
    SUCCESS) echo "$R" | python3 -m json.tool; break ;;
    FAILED|CANCEL) echo "$R" | python3 -m json.tool; exit 4 ;;
  esac
  sleep 5
done

# 3) 可选:旧 outputs 接口拿 consumeCoins/thirdPartyConsumeMoney/failedReason 归因
curl -sS -X POST "$ORIGIN/task/openapi/outputs" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d "{\"apiKey\":\"$RH_API_KEY\",\"taskId\":\"$TASK_ID\"}"
