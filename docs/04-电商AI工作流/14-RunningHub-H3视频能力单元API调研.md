# RunningHub 版 MiniMax H3：视频能力单元 API 调研

> 调研日期：2026-09-07；实跑完成：2026-09-09（充值 ¥20 后 H3 全链路跑通并通过 doc13 验收）。
> 工作流功能验收标准见[RunningHub H3 卫衣等条件复跑](13-RunningHub-H3卫衣等条件复跑.md)，实跑结果见本文 §6。

## 1. 目标与结论

目标：把 H3 R2V（商品图 + 动作参考视频 + 提示词 → 带音频竖屏视频）工作流封装成一个「视频能力单元」，形态对齐主流闭源视频 API（阿里 wan3.0）：

```text
用户 → 赢海AIGC（自有中间层）→ RunningHub OpenAPI → 云端 ComfyUI（rh-h3-hoodie-v3.json）
```

- **固定入参**：画幅、分辨率、时长、提示词、参考媒体（图片/视频）。
- **固定出参**：生成视频 URL、运行状态、错误码与失败原因。
- **异步化**：提交任务返回 `taskId`，轮询或 webhook 拿结果。

### 调研结论（TL;DR）

| # | 结论 |
| --- | --- |
| 1 | RunningHub OpenAPI 本身就是「异步任务」形态，`create` 返回 `taskId` → 轮询 `/openapi/v2/query`（或 webhook 推送）→ `results[].url`。查询接口齐备，不需要自建任务表以外的查询能力。 |
| 2 | 输出不是自家 OSS，而是 RunningHub 的对象存储（腾讯云 COS）。中间层应把 `fileUrl` 转存到自家 OSS 后再返回长期 URL，对齐 wan3.0「video_url 24 小时有效、及时转存」的官方建议。 |
| 3 | 单条成本接口自证：查询结果里直接返回 `taskCostTime` / `consumeCoins` / `consumeMoney`。**实跑校准（2026-09-09）：H3 热实例 67 秒 / 14 币 ≈ ¥0.28 一条，冷启动估计 ¥0.8–1.3**，比"5–8 元"的保守估计低一个数量级；计费与模型无关，纯按机器运行秒计（≈0.2 币/秒）。 |
| 4 | H3 闭源 API（768P ¥0.50/秒）不是替代项而是**质量对照项**：同模型、同 prompt 对比开源工作流与闭源 API 的商品一致性，作为换装效果的基线。（注意：RunningHub 平台的标准模型 H3 端点仅企业级-共享 Key 可用，个人 Key 实测 1014。） |
| 5 | ⚠️ 官方文档明确「API 调用会强制重置 seed」。这与 doc13 的固定 seed 等条件复跑策略冲突：走 API 时只能以「通过率」（如 3 跑 2 过）验收，不能用单次固定种子；严格单变量对照仍需平台手动运行。 |

## 2. RunningHub OpenAPI（工作流 API）摘要

### 2.1 前置条件

| 事项 | 说明 |
| --- | --- |
| API Key | 控制台 `https://www.runninghub.cn/enterprise-api/consumerApi` 创建。三类：消费级-会员 / 企业级-共享 / 企业级-独占。**工作流 API 三类都可用**（标准模型 API 仅限企业级-共享 Key）。 |
| `workflowId` | 在平台导入工作流并保存后由平台分配。 |
| `nodeInfoList` 的 nodeId/fieldName | 来自工作流的 **api_format JSON**（工作流页面「导出 API」按钮下载），不要按画布顺序猜。官方说明：[About nodeInfoList](https://www.runninghub.ai/runninghub-api-doc-en/doc-8287464)。 |
| 工作流文件名 | ≤ 50 字符（doc13 已按此约束命名 `rh-h3-hoodie-v3.json`）。 |
| 48G 机器 | `create` 时传 `instanceType: "plus"`；需先在平台用对应机器调试保存工作流（[原生 ComfyUI 接口支持](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287337)）。H3 量化组合约 41 GiB，24G 机器跑不了完整 INT8 组合，**API 任务建议直接指定 plus**。 |

### 2.2 提交任务：`POST /task/openapi/create`

请求体（[高级版文档](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749013)）：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `apiKey` | 是 | 请求头同时要求 `Authorization: Bearer <apiKey>` |
| `workflowId` | 二选一 | 平台保存的工作流 ID；若传 `workflow`（完整 JSON）则忽略此字段 |
| `nodeInfoList` | 否 | `[{nodeId, fieldName, fieldValue}]`，执行前替换节点参数 |
| `webhookUrl` | 否 | 任务结束回调地址（见 2.6） |
| `instanceType` | 否 | `"plus"` = 48G 显存机器 |
| `retainSeconds` | 否 | 10–180 秒，企业共享 Key 专属：任务结束后保留实例供复用，**按保留时长额外计费** |
| `accessPassword` | 否 | 工作流开启加密访问时使用 |
| `usePersonalQueue` | 否 | 独占 Key 专属队列，上限 1000 |

响应（异步，立即返回）：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "taskId": "1910246754753896450",
    "taskStatus": "QUEUED",
    "clientId": "e825290b08ca2015b8f62f0bbdb5f5f6",
    "netWssUrl": null,
    "promptTips": "{\"result\": true, \"error\": null, \"node_errors\": {}}"
  }
}
```

- `taskStatus`：`QUEUED` / `RUNNING`（此时 `netWssUrl` 给出实时进度 WebSocket）/ `FAILED`。
- `promptTips` 非空且 `node_errors` 非空时，说明提交前节点校验已失败（参数名错误、缺媒体等），应立即失败，不消耗运行时长。
- `clientId` 建议保存，供 WebSocket 重连。

### 2.3 上传参考媒体：`POST /task/openapi/upload`

form-data：`apiKey`、`fileType: "input"`、`file`。返回 `{"fileName": "api/xxxx.jpg", "fileType": "image"}`。
该 `fileName` 就作为 `LoadImage` / `LoadVideo` 节点的 `fieldValue`。失败对应错误码 808/809。

另一种方式：工作流内用 `LoadImageFromUrl` 节点直接吃自建图床 URL，省一次上传往返（官方 nodeInfoList 说明页推荐给文生图场景）。视频侧是否有对应 FromUrl 节点待实机确认，跑通阶段统一走 upload 接口。

### 2.4 查询状态与结果

**新接口（推荐）：`POST /openapi/v2/query`**，请求体仅 `{taskId}`（[文档](https://www.runninghub.cn/runninghub-api-doc-cn/api-425767306)）：

```json
{
  "taskId": "2009191190196789249",
  "status": "SUCCESS",
  "errorCode": "",
  "errorMessage": "",
  "results": [
    { "url": "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/.../output/<uuid>.mp4",
      "outputType": "mp4" }
  ],
  "clientId": "",
  "promptTips": ""
}
```

`status`：`QUEUED` / `RUNNING` / `SUCCESS` / `FAILED`（`FAILED` 时 `errorCode` 对应 2.5 错误码表）。

**旧接口（已废弃，仍在部分文档中被引用）**：

- `POST /task/openapi/status` —— 官方标注「停止维护」。
- `POST /task/openapi/outputs` —— 标记 deprecated，但响应里带 **成本字段**，做成本校准比 V2 更有用：`data[]` 元素含 `fileUrl`、`fileType`、`taskCostTime`（秒）、`nodeId`、`consumeCoins`（RH 币）、`consumeMoney`（钱包金额）。失败时 `data.failedReason` 给出 `node_name`、`node_id`、`exception_type`、`exception_message`、`traceback`，可直接用于排查是哪个节点崩了。

**建议**：功能轮询用 V2；成本与失败归因另打一次 `outputs`。官方示例轮询间隔 5 秒、超时 600 秒；H3 任务按 20 分钟设上限更稳。

### 2.5 错误码对照（[官方全表](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287338)）

能力单元需要重点处理/映射的码：

| 码 | 标识 | 语义 | 能力单元建议动作 |
| --- | --- | --- | --- |
| 0 | success | 成功 | — |
| 301 | PARAMS_INVALID | 参数错误 | 4xx，直接失败 |
| 380 | WORKFLOW_NOT_EXISTS | 工作流不存在 | 5xx 配置错误，告警 |
| 415 | TASK_INSTANCE_MAXED | 独占机器数不足 | 429 重试 |
| 416 | TASK_CREATE_FAILED_BY_NOT_ENOUGH_WALLET | 余额不足 | 5xx 告警 + 暂停派发 |
| 421 | TASK_QUEUE_MAXED | 共享 Key 并发上限 | 429 退避重试 |
| 433 | VALIDATE_PROMPT_FAILED | 工作流校验未通过 | 4xx，透传 msg |
| 802 | APIKEY_UNAUTHORIZED | Key 失效 | 5xx 配置错误，告警 |
| 804 | APIKEY_TASK_IS_RUNNING | 运行中（旧接口状态语义） | 继续轮询 |
| 805 | APIKEY_TASK_STATUS_ERROR | 任务异常/失败，`failedReason` 有节点级堆栈 | 5xx，记录归因 |
| 807 | APIKEY_TASK_NOT_FOUND | 任务不存在/过期 | 4xx |
| 808/809 | 上传失败/超限 | 素材问题 | 4xx |
| 813 | APIKEY_TASK_IS_QUEUED | 排队中 | 继续轮询 |
| 1501 | 内容审核未通过 | 提示词/图片违规 | 4xx 透传给用户 |
| 1505 | 禁止生成真人 | 竖屏带货视频场景常见 | 4xx 透传 |
| 1006 | 任务执行超时 | — | 429/5xx 视策略 |

### 2.6 Webhook（可选，跑通后再用）

`create` 传 `webhookUrl` 后，任务结束平台会 POST：

```json
{ "event": "TASK_END", "taskId": "…", "eventData": "{\"fileUrl\": \"…\", \"fileType\": \"mp4\", \"nodeId\": \"92\"}" }
```

`eventData` 是**字符串化的 JSON**，需要二次解析。轮询与 webhook 不互斥；跑通期只用轮询即可。

### 2.7 与 `rh-h3-hoodie-v3.json` 的节点映射

| 能力单元入参 | 节点 ID | 节点类型 | fieldName | 说明 |
| --- | --- | --- | --- | --- |
| 商品/参考图 | 137 | `LoadImage` | `image` | upload 返回的 `fileName` |
| 动作参考视频 | 147 | `LoadVideo` | `file` | ⚠️ 原生 `LoadVideo` 的字段名是 `file`，不是 `video`（源码 `comfy_extras/nodes_video.py:297`） |
| 提示词 | 138 | `PrimitiveStringMultiline` | 以导出 api_format 为准（常见 `value`/`string`） | |
| 画幅 | 115 | `ResolutionSelector` | `aspect_ratio` | 枚举如 `"9:16 (Portrait Widescreen)"`（`comfy_extras/nodes_resolution.py:7-23`） |
| 分辨率 | 115 | `ResolutionSelector` | `megapixels` | 0.2 起步；H3 帧数要求 `17n+5` |
| 时长（秒） | 132 | `PrimitiveFloat` | `value` | 工作流内 `ComfyMathExpression`（节点 131）自动折算成 `17n+5` 帧数 |
| 加速开关 | 146 | `PrimitiveBoolean` | `value` | Turbo 4 步 LoRA |
| 输出 | 92 | `SaveVideo` | — | 结果取 `nodeId=92` 的 `fileUrl` |
| （不可覆盖） | 129 | `RandomNoise` | `seed` | ⚠️ API 调用强制重置 seed，固定种子验收只能手动运行 |

> `fieldValue: []` 表示该字段有连线，官方不建议 API 覆盖。最终以平台导出的 api_format JSON 为准后再写死映射。

## 3. 视频能力单元 API 契约（对齐 wan3.0 设计）

### 3.1 wan3.0 的设计理念（借鉴点）

阿里[万相3.0 API](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference) 的形态：`create` 提交 `{model, input, parameters}` 异步返回 `task_id`；`GET /tasks/{task_id}` 轮询，`output.task_status` ∈ `PENDING/RUNNING/SUCCEEDED/FAILED/UNKNOWN`，成功后 `output.video_url` **24 小时有效**；`usage` 返回计费口径。值得照搬的三点：

1. **`input.media` 数组 + 类型标签**（`reference_image` / `reference_video`），prompt 里用「图1 / 视频1」按序引用 —— 与 H3 R2V 的 `<Picture 1>` / `<Video 1>` 占位符天然同构。
2. **`parameters` 与 `input` 分离**：分辨率/画幅/时长是运行参数，不混进语义输入。
3. **结果 URL 有时效**，官方明确要求调用方及时转存 —— 我们转存自家 OSS，把「时效」变成「长期」。

### 3.2 契约定义（赢海AIGC 中间层暴露给上层）

**创建任务** `POST /api/v1/video/generations`

```json
{
  "model": "minimax-h3-r2v",
  "input": {
    "prompt": "<Picture 1> is the only clothing identity reference: …不复制 <Video 1> 原服装",
    "media": [
      { "type": "reference_image", "url": "https://our-oss.example/product/1977-hoodie.png" },
      { "type": "reference_video", "url": "https://our-oss.example/benchmark-24fps.mp4" }
    ]
  },
  "parameters": {
    "resolution": "0.2MP",
    "ratio": "9:16",
    "duration": 5,
    "turbo": true
  }
}
```

响应 `202`：

```json
{ "task_id": "yh-20260907-xxxx", "task_status": "PENDING", "request_id": "req-…" }
```

**查询任务** `GET /api/v1/video/generations/{task_id}`（轮询建议 5s，超时 20min）

```json
{
  "task_id": "yh-20260907-xxxx",
  "task_status": "SUCCEEDED",
  "output": {
    "video_url": "https://our-oss.example/results/xxxx.mp4",
    "duration": 5.167, "fps": 24, "width": 352, "height": 608
  },
  "usage": { "runtime_seconds": 243, "coins": 97.2, "money": 1.95 },
  "error": { "code": null, "message": null }
}
```

### 3.3 状态机映射

| 能力单元 `task_status` | RunningHub V2 `status` | 旧接口 code | 语义 |
| --- | --- | --- | --- |
| `PENDING` | `QUEUED` | 813 | 排队/已受理 |
| `RUNNING` | `RUNNING` | 804 | 运行中 |
| `SUCCEEDED` | `SUCCESS` | 0 | 有 `results[].url` |
| `FAILED` | `FAILED` | 805 等 | `error` 带 RunningHub `errorCode` + `failedReason` 摘要 |
| `EXPIRED`（可选） | — | 423/807 | taskId 过期未查询 |

错误码设计：能力单元对外只暴露稳定枚举（`INVALID_ARGUMENT / RATE_LIMITED / CONTENT_REJECTED / UPSTREAM_FAILED / INSUFFICIENT_BALANCE`），原始 RunningHub code 放在 `error.details.upstream_code` 供排查，避免把平台私有码泄漏成对外契约。

### 3.4 输出 URL 生命周期

RunningHub `fileUrl` 位于其 COS（`rh-images-*.cos.ap-beijing.myqcloud.com` / `rh-images.xiaoyaoyou.com`），不宜直接当产品 URL。中间层在收到 `TASK_END` 或轮询到 `SUCCEEDED` 后：下载 → 上传自家 OSS（按 task_id 归档）→ 返回长期 `video_url`，并保留 RunningHub 原始 URL 与 `taskId` 便于对账复跑。

### 3.5 参考媒体落地方式（对 24 FPS 约束的提醒）

| 方式 | 流程 | 适用 |
| --- | --- | --- |
| A. upload 接口 | 中间层下载用户 URL → `/task/openapi/upload` → `fileName` 填 nodeInfoList | 跑通期首选，链路可控 |
| B. `LoadImageFromUrl` | 工作流节点直连用户图床 URL | 图片可用；视频节点待实机确认 |
| C. 预处理前置 | 30 FPS 原视频先由中间层 ffmpeg 转 24 FPS（doc13 的硬性要求）再上传 | **A/B/C 都绕不开**：H3 参考视频必须 24 FPS，这是能力单元服务端要承担的前处理，不能甩给用户 |

## 4. 成本对比

### 4.1 三个选项

| 维度 | A. MiniMax 闭源 API（H3） | B. RunningHub 工作流托管 | C. 租 GPU 自部署 |
| --- | --- | --- | --- |
| 单价 | 768P **¥0.50/秒**、2K **¥0.80/秒**；参考图 >5 张每张 +¥0.20（2026-08 公开报道） | 按运行秒数计费：24G 标准 0.2 RH币/秒、48G Plus 0.4 RH币/秒（**实跑校准：28s→6 币、67s→14 币，与 0.2 币/秒吻合**）；企业 API 从人民币钱包扣（与 RH 币两个钱包，实测独立） | AutoDL/智星云/算家云 4090 24G ≈ ¥1.3–3.4/h（「3 元/h」在区间内）；免费额度见 [GPU 资源参考](../03-GPU资源参考/free-gpu-compute-list.md) |
| 5 秒视频单条估算 | 768P：¥2.5；2K：¥4.0 | **实测：热实例 ¥0.28/条（14 币/67s）**；冷启动含 41 GiB 加载约 2–4 分钟，估计 ¥0.8–1.3/条；连续生产时热实例复用可稳定在 ¥0.3–0.6 | 持续生产：120s 采样 × ¥3/h ≈ **¥0.10** + 加载摊销，冷启动整段 ≥ 5 分钟 ≈ **¥0.3–0.5/条**；RTX 5060 8GB 本地实测 120.39 秒/条（doc10/13） |
| 上手成本 | 最低（注册即用） | 低：导入 JSON → 拿 workflowId → 3 个接口 | 高：部署 ComfyUI + 模型 41 GiB + 队列/监控/弹性伸缩自建 |
| 能力自由度 | 低：API 参数固定，换装/多参考自由度受限于官方暴露面 | 高：任何 ComfyUI 工作流皆可上架，改 JSON 即改能力 | 最高：节点、量化、内存策略全可控（项目已有 NVFP4/INT8/8GB 方案） |
| 风险 | 单价随官方政策变；数据出境/合规按平台规则 | 任务失败仍计运行时长；排队波动；seed 强制重置 | 冷启动贵：H3 加载 2–5 分钟，弹性缩容会放大单位成本，需常驻实例 |

### 4.2 结论（2026-09-09 实测后修订）

- **B 已实测跑通且成本远低于预期**：热实例单条 ¥0.28、冷启动 ¥0.8–1.3。跑通期与中小批量（日均几十条）直接用 B；保持连续派单可维持实例热度摊薄加载成本。
- **量产后迁 C 的触发条件**：日均稳定 >200 条、或需要更高质量档（0.4MP+）。自部署的前提是解决常驻实例 + 任务队列 + 24 FPS 前处理。
- **A 定位为对照与兜底**：同 prompt 同素材跑一次闭源 H3 作为质量基线；高价值订单兜底。注意 RunningHub 的标准模型 H3 端点要企业 Key；走 MiniMax 官方 API 则直接可用。

## 5. 跑通清单（✅ 2026-09-09 已完成）

> 以下步骤已全部执行完毕，留档作为复跑指引；可复跑资产在 `output/runninghub/api/`（git 忽略）。

1. ~~**账号**~~ ✅ 注册 + 钱包充值 ¥20（API 计费与 RH 币/积分是两个钱包）。
2. ~~**上架工作流**~~ ✅ 改为 `workflow` 直传：无需在平台导入保存。`convert_ui_to_api.py` 把 `rh-h3-hoodie-v3.json` 转成 API 格式（nodeInfoList 与直传工作流不互通，动态参数直接烤进 JSON）。
3. ~~**最小脚本**~~ ✅ `run_h3_workflow.py`：上传素材 → 烤入 → create → 轮询 outputs → 下载 → 成本记录；`rh_client.py` 为契约 client。
4. ~~**成本校准**~~ ✅ 实测 0.2 币/秒（28s→6 币、67s→14 币），热实例单条 ¥0.28。
5. ~~**功能验收**~~ ✅ doc13 四项全过（taskId `2097529689961885697`），API 重置 seed 下一次通过，摘墨镜时序优于本地版。
6. **通过后（待做）**：按 §3 契约实现赢海AIGC 中间层——轮询改服务、OSS 转存、错误码映射；多商品/多视频泛化按 doc13 §6 顺序逐变量放开。

## 6. 实跑记录（留痕）

### 2026-09-09 充值 ¥20 后全链路跑通（验收通过）

| 任务 | taskId | 结果 | 成本 |
| --- | --- | --- | --- |
| SD1.5 最小文生图（`workflow` 直传首验） | `2097515969621745666` | ✅ 28 秒出图，`workflow` 直传生效 | 6 币（0.21 币/秒） |
| H3 v1（媒体走 nodeInfoList） | `2097519662874193922` | ❌ `803 node_not_found_in_workflow`（nodeInfoList 对着占位 workflowId 校验，与直传 workflow 不互通） | —（未起跑） |
| H3 v1b（媒体烤进工作流，codec 缺省） | `2097527112536915969` | ❌ 管线全程跑通，仅 `SaveVideo.execute() missing 'codec'` | 按运行秒计（实例已热） |
| H3 v2（codec 嵌套 dict） | `2097529655111413761` | ❌ `Value not in list`（DynamicCombo 嵌套形态被拒） | 同上 |
| **H3 v3（codec 纯字符串 "auto"）** | **`2097529689961885697`** | ✅ **352×608、24FPS、5.167 秒；doc13 四项验收全部通过** | **14 币 / 67 秒（热实例 0.21 币/秒）** |

关键实测结论（修正调研期推断）：

1. **计费模型**：工作流 API 按运行秒计费，与模型无关（SD1.5 与 H3 同为 ≈0.2 币/秒）。H3 热实例复用（同 clientId 连续任务）时单条仅 14 币 ≈ **¥0.28**；冷启动需另计 41 GiB 模型加载（按公开费率约 2–4 分钟 ≈ 25–50 币），冷启动单条估计 **¥0.8–1.3**。**单条成本比 §4.1 预估低一个数量级，"5–8 元/条"的说法被实测否定。**
2. **`workflow` 直传可用**（个人消费级 Key）：传完整 API 格式 JSON 字符串 + `workflowId: "1"` 占位。但 `nodeInfoList` 与直传工作流不互通（803），动态参数须烤进 JSON。
3. **动态参数两个坑**：`SaveVideo.codec` 平台版必填，唯一可用形态是纯字符串 `"auto"`；失败任务 10 秒内返回且实例保持热（上游节点缓存命中），参数迭代极便宜。
4. **验收**：API 强制重置 seed 下一次通过卫衣四项（商品身份/结构/`1977`/摘墨镜时序），时序表现优于本地固定 seed 版。产物视频已存 `output/runninghub/api/runs/2097529689961885697/output.mp4`（RunningHub COS 原始 URL 另存于 final_outputs.json，需及时转存）。

可复跑资产（均在 `output/runninghub/api/`，git 忽略）：

- `convert_ui_to_api.py`：UI→API 格式确定性转换器（28 节点，widget 槽位对齐 + 点号动态输入 + codec 形态已固化）
- `run_h3_workflow.py`：一键全链路（上传→烤入→create→轮询→下载→成本记录）；`--query <taskId>` 可复查
- `rh_client.py`：契约 client（upload/submit/poll 分层，瞬态重试）

### 2026-09-07 个人 Key 能力面探测（全程零消耗）

| # | 探测 | 接口 | 结果 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | 伪 taskId 查询 | `POST /openapi/v2/query` | HTTP 200，`1007 must be greater than 0` | Bearer 鉴权通过，Key 有效 |
| 2 | 标准模型 API 提交 `minimax/hailuo-h3/multimodal-to-video` | `POST /openapi/v2/...` | `1014` Standard Model API 仅限企业级-共享 Key | **闭源 H3 端点个人 Key 不可用（实锤）**；`/media/upload/binary` 上传本身可用 |
| 3 | 工作流 API 上传 | `POST /task/openapi/upload` | `code 0`，返回 `api/xxx.png` / `api/xxx.mp4` | 个人 Key 可用 |
| 4 | create 格式校验（`workflowId` 占位 + `workflow` 直传 API 格式 JSON） | `POST /task/openapi/create` | `workflowId=''`→301；`'0'`→301 must be greater than 0；`'1'`→**414** | 参数校验全部通过，请求到达计费闸门 |
| 5 | 计费闸门（H3 工作流 / 0.1MP / plus / SD1.5 最小工作流 / 故意缺参的坏工作流） | 同上 | 全部 `414 TASK_CREATE_FAILED_BY_NOT_ENOUGH_POWER_VALUE` | **API 算力值独立于平台积分（≈0）**；计费校验先于工作流内容校验（坏工作流返回 414 而非 433），`workflow` 直传是否生效需余额可用后验证 |

- UI→API 格式确定性转换器与产物：`output/runninghub/api/convert_ui_to_api.py` → `rh-h3-hoodie-v3-api-format.json`（28 节点，widget 槽位对齐 + 点号动态输入按服务端 `build_nested_inputs` 扁平键规则）。
- 契约 client 与跑通脚本（余额可用后即跑）：`output/runninghub/api/rh_client.py`、`run_h3_multimodal.py`（标准模型 API，企业 Key 适用）、`run_h3_workflow.py`（工作流 API，个人 Key 适用）。
- **2026-09-09 充值 ¥20 后该阻塞解除，H3 全链路当日跑通并通过验收**，详见上表。

## 7. 来源

RunningHub 官方（中文文档站）：

- [开始 - RunningHub-API](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287334)（提交 → taskId → 查询 → 结果 总流程）
- [发起 ComfyUI 任务-高级](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749013)（`nodeInfoList`/`webhookUrl`/`instanceType`/`retainSeconds`）
- [查询任务生成结果 V2](https://www.runninghub.cn/runninghub-api-doc-cn/api-425767306)（`/openapi/v2/query`）
- [查询任务生成结果（旧）](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749004)（`consumeCoins`/`failedReason` 成本与归因字段）
- [接口错误码说明](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287338)
- [AI 应用完整接入示例](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287339)（upload + 轮询 5s/600s 示例）
- [工作流完整接入示例](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287342)、[nodeInfoList 说明](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287336)（API 强制重置 seed 等）
- [企业 API 计费](https://www.runninghub.cn/enterprise-api/sharedApi)、[原生 ComfyUI 接口支持（48G）](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287337)

成本旁证：

- MiniMax 官方 [视频定价](https://platform.minimax.io/docs/guides/pricing-video)（H3 走按量付费；资源包暂不含 H3）；H3 国内单价（768P ¥0.50/秒、2K ¥0.80/秒）来自 2026-08 SegmentFault 对比报道与 OpenRouter/PoYo.ai 等渠道报价旁证。
- RunningHub 计费：新浪财经 2025-10《RunningHub 按下“加速键”：全面优化算力成本》报道（¥4/h 标准、¥6/h Plus、按秒计费，仅标题检索可得未留档原文）；RH 币充值比例见[官方教程帖](https://www.runninghub.cn/post/1961661249467695105)与第三方代充行情（1000 币 ≈ ¥14–19），**口径未完全对齐，以首条实测为准**。
- 算力租赁行情与免费额度：[free-gpu-compute-list](../03-GPU资源参考/free-gpu-compute-list.md)。

仓库内关联文档：

- [11-RunningHub-MiniMax-H3导入与首跑](11-RunningHub-MiniMax-H3导入与首跑.md)（平台节点/模型清单）
- [13-RunningHub-H3卫衣等条件复跑](13-RunningHub-H3卫衣等条件复跑.md)（验收标准、24 FPS 前处理、固定 seed 策略）
- [10-映海爆款带货视频本地复刻](10-映海爆款带货视频本地复刻.md)（本地 120.39 秒/条基线）
