#!/usr/bin/env bash
# MiniMax-H3 文生视频 2K — RunningHub 标准模型 API(单任务直出,一价全含)。
# 关键口径:resolution=2K 是一个任务一个报价;平台如内部经 768P 中间阶段,
# 费用已含在该任务报价内(实测证据:AI 应用路线 2K 任务第三方费 ¥3.85/5s,
# 未出现独立的 768P 任务或第二次扣费)。不要再叠加一次 768P 生成费。
# 验证状态:schema 已核实;通道需企业级-共享 Key(个人 Key 1014)。
#          2026-09-14 起 414=账户算力值耗尽(与渠道无关,充值即恢复)。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=<企业级-共享 Key>}"

BASE="https://www.runninghub.cn/openapi/v2"
curl -sS -X POST "$BASE/minimax/hailuo-h3/text-to-video" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"一只橙色猫在雨后的城市屋顶上缓慢行走,电影感镜头","resolution":"2K","duration":"5","ratio":"16:9"}'
# → {"taskId":"…"} 后轮询到终态(单次 query 不等于终态):
for i in $(seq 1 240); do
  R=$(curl -sS -X POST "$BASE/query" -H "Authorization: Bearer $RH_API_KEY" \
       -H "Content-Type: application/json" -d "{\"taskId\":\"$TASK_ID\"}")
  S=$(echo "$R" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')
  echo "[$i] $S"
  case "$S" in
    SUCCESS) echo "$R" | python3 -m json.tool; break ;;
    FAILED|CANCEL) echo "$R" | python3 -m json.tool; exit 4 ;;
  esac
  sleep 5
done
# 终态响应 usage 字段即费用:usage.consumeCoins(平台币)
# + usage.thirdPartyConsumeMoney(第三方模型费,元);同一任务勿重复累计。
