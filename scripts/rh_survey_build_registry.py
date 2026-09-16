#!/usr/bin/env python3
"""Build the RunningHub public API capability registry from official sources.

Sources (fetched once, then reused offline):
  1. HM-RunningHub/ComfyUI_RH_OpenAPI  models_registry.json  (422 standard-model
     endpoint definitions, official RunningHub org repo, Apache-2.0)
  2. Same repo developer-kit/pricing.public.json (353 public-safe pricing rows,
     snapshot version public-2026-04-29)
  3. Curated endpoint families verified against official docs pages and the
     repo's core client code (see ENDPOINT_FAMILIES below with source links)
  4. Real-run cost evidence from this repo's local run records
     (output/runninghub/api/*/run.json, gitignored)

Outputs into docs/05-RunningHub-API/data/:
  runninghub-api-registry.json   machine-readable registry (meta + families +
                                 capabilities + pricing + evidence + gaps)
  model-capabilities.csv         flat human-readable catalog (one row per
                                 model endpoint)
  sources-snapshot.json          provenance of every input source

Usage:
  python3 scripts/rh_survey_build_registry.py \
      --models-registry /tmp/rh-survey/models_registry_current.json \
      --pricing /tmp/rh-survey/ComfyUI_RH_OpenAPI/developer-kit/pricing.public.json

The script never stores API keys. It reads only the two source JSON files and
the local run records; nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs/05-RunningHub-API/data"
MODELS_URL = "https://raw.githubusercontent.com/HM-RunningHub/ComfyUI_RH_OpenAPI/main/models_registry.json"
REPO_URL = "https://github.com/HM-RunningHub/ComfyUI_RH_OpenAPI"
KIT_URL = REPO_URL + "/tree/main/developer-kit"
COLLECTED_AT = "2026-09-13"
# 2026-09-14 复检:重新下载官方注册表,SHA256 与 09-13 快照一致(未变化)。
REVERIFIED_AT = "2026-09-14"
REGISTRY_SHA256 = "73b109c96bb802d7f2ac0d2e25cdb9cd70f4d8987d0041cc045a93b444b409d7"

DOC_CN = "https://www.runninghub.cn/runninghub-api-doc-cn"
DOC_EN = "https://www.runninghub.ai/runninghub-api-doc-en"

# ---------------------------------------------------------------------------
# Curated HTTP endpoint families.  Every entry was verified on 2026-09-13
# against the official doc site, the official ComfyUI_RH_OpenAPI client code,
# or a live request from this workspace's personal key (marked live_verified).
# ---------------------------------------------------------------------------
ENDPOINT_FAMILIES = [
    {
        "id": "model-api-submit",
        "family": "标准模型 API",
        "method": "POST",
        "path": "/openapi/v2/{model_endpoint}",
        "base_url_cn": "https://www.runninghub.cn/openapi/v2",
        "base_url_intl": "https://www.runninghub.ai/openapi/v2",
        "auth": {"type": "bearer", "header": "Authorization: Bearer <key>"},
        "key_types_allowed": ["enterprise-shared"],
        "key_types_denied_observed": ["consumer-member"],
        "behavior": "异步:提交即返回 taskId → 轮询 query;模型端点清单见 model_capabilities",
        "instances": "422 个模型端点(按 1 个通用提交接口计,不逐个计入接口数)",
        "sources": [f"{DOC_CN}/doc-8287334", REPO_URL],
        "verification": "doc_verified+live_verified",
        "notes": "个人 Key 实测 1014 Access Denied(2026-09-07/09-12/09-13 三次);仅企业级-共享 Key 可调用",
    },
    {
        "id": "model-api-query",
        "family": "标准模型 API",
        "method": "POST",
        "path": "/openapi/v2/query",
        "auth": {"type": "bearer"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "请求 {taskId};返回 status(SUCCESS/FAILED/CANCEL/QUEUED/RUNNING)、results[].url、usage(consumeCoins/consumeMoney/thirdPartyConsumeMoney/taskCostTime/output_seconds)",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287334", f"{DOC_EN}/api-498427804"],
        "verification": "live_verified",
        "notes": "2026-09-13 用个人 Key 重查任务 2098737586251202562 成功,usage 字段完整",
    },
    {
        "id": "model-api-upload",
        "family": "标准模型 API",
        "method": "POST",
        "path": "/openapi/v2/media/upload/binary",
        "auth": {"type": "bearer", "multipart_field": "file"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "multipart 上传本地媒体 → data.download_url → 填入 imageUrl/videoUrl/audioUrl 等字段",
        "instances": 1,
        "sources": [REPO_URL + " core/upload.py", f"{DOC_EN}/api-498427804"],
        "verification": "doc_verified",
        "notes": "官方 kit client 与 core/upload.py 使用同一路径",
    },
    {
        "id": "model-api-price-preview",
        "family": "标准模型 API",
        "method": "POST",
        "path": "/openapi/v2/price-preview/{model_endpoint}",
        "auth": {"type": "bearer"},
        "key_types_allowed": ["enterprise-shared"],
        "key_types_denied_observed": ["consumer-member"],
        "behavior": "请求体=提交 payload;返回 estimatedPrice/currency/priceText/freeLimit,不创建任务",
        "instances": "按模型端点复用(1 个通用接口)",
        "sources": ["本仓库 scripts/runninghub_h3_t2v.py + 2026-09-12/09-13 实测"],
        "verification": "live_verified",
        "notes": "个人 Key 返回 1014(2026-09-13 对 768P/2K 两个 payload 均实测);企业 Key 可得官方预估价",
    },
    {
        "id": "asset-api",
        "family": "素材资产 API(Seedance 2.0 素材)",
        "method": "POST",
        "path": "/openapi/v2/assets/{create,list,query,update,delete} 与 assets/groups/{create,list,query,update,delete}",
        "auth": {"type": "bearer"},
        "key_types_allowed": ["consumer-member", "enterprise-shared"],
        "behavior": "管理可复用素材资产,供 seedance-2.5-token 等模型引用",
        "instances": 10,
        "sources": [REPO_URL + " nodes/assets/asset_nodes.py"],
        "verification": "live_verified",
        "notes": "2026-09-13 个人 Key 调 assets/query 返回业务校验错误(素材ID不能为空),证明鉴权通过、路径存在",
    },
    {
        "id": "workflow-create",
        "family": "ComfyUI 工作流 API",
        "method": "POST",
        "path": "/task/openapi/create",
        "base_origin": "https://www.runninghub.cn",
        "auth": {"type": "bearer+body", "note": "Header Bearer + body apiKey 双写"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "提交 workflowId 或直传 workflow JSON;nodeInfoList 替换节点参数;instanceType=plus 指定 48G 机;webhookUrl 回调;企业共享 Key 可用 retainSeconds 保留实例(另计费);独占 Key 可用 usePersonalQueue",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287334", f"{DOC_CN}/api-425749013", f"{DOC_CN}/doc-8287336"],
        "verification": "auth_verified",
        "notes": "本仓库 2026-09-09 用个人 Key 实跑成功(taskId 2097529689961885697 等);API 强制重置 seed",
    },
    {
        "id": "workflow-upload",
        "family": "ComfyUI 工作流 API",
        "method": "POST",
        "path": "/task/openapi/upload",
        "auth": {"type": "form", "fields": "apiKey, fileType=input, file"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "multipart 上传 → 返回 fileName,填入 LoadImage/LoadVideo 节点 fieldValue",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287339"],
        "verification": "live_verified",
        "notes": "2026-09-07 个人 Key 实测 code 0",
    },
    {
        "id": "workflow-query-outputs",
        "family": "ComfyUI 工作流 API",
        "method": "POST",
        "path": "/task/openapi/outputs",
        "auth": {"type": "bearer+body"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "已标注 deprecated,但响应含 taskCostTime/consumeCoins/consumeMoney/thirdPartyConsumeMoney/failedReason(节点级失败归因),成本核验仍需此接口",
        "instances": 1,
        "sources": [f"{DOC_CN}/api-425749004", "本仓库 2026-09-12 实跑记录"],
        "verification": "live_verified",
        "notes": "V2 query 也已带 usage 字段;失败归因(failedReason.traceback)仅此接口提供",
    },
    {
        "id": "workflow-status",
        "family": "ComfyUI 工作流 API",
        "method": "POST",
        "path": "/task/openapi/status",
        "auth": {"type": "bearer+body"},
        "key_types_allowed": ["consumer-member"],
        "behavior": "官方标注停止维护;建议改用 /openapi/v2/query",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287334"],
        "verification": "doc_verified",
        "notes": "deprecated",
    },
    {
        "id": "workflow-cancel",
        "family": "ComfyUI 工作流 API",
        "method": "POST",
        "path": "/task/openapi/cancel",
        "auth": {"type": "bearer+body"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "请求 {apiKey, taskId} 取消运行中任务;取消前已运行时长照计费",
        "instances": 1,
        "sources": [f"{DOC_EN}/doc-8287463", "https://qpsnl2kplc.apifox.cn/api-435315561"],
        "verification": "doc_verified",
        "notes": "本仓库未实测取消(避免对已成功任务误操作)",
    },
    {
        "id": "workflow-webhook",
        "family": "ComfyUI 工作流 API",
        "method": "PUSH",
        "path": "create 时传 webhookUrl → 平台 POST {event: TASK_END, taskId, eventData(字符串化 JSON)}",
        "auth": {"type": "none"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "任务结束回调;eventData 需二次 JSON 解析;与轮询不互斥",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287334"],
        "verification": "doc_verified",
        "notes": "2026-09-15 复查官方文档站与官方仓库客户端代码:未发现\"按 taskId 查询 webhook 事件记录/事件详情\"的公开接口;事件详情只能由回调接收方自行落库。已记入 gaps。",
    },
    {
        "id": "ai-app-run",
        "family": "AI 应用 API",
        "method": "POST",
        "path": "/task/openapi/ai-app/run",
        "auth": {"type": "bearer+body"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "提交 webappId + nodeInfoList(业务参数);官方应用按实际用量计费(平台 coins + thirdPartyConsumeMoney);自定义应用可能按算力值(power value)闸门",
        "instances": 1,
        "sources": [f"{DOC_EN}/doc-8287470", "本仓库 scripts/runninghub_h3_personal_app.py"],
        "verification": "live_verified",
        "notes": "2026-09-12 实跑成功一条 2K H3(taskId 2098737586251202562);自定义应用同日报 414 NOT_ENOUGH_POWER_VALUE",
    },
    {
        "id": "ai-app-node-info",
        "family": "AI 应用 API",
        "method": "GET",
        "path": "/api/webapp/apiCallDemo?apiKey=…&webappId=…",
        "auth": {"type": "query"},
        "key_types_allowed": ["consumer-member", "enterprise-shared", "enterprise-dedicated"],
        "behavior": "获取应用的节点列表/参数 schema(apiCallDemo),供拼装 nodeInfoList",
        "instances": 1,
        "sources": [f"{DOC_EN}/doc-8287470"],
        "verification": "doc_verified",
        "notes": "",
    },
    {
        "id": "llm-chat",
        "family": "LLM API",
        "method": "POST",
        "path": "/v1/chat/completions",
        "base_url_cn": "https://llm.runninghub.cn/v1",
        "base_url_intl": "https://llm.runninghub.ai/v1",
        "auth": {"type": "bearer"},
        "key_types_allowed": ["enterprise-shared"],
        "key_types_denied_observed": ["consumer-member"],
        "behavior": "OpenAI 兼容协议;官方文档称同时兼容 Anthropic / Gemini 协议;示例模型 glm-5.2,节点库含 qwen-plus/qwen-max/deepseek-chat",
        "instances": 1,
        "sources": [f"{DOC_CN}/doc-8287334", REPO_URL + " nodes/llm_chat.py"],
        "verification": "doc_verified",
        "notes": "个人 Key 未实测(文档标注企业共享 Key 限定);Anthropic/Gemini 协议端点路径未在公开文档列明",
    },
]

# MiniMax 官方价目锚点(H3 系列,人民币,2026-09-13 抓取 platform.minimax.cn)。
# 用途:RunningHub 标准模型 API 的 H3 价格未公开,以官方原厂价作下界锚点与
# 第三方透传校准;RunningHub 实际扣费以平台结算为准。
MINIMAX_ANCHOR_CNY = {
    "source": "https://platform.minimax.cn/docs/guides/pricing-paygo",
    "collected_at": COLLECTED_AT,
    "h3_768p_cny_per_second": 0.50,
    "h3_2k_cny_per_second": 0.80,
    "h3_max_480p_cny_per_second": 0.33,
    "h3_max_768p_cny_per_second": 0.50,
    "regen_768p_to_2k_output_cny_per_second": 0.30,
    "regen_768p_to_2k_input_video_cny_per_second": 0.30,
    "regen_image_cny_each_after_5_free": 0.15,
    "h3_image_cny_each_after_5_free": 0.20,
    "context_ir_input_cny_per_mtoken": 5.80,
    "context_ir_output_cny_per_mtoken": 23.00,
    "usd": {"h3_768p_usd_per_second": 0.08, "h3_2k_usd_per_second": 0.13,
            "source": "https://platform.minimax.io/docs/guides/pricing-paygo"},
}

# 已核验的真实运行费用证据(来自本仓库本地运行记录,gitignored)。
# 字段语义:consumeCoins=平台币;thirdPartyConsumeMoney=第三方模型费(元);
# taskCostTime=任务耗时秒(不是金额);output_seconds=成片秒数(每秒成本分母)。
RUN_EVIDENCE = [
    {
        "record": "output/runninghub/api/h3_standard_app_runs/20260912T113649Z-d0a65f81/run.json",
        "route": "ai-app(官方标准应用: Minimax H3 文生视频工作流)",
        "webapp_id": "2083105376052006914",
        "task_id": "2098737586251202562",
        "child_task_id": "2098737633676382210",
        "endpoint_model": "minimax/hailuo-h3(经应用内工作流调用)",
        "request": {"resolution": "2K", "duration": "5", "ratio": "16:9"},
        "status": "SUCCESS",
        "output_measured": {"width": 2560, "height": 1440, "fps": 24,
                            "duration_seconds": 5.167, "has_audio": True,
                            "video_codec": "h264", "audio_codec": "aac"},
        "usage": {"consumeCoins": 7, "consumeMoney": None,
                  "thirdPartyConsumeMoney": 3.85, "taskCostTime": 309,
                  "output_seconds": 5},
        "collected_at": "2026-09-12",
        "reverified_at": "2026-09-13",
        "verification": "real_run_success+cost_verified",
    },
    {
        "record": "output/runninghub/api/h3_personal_app_runs/20260912T093142Z-1eb2579a/run.json",
        "route": "ai-app(自定义应用: minimax-h3-文生视频)",
        "webapp_id": "2084613917401243650",
        "task_id": None,
        "request": {"resolution": "2K", "duration": "5"},
        "status": "FAILED(414 TASK_CREATE_FAILED_BY_NOT_ENOUGH_POWER_VALUE)",
        "usage": None,
        "collected_at": "2026-09-12",
        "verification": "channel_restriction_observed",
        "notes": "自定义应用按算力值闸门,未起跑未扣费",
    },
    {
        "record": "output/runninghub/api/h3_t2v_runs/20260912T085951Z-56e33ed8/run.json",
        "route": "standard-model-api(minimax/hailuo-h3/text-to-video)",
        "request": {"resolution": "2K", "duration": "5", "ratio": "16:9"},
        "status": "FAILED(1014 仅限企业级共享 Key)",
        "usage": None,
        "collected_at": "2026-09-12",
        "reverified_at": "2026-09-13",
        "verification": "channel_restriction_observed",
    },
    {
        "record": "docs/04-电商AI工作流/14-RunningHub-H3视频能力单元API调研.md §6",
        "route": "workflow-api(rh-h3-hoodie-v3, 0.2MP≈352×608, 非 768P 档)",
        "task_id": "2097529689961885697",
        "status": "SUCCESS",
        "output_measured": {"width": 352, "height": 608, "fps": 24, "duration_seconds": 5.167},
        "usage": {"consumeCoins": 14, "taskCostTime": 67},
        "collected_at": "2026-09-09",
        "verification": "real_run_success+cost_verified",
        "notes": "工作流按运行秒计币 ≈0.21 币/秒;此为工作流算力费,不是 768P 模型档价格",
    },
    {
        "record": "output/runninghub/api/matrix_runs/20260916T003929Z-94d031-wf-inline/task_record.json",
        "route": "workflow-api(开源 H3 权重工作流 h3-t2v-open-768p-cloud.json, plus 实例)",
        "task_id": "2100021717924806657",
        "request": {"prompt": "与 09-12 2K 实测同一提示词", "megapixels": 0.98,
                     "aspect_ratio": "16:9 (Widescreen)", "duration_s": 5, "steps": 8},
        "status": "SUCCESS",
        "output_measured": {"width": 1344, "height": 768, "fps": 24,
                             "duration_seconds": 5.167, "has_audio": True,
                             "video_codec": "h264", "audio_codec": "aac",
                             "sha256_12": "f5176d6b99d9"},
        "usage": {"consumeCoins": 78, "taskCostTime": 195, "thirdPartyConsumeMoney": None},
        "collected_at": "2026-09-16",
        "verification": "real_run_success+cost_verified",
        "notes": "渠道=平台工作流托管开源 H3 权重(fl2va int8+8步turbo LoRA), 按运行秒计币(78/195=0.4 币/秒, plus 档);非标准模型 API 的 768P 档, 分辨率由工作流 ResolutionSelector 控制(megapixels 0.98=1344x768, 与官方 768p 标注一致)",
    },
    {
        "record": "output/runninghub/api/matrix_runs/20260915T134805Z-174788-wf-inline/task_record.json",
        "route": "workflow-api(SD1.5 最小文生图诊断, 判别 414 闸门范围)",
        "task_id": "2099857788745515009",
        "status": "SUCCESS",
        "output_measured": {"note": "512x512 image"},
        "usage": {"consumeCoins": 3, "taskCostTime": 12},
        "collected_at": "2026-09-15",
        "verification": "real_run_success+cost_verified",
        "notes": "证明工作流 API 钱包计费正常;414 仅挡 RH_ 闭源模型节点与 AI 应用(算力值闸门), 不挡普通工作流",
    },
    {
        "record": "output/runninghub/api/matrix_runs/20260914T143052Z-5925ed-wf-inline/task_record.json",
        "route": "workflow-api(直传 RH_MinimaxHailuoH3TextToVideo 节点, 768P/5s/16:9)",
        "request": {"resolution": "768P", "duration": "5", "ratio": "16:9"},
        "status": "SUBMIT_REJECTED(414 TASK_CREATE_FAILED_BY_NOT_ENOUGH_POWER_VALUE)",
        "usage": None,
        "cost_cny": 0,
        "collected_at": "2026-09-14",
        "verification": "channel_gate_observed",
        "notes": "工作流 API 创建在计费闸门被拒,任务未创建、未扣费;经 docs/05 examples/python/rh_min_client.py run-workflow 入口执行",
    },
    {
        "record": "output/runninghub/api/matrix_runs/20260914T143223Z-4f0ea9-aiapp-2083105376052006914/task_record.json",
        "route": "ai-app(官方应用 2083105376052006914, 2K/5s/16:9)",
        "request": {"resolution": "2K", "duration": "5", "ratio": "16:9"},
        "status": "SUBMIT_REJECTED(414 TASK_CREATE_FAILED_BY_NOT_ENOUGH_POWER_VALUE)",
        "usage": None,
        "cost_cny": 0,
        "collected_at": "2026-09-14",
        "verification": "account_state_observed",
        "notes": "同应用同类参数 2026-09-12 成功(taskId 2098737586251202562);2026-09-14 与 2026-09-15 两次重试均被 414:账户算力值/余额耗尽且无按日刷新(持续账户状态,非渠道关闭或应用下架);经 rh_min_client.py run-ai-app 入口执行",
    },
]

GAPS = [
    {"id": "account-balance-exhausted", "severity": "blocker",
     "detail": "2026-09-14 起账户算力值/余额耗尽(2026-09-15 复测仍 414,无按日刷新):工作流 API(414)与官方 AI 应用(同码)均在创建闸门被拒,任务未创建、零扣费。三个关键成片任务(A 768P / B 2K 直出 / C 768P→2K)全部受阻,直至充值或获得新授权额度。恢复后最小待执行命令见 docs/05-RunningHub-API/README.md。"},
    {"id": "h3-rh-price", "severity": "high",
     "detail": "RunningHub 标准模型 API 的 H3 端点(含 768P/2K/regeneration)在官方公开定价文件(pricing.public.json, 353 条, 2026-04-29)中零条目;price-preview 接口个人 Key 返回 1014。需企业级-共享 Key 调 price-preview 或实跑一条任务才能得到平台侧官方价。"},
    {"id": "coin-cny-rate", "severity": "high",
     "detail": "consumeCoins(平台币)与人民币的官方兑换比例未在公开文档找到。旁证:第三方代充 1000 币≈¥14–19;doc14 工作假设 ¥0.02/币(未对账确认)。所有「币→元」换算必须标注此缺口。"},
    {"id": "ai-app-coin-semantics", "severity": "medium",
     "detail": "AI 应用任务 7 币/309s 的计费规则(按次、按秒还是按应用定价)与工作流 API 的 ≈0.2 币/秒不一致,平台未公开 AI 应用计费公式。需对照控制台「任务与账单」明细。"},
    {"id": "openapi-export", "severity": "medium",
     "detail": "官方文档站为 Apifox 托管(runninghub.cn/runninghub-api-doc-cn),未发现公开的 OpenAPI/Swagger 导出文件;接口族清单以文档页+官方仓库客户端代码核对。"},
    {"id": "seedance-2.5-price", "severity": "medium",
     "detail": "seedance-2.5-token(480p–4k, 4–30s)与 wan-3.0、h3-max-turbo、gemini-omni-1.1 等新端点(2026-04 快照后新增的 39 个)无公开定价条目。"},
    {"id": "llm-protocols", "severity": "low",
     "detail": "LLM API 声称兼容 OpenAI/Anthropic/Gemini 三种协议,但仅 chat/completions 路径有公开文档;Anthropic(/v1/messages)与 Gemini 端点路径未公开列明。"},
    {"id": "account-billing-api", "severity": "low",
     "detail": "账户余额、任务账单明细、任务列表查询未发现公开 API(仅网页控制台「任务与账单」);费用对账目前依赖任务 usage 字段+人工查账。"},
    {"id": "h3-768p-pixels", "severity": "low",
     "detail": "H3 768P 档的实际输出像素未实测(推断 16:9 下为 1344×768,依据 regeneration 接口对源视频的约束:尺寸被 32 整除、面积上限 768×1344)。2K 已实测 2560×1440。"},
    {"id": "output-url-validity", "severity": "low",
     "detail": "产物 URL 位于平台对象存储且有时效,官方建议及时转存,但具体有效时长未在公开文档列明;实测任务次日(2026-09-13)产物 URL 仍可访问。"},
    {"id": "dynamic-apps-unbounded", "severity": "info",
     "detail": "AI 应用/工作流为动态社区实例(平台应用市场持续新增),无法穷举;已交付通用 webappId/workflowId 调用机制+本仓库已验证实例清单,不声称覆盖全部私人实例。"},
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_models(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["models"] if isinstance(data, dict) else data


def resolution_options(model: dict) -> list[str]:
    for p in model.get("params") or []:
        if p.get("fieldKey") in ("resolution", "targetResolution"):
            vals = []
            for o in p.get("options") or []:
                vals.append(o.get("value") if isinstance(o, dict) else o)
            return [str(v) for v in vals if v is not None]
    return []


def duration_options(model: dict) -> list[str]:
    for p in model.get("params") or []:
        if p.get("fieldKey") == "duration":
            vals = []
            for o in p.get("options") or []:
                vals.append(o.get("value") if isinstance(o, dict) else o)
            return [str(v) for v in vals if v is not None]
    return []


def audio_flag(model: dict) -> str:
    """Best-effort classification of audio input/output billing switches."""
    keys = {p.get("fieldKey") for p in model.get("params") or []}
    if {"generateAudio", "generateAudioSwitch", "sound"} & keys:
        return "可选音轨(参数开关)"
    if "audioUrls" in keys:
        return "支持音频参考输入"
    return "未声明"


def build_capabilities(models: list[dict], pricing_by_ep: dict) -> list[dict]:
    """One registry entry per model endpoint. Verification status is honest:
    schema comes from the official registry (doc_verified); nothing is marked
    real-run unless this workspace actually ran it (only via app/workflow
    routes, never the standard model API directly)."""
    h3_t2v = "minimax/hailuo-h3/text-to-video"
    out = []
    for m in models:
        ep = m.get("endpoint", "")
        pr = pricing_by_ep.get(ep)
        res = resolution_options(m)
        entry = {
            "id": ep,
            "name_cn": m.get("name_cn") or m.get("display_name"),
            "name_en": m.get("name_en"),
            "class_name": m.get("class_name"),
            "output_type": m.get("output_type"),
            "category": m.get("category"),
            "method": "POST",
            "path": f"/openapi/v2/{ep}",
            "params": [
                {k: p.get(k) for k in ("fieldKey", "type", "required", "description",
                                       "defaultValue", "options", "maxLength", "accept",
                                       "maxSize") if p.get(k) is not None}
                for p in m.get("params") or []
            ],
            "resolution_options": res,
            "duration_options": duration_options(m),
            "audio": audio_flag(m),
            "supports_768p": "768P" in res or "768p" in res,
            "supports_2k": any(r.lower() in ("2k",) for r in res),
            "pricing": (
                {"currency": pr.get("currency"), "unit": pr.get("unit"),
                 "pricing_type": pr.get("pricing_type"), "depends_on": pr.get("depends_on"),
                 "rules": pr.get("rules"), "price": pr.get("price"),
                 "snapshot_version": pr.get("updated_at") or "public-2026-04-29",
                 "status": "official_listed_price"}
                if pr else
                {"status": "no_public_price", "note": "官方公开定价文件无此端点条目"}
            ),
            "verification_status": "schema_verified",
            "verification_notes": [],
            "sources": [MODELS_URL, f"{DOC_CN}/doc-8287334"],
        }
        if ep == h3_t2v:
            # 证据范围严格限定:仅文生视频端点、仅 2K 档、仅官方 AI 应用渠道、
            # 2026-09-12 一次成功样本。不给 i2v/多模态/768P/标准模型 API 外推。
            entry["verification_status"] = "schema_verified+real_run_2k_via_ai_app+real_run_768p_via_open_workflow"
            entry["verification_notes"] = [
                "闭源模型证据:2K 档经官方 AI 应用(2083105376052006914)2026-09-12 一次成功;09-14/15 复跑被 414(算力值闸门)",
                "开源权重证据:768P(1344x768)经平台工作流托管开源 H3 权重 2026-09-16 实测成功(78 币/195s, plus 0.4 币/秒), 见 run_evidence;此路线分辨率由工作流参数控制, 不等于标准模型 API 的 resolution=768P 档",
                "标准模型 API 直调(768P/2K)均未实测(个人 Key 1014;企业 Key 才可)",
            ]
        elif ep.startswith("minimax/hailuo-h3"):
            entry["verification_status"] = "schema_verified"
            entry["verification_notes"] = [
                "未实测;2K 成功证据仅覆盖 t2v 端点的 AI 应用渠道,不外推到本端点",
            ]
        out.append(entry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-registry", type=Path, default=Path("/tmp/rh-survey/models_registry_current.json"))
    ap.add_argument("--pricing", type=Path,
                    default=Path("/tmp/rh-survey/ComfyUI_RH_OpenAPI/developer-kit/pricing.public.json"))
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.models_registry.exists():
        print(f"models registry not found locally, downloading {MODELS_URL}", file=sys.stderr)
        args.models_registry.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODELS_URL, args.models_registry)
    models = load_models(args.models_registry)
    pricing_doc = json.loads(args.pricing.read_text(encoding="utf-8"))
    pricing_by_ep = {p["endpoint"]: p for p in pricing_doc.get("pricing") or []}

    capabilities = build_capabilities(models, pricing_by_ep)
    fam_instances = sum(f["instances"] for f in ENDPOINT_FAMILIES if isinstance(f["instances"], int))
    model_count = len(capabilities)
    priced = sum(1 for c in capabilities if c["pricing"]["status"] == "official_listed_price")
    vid = [c for c in capabilities if c["output_type"] == "video"]
    v768 = [c for c in vid if c["supports_768p"]]
    v2k = [c for c in vid if c["supports_2k"]]

    # 显式覆盖清单(不做总数相减):官方仓库根注册表 vs 官方 kit 快照的差异,
    # 以及无公开价格条目的端点全集;重复端点检测。
    kit_path = args.models_registry.parent / "ComfyUI_RH_OpenAPI/developer-kit/model-registry.public.json"
    if not kit_path.exists():
        kit_path = Path("/tmp/rh-survey/ComfyUI_RH_OpenAPI/developer-kit/model-registry.public.json")
    added_vs_kit = []
    if kit_path.exists():
        kit_models = json.loads(kit_path.read_text(encoding="utf-8"))
        if isinstance(kit_models, dict):
            kit_models = kit_models["models"]
        kit_eps = {m["endpoint"] for m in kit_models}
        added_vs_kit = sorted({m["endpoint"] for m in models} - kit_eps)
    missing_price = sorted(c["id"] for c in capabilities
                           if c["pricing"]["status"] != "official_listed_price")
    dup_check = {}
    for m in models:
        dup_check[m["endpoint"]] = dup_check.get(m["endpoint"], 0) + 1
    duplicates = sorted(e for e, n in dup_check.items() if n > 1)

    registry = {
        "meta": {
            "name": "RunningHub 公开 API 能力注册表",
            "scope": "RunningHub 平台正式开放且公开可访问的 API(中国大陆站 runninghub.cn 为主,国际站 runninghub.ai 并行)",
            "collected_at": COLLECTED_AT,
            "reverified_at": REVERIFIED_AT,
            "freshness": {
                "official_registry_sha256": REGISTRY_SHA256,
                "note": f"{REVERIFIED_AT} 重新下载官方注册表,SHA256 与 {COLLECTED_AT} 快照一致(内容未变化);缓存可信复用",
            },
            "region": "CN(primary)/intl(mirror)",
            "dedup_rule": "模型端点以官方 models_registry.json 的 endpoint 字段唯一键去重;一个通用提交接口承载全部模型端点,接口数按接口族统计而非按模型数",
            "excluded": ["私人/未公开工作流与 AI 应用实例(动态无界, 以通用调用机制覆盖)",
                          "本地部署、GPU 租赁、其他云平台"],
            "coverage_lists": {
                "added_vs_kit_snapshot": added_vs_kit,
                "added_vs_kit_source": str(kit_path) + " (public-2026-04-29)",
                "missing_public_price": missing_price,
                "duplicate_endpoints": duplicates,
                "note": "missing_public_price 不含工作流/AI 应用/素材族;模型端点缺价=官方定价文件(快照 2026-04-29)无该 endpoint 条目",
            },
            "counts": {
                "http_endpoint_families": len(ENDPOINT_FAMILIES),
                "http_endpoint_instances_curated": fam_instances,
                "model_capabilities": model_count,
                "model_capabilities_with_public_price": priced,
                "model_capabilities_missing_public_price": len(missing_price),
                "video_capabilities": len(vid),
                "video_supports_768p": len(v768),
                "video_supports_2k": len(v2k),
                "duplicate_endpoints": len(duplicates),
                "verified_live_this_workspace": [
                    "/openapi/v2/query (个人 Key, 2026-09-13)",
                    "/openapi/v2/price-preview/* (个人 Key → 1014, 2026-09-13)",
                    "/openapi/v2/assets/query (个人 Key, 业务校验可达, 2026-09-13)",
                    "/task/openapi/* 工作流+AI 应用(个人 Key, 2026-09-09~12 实跑;2026-09-14 起 414 账户算力值耗尽)",
                    "/api/webapp/apiCallDemo (个人 Key, 2026-09-14 实测)",
                ],
            },
            "key_types": {
                "consumer-member": "消费级-会员(个人):AI 应用 API、工作流 API",
                "enterprise-shared": "企业级-共享:全部四种 API(模型/LLM/AI 应用/工作流)",
                "enterprise-dedicated": "企业级-独占:AI 应用 API、工作流 API(需购买独占机器)",
            },
            "lifecycle_conventions": {
                "poll_interval_seconds": "官方示例 5 秒;视频任务上限建议 20 分钟(本地超时≠平台任务失败,保留 taskId 可续查)",
                "output_url_validity": "产物位于平台 COS(rh-images-*.cos.ap-beijing.myqcloud.com / rh-images.xiaoyaoyou.com),URL 有时效,官方建议及时转存;具体有效时长未在公开文档列明(见 gaps)",
                "retry": "仅瞬态错误(网络/429/5xx)指数退避重试;参数错误/余额/内容审核等确定性错误不重试;提交失败但结果不确定时禁止盲重试(可能重复扣费)",
                "concurrency": "共享 Key 有并发上限(超限 421 TASK_QUEUE_MAXED,退避重试);独占机器不足 415;独占 Key 可用 usePersonalQueue(上限 1000);企业共享 Key 可用 retainSeconds 保留实例复用(按保留时长另计费)",
                "seed": "API 调用强制重置 seed,同参数两次运行结果不同(官方文档)",
                "error_codes": "全表见官方 doc-8287338;高频码:301 参数错/414 算力或余额不足/416 余额不足/421 并发上限/802 Key 失效/805 任务失败含节点级 failedReason/807 任务不存在/808-809 上传失败/1014 模型与 LLM API 限企业共享 Key/1501 内容审核/1505 禁止真人/1006 执行超时",
            },
        },
        "endpoint_families": ENDPOINT_FAMILIES,
        "model_capabilities": capabilities,
        "pricing_anchors": {"minimax_official_cny": MINIMAX_ANCHOR_CNY},
        "run_evidence": RUN_EVIDENCE,
        "gaps": GAPS,
    }

    out: Path = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    reg_path = out / "runninghub-api-registry.json"
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # flat human-readable catalog
    csv_path = out / "model-capabilities.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["endpoint", "名称(中文)", "输出类型", "分类", "分辨率选项",
                    "时长选项(秒)", "音频", "支持768P", "支持2K",
                    "公开价格(快照2026-04-29)", "验证状态"])
        for c in capabilities:
            price = c["pricing"]
            ptxt = ""
            if price["status"] == "official_listed_price":
                ptxt = f"{price.get('currency')} {price.get('price') if price.get('price') is not None else '按参数'} {price.get('unit')}"
            else:
                ptxt = "无公开价"
            w.writerow([c["id"], c["name_cn"], c["output_type"], c["category"],
                        "|".join(c["resolution_options"]), "|".join(c["duration_options"]),
                        c["audio"], "是" if c["supports_768p"] else "否",
                        "是" if c["supports_2k"] else "否", ptxt, c["verification_status"]])

    # sources snapshot with hashes
    sources = {
        "collected_at": COLLECTED_AT,
        "reverified_at": REVERIFIED_AT,
        "freshness_audit": {
            "method": "重新下载官方 raw 文件并与快照做 SHA256 对比;不一致才视为内容更新",
            "models_registry": {
                "snapshot_sha256_0913": REGISTRY_SHA256,
                "redownloaded_sha256_0914": REGISTRY_SHA256,
                "result": "identical(缓存可信,标注为快照+复检日期,不标注为当日新采集)",
                "warning": "raw.githubusercontent 偶发截断响应(2026-09-14 首次重下 1.09MB/完整 1.43MB),必须以 JSON 可解析+SHA256 对比为准",
            },
        },
        "sources": [
            {"id": "official-model-registry", "url": MODELS_URL,
             "repo": REPO_URL, "repo_last_commit": "8f9c858 2026-09-10",
             "file": str(args.models_registry), "sha256": sha256_file(args.models_registry),
             "model_count": model_count, "role": "422 个标准模型端点定义(官方组织维护, Apache-2.0)"},
            {"id": "official-kit-pricing", "url": KIT_URL,
             "file": str(args.pricing), "sha256": sha256_file(args.pricing),
             "version": pricing_doc.get("version"), "pricing_count": pricing_doc.get("pricing_count"),
             "role": "353 条公开安全定价(快照 2026-04-29, 不含 H3)"},
            {"id": "official-docs-cn", "url": DOC_CN + "/doc-8287334",
             "role": "API 总览/Key 类型/调用流程(当日核对)"},
            {"id": "official-docs-h3-regen", "url": DOC_EN + "/api-498427804",
             "role": "H3 Regeneration 768P→2K 端点契约(当日核对)"},
            {"id": "minimax-cny-pricing", "url": MINIMAX_ANCHOR_CNY["source"],
             "role": "H3 官方原厂人民币价(锚点)"},
            {"id": "minimax-usd-pricing", "url": MINIMAX_ANCHOR_CNY["usd"]["source"],
             "role": "H3 官方原厂美元价(锚点)"},
            {"id": "local-run-records", "role": "本仓库实跑费用证据",
             "files": [e["record"] for e in RUN_EVIDENCE]},
        ],
    }
    (out / "sources-snapshot.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"registry: {reg_path} ({reg_path.stat().st_size} bytes)")
    print(f"catalog:  {csv_path}")
    print(f"families={len(ENDPOINT_FAMILIES)} models={model_count} priced={priced} "
          f"video={len(vid)} 768p={len(v768)} 2k={len(v2k)}")
    print("768P video endpoints:")
    for c in v768:
        print("  +", c["id"])
    print("2K video endpoints:")
    for c in v2k:
        print("  +", c["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
