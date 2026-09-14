#!/usr/bin/env bash
# ComfyUI 工作流路线(个人 Key 可用)——按机器运行秒计费(实测 ≈0.21 币/秒,
# 与模型无关),失败任务也计运行时长。适合任意自上架工作流,不是标准模型价。
# 本仓库 2026-09-09 已实测跑通(taskId 2097529689961885697 等)。
set -euo pipefail
: "${RH_API_KEY:?请 export RH_API_KEY=...}"

ORIGIN="https://www.runninghub.cn"

# 0) 上传参考媒体(返回 fileName 填入 LoadImage/LoadVideo 节点)
FILENAME=$(curl -sS -X POST "$ORIGIN/task/openapi/upload" \
  -H "Authorization: Bearer $RH_API_KEY" \
  -F "apiKey=$RH_API_KEY" -F "fileType=input" -F "file=@./product.png" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["fileName"])')
echo "fileName=$FILENAME"

# 1) 提交工作流任务(instanceType=plus 指定 48G 机器,需先在平台调试保存)
TASK_ID=$(curl -sS -X POST "$ORIGIN/task/openapi/create" \
  -H "Authorization: Bearer $RH_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "apiKey": "'"$RH_API_KEY"'",
    "workflowId": "<平台保存工作流后分配的ID>",
    "instanceType": "plus",
    "nodeInfoList": [
      {"nodeId": "137", "fieldName": "image", "fieldValue": "'"$FILENAME"'"},
      {"nodeId": "138", "fieldName": "value", "fieldValue": "提示词…"}
    ]
  }' | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["data"]["taskId"])')
echo "taskId=$TASK_ID"

# 2) 轮询新接口 / 取消 / 成本与失败归因
curl -sS -X POST "$ORIGIN/openapi/v2/query" -H "Authorization: Bearer $RH_API_KEY" \
  -H "Content-Type: application/json" -d "{\"taskId\":\"$TASK_ID\"}"
# 取消(取消前已运行时长照计费):
# curl -sS -X POST "$ORIGIN/task/openapi/cancel" -H "Authorization: Bearer $RH_API_KEY" \
#   -H "Content-Type: application/json" -d "{\"apiKey\":\"$RH_API_KEY\",\"taskId\":\"$TASK_ID\"}"
