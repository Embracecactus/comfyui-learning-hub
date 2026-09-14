# 通用视频/图像能力单元 API 服务（RunningHub 工作流无关封装）

> 2026-09-09 上线。目标：**工作流无关**的能力单元封装——后续新增任何 ComfyUI 工作流，只需加一份能力清单（manifest），不改代码。
> 代码：`scripts/rh_capability_api/`（版本管理）；运行时数据（密钥/任务库/产物）在 `output/runninghub/api/`（git 忽略）。

## 1. 与 doc14 契约的对应

doc14 §3 定义了 wan3.0 风格契约（`input.media` + `parameters` + 异步任务），本服务是其实现：

| 契约概念 | 实现 |
| --- | --- |
| `model` | `capability`（能力名 = 清单文件名） |
| `input.prompt` + `input.media[]` | `input` 对象（参数名由清单定义，媒体支持本地路径/HTTP URL/已上传 fileName） |
| `parameters`（resolution/ratio/duration） | `parameters` 对象（清单里声明映射到哪个节点哪个字段，含 enum 值翻译） |
| `POST 创建任务 → task_id` | `POST /v1/tasks` → `202 {"task_id": "cap-…", "task_status": "PENDING"}` |
| `GET /tasks/{id}` 轮询 | `GET /v1/tasks/{task_id}` → `task_status: PENDING/RUNNING/SUCCEEDED/FAILED` + `output[]` + `usage` + `error` |
| 错误码稳定枚举 | RunningHub code → `INVALID_ARGUMENT / RATE_LIMITED / INSUFFICIENT_BALANCE / CONTENT_REJECTED / MEDIA_REJECTED / TASK_NOT_FOUND / UPSTREAM_FAILED`（原始码在 `error.upstream_code`） |
| video_url 24h 时效 → 转存 | 任务成功后自动下载产物到 `artifacts/<task_id>/`（`output[].local_path`），OSS 转存在 `_collect()` 一处接入 |

## 2. 新增一个工作流 = 新增一份清单

```json
{
  "capability": "my-new-capability",
  "title": "…",
  "output": "video",
  "workflowFile": "output/runninghub/api/my-workflow-api-format.json",
  "outputNodes": ["92"],
  "params": {
    "prompt":  {"node": "138", "field": "value", "type": "string", "required": true},
    "image":   {"node": "137", "field": "image", "type": "image", "required": true},
    "ratio":   {"node": "115", "field": "aspect_ratio", "type": "enum", "default": "9:16",
                "values": {"9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)"}},
    "duration": {"node": "132", "field": "value", "type": "number", "default": 5}
  }
}
```

要点（全部来自实跑教训，doc14 §6）：

- 基础工作流必须是 **API 格式**（UI 格式先用 `output/runninghub/api/convert_ui_to_api.py` 转换，codec/点号输入等坑已固化在转换器里）。
- `nodeInfoList` 与直传工作流不互通 → 所有动态参数**烤进工作流 JSON**，`nodeInfoList` 恒为空。
- `outputNodes` 按节点 ID 过滤产物，多输出节点的工作流只取声明节点。
- 媒体参数类型为 `image/video/audio`，引擎自动走 `/task/openapi/upload`（内容寻址，同名去重）。

## 3. 使用

```bash
# 能力目录（自描述参数 schema）
python3 scripts/rh_capability_api/cli.py --config output/runninghub/api/config.json list

# 直接跑一个任务并等结果（媒体传本地路径）
python3 scripts/rh_capability_api/cli.py --config output/runninghub/api/config.json run h3-r2v-vertical \
  --input '{"prompt": "...", "image": "hoodie.png", "video": "ref-24fps.mp4"}' --param duration=5

# 查询历史任务（SQLite 持久化，跨重启可查）
python3 scripts/rh_capability_api/cli.py --config ... query cap-82c278c1e2374272

# HTTP 服务（赢海AIGC 中间层对接形态）
python3 scripts/rh_capability_api/server.py --config ... --manifests scripts/rh_capability_api/manifests \
  --db output/runninghub/api/capability_tasks.db --artifacts output/runninghub/api/artifacts \
  --repo-root . --port 8077
```

curl 示例：

```bash
curl -X POST http://127.0.0.1:8077/v1/tasks -d '{
  "capability": "h3-r2v-vertical",
  "input": {"prompt": "…", "image": "https://our-oss/hoodie.png", "video": "https://our-oss/ref.mp4"},
  "parameters": {"ratio": "9:16", "duration": 5}
}'
# 202 {"task_id": "cap-…", "task_status": "PENDING", "upstream_task_id": "…"}

curl http://127.0.0.1:8077/v1/tasks/cap-…
# {"task_status": "SUCCEEDED", "output": [{"type": "video", "url": "…", "local_path": "…"}],
#  "usage": {"runtime_seconds": "76", "coins": "16"}}
```

## 4. 首批两个能力（通用性验证，同一引擎零改动）

| 能力 | 类型 | 基础工作流 | 实跑 |
| --- | --- | --- | --- |
| `sd15-t2i` | 图像（纯文生图，内嵌 workflowInline） | 经典 SD1.5 默认工作流 | ✅ 21s / 5 币 |
| `h3-r2v-vertical` | 视频（商品图+动作参考+提示词→带音频竖屏） | `rh-h3-hoodie-v3` API 格式 | ✅ 76s / 16 币，画面验收同 doc13 |

## 5. 计费（工作流 API，2026-09-09 实测）

- 计费与模型无关，**纯按机器运行秒数**：实测 21s→5 币、28s→6 币、67s→14 币、76s→16 币（≈0.21 币/秒）。
- `outputs` 接口只回 `consumeCoins`（`consumeMoney` 恒 null），人民币口径需对照控制台「账户明细」。
- 冷启动（41 GiB H3 模型加载）计入运行时长；连续派单时实例保持热，单条 5 秒视频约 **14–16 币**。

## 6. 边界与后续

- 运行中任务依赖本进程轮询；服务重启后用 `store.pending_with_rh_id()` 续查（轮询线程启动即接管）。
- 并发上限遵循 RunningHub 共享 Key 限制（421 时按 RATE_LIMITED 退避）。
- API 强制重置 seed（平台行为），同请求两次运行结果不同；确定性需求要走种子管理或后处理筛选。
- OSS 转存、webhook 通知、参数校验增强（如 24 FPS 前处理）按 doc14 §3 规划接入。
