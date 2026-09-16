# RunningHub API 调研与接入资料(docs/05)

2026-09-13 完成的 RunningHub 全量公开 API 盘点、可复用接入方案,
以及从头生成 768P / 2K 视频的完整费用核验;**2026-09-14/15 复验**:
客户端修复(任务恢复/付费闸门/下载归档)、注册表证据范围收窄、
官方快照 SHA256 复检一致、账户余额阻塞记录(见下表)。

## 渠道验证状态(截至 2026-09-15,个人消费级 Key,站点点 .cn)

| 渠道 | 状态 | 证据 |
| --- | --- | --- |
| `/openapi/v2/query` 查询 | ✅ 已验证 | 2026-09-13/14 实测,usage 费用字段完整 |
| `resume`/`outputs`(续查/下载/费用归因) | ✅ 已验证 | 2026-09-14,下载文件 sha256 与 09-12 归档一致 |
| `/api/webapp/apiCallDemo` 应用参数 | ✅ 已验证 | 2026-09-14;注意:响应会回显 apiKey,勿外传原文 |
| AI 应用生成(官方应用 2083105376052006914,2K/5s) | ✅ 2026-09-12 一次成功(¥3.85+7 币);**2026-09-14 起被 414 拒(09-15 复测仍拒)** | "算力值"钱包耗尽且无按日刷新,任务未创建、零扣费;同应用同参数 09-12 曾成功(账户状态,非渠道关闭) |
| 工作流 API 生成(普通节点) | ✅ **已验证**(2026-09-15/16) | SD1.5 诊断成功(3 币/12s);**开源 H3 768P 文生视频成功(taskId 2100021717924806657,78 币/195s,1344×768@24fps 带音轨)** |
| 工作流 API 生成(RH_ 闭源模型节点) | ⛔ 2026-09-14 创建闸门 414 | 平台是否原生接管 RH_ 节点鉴权未验证;"算力值"闸门挡在内容校验之前 |
| 标准模型 API(含 768P/2K/regeneration 直调、price-preview) | ⛔ 仅企业级-共享 Key | 个人 Key 实测 1014(09-07/09-12/09-13 三次) |
| C 路线(768P→2K regeneration) | ⛔ 未实测 | 需标准模型 API(企业 Key)或已验证的应用/工作流渠道;**没有 A 的 768P 源视频前也无法执行** |

**恢复付费验证的最小待执行命令**(前提:账户充值或获得含算力值的授权;
按序执行,A 的产物供 C 复用):

```bash
export RH_API_KEY=<个人或企业 Key>
CLIENT=docs/05-RunningHub-API/examples/python/rh_min_client.py
# A. 768P 文生视频(开源 H3 权重工作流,已实测成功路线;plus=48G 实例)
python3 $CLIENT run-workflow - \
  --inline docs/05-RunningHub-API/examples/workflows/h3-t2v-open-768p-cloud.json \
  --instance-type plus --execute
# B. 2K 直出(AI 应用路线,与 2026-09-12 成功样本同参数,预估 ¥3.85+7 币)
python3 $CLIENT run-ai-app 2083105376052006914 \
  '[{"nodeId":"1","fieldName":"prompt","fieldValue":"一只橙色猫在雨后的城市屋顶上缓慢行走，电影感镜头，光线自然。","description":"prompt"},{"nodeId":"1","fieldName":"resolution","fieldValue":"2K","description":"resolution 分辨率"},{"nodeId":"1","fieldName":"duration","fieldValue":"5","description":"duration 时长（秒）"},{"nodeId":"1","fieldName":"ratio","fieldValue":"16:9","description":"ratio 比例"}]' \
  --execute
# C. 768P→2K(需 A 成功产出源视频;上传源视频后按 02-费用报告 §2 C 行执行,
#    标准模型 API 需企业级-共享 Key)
```

## 文档

| 文件 | 内容 |
| --- | --- |
| [01-调研报告.md](01-调研报告.md) | 工程可复用资产、14 接口族 + 422 模型覆盖统计、Key 类型矩阵、验证状态体系、方式 A/B 评估、缺口汇总 |
| [02-768P-2K费用报告.md](02-768P-2K费用报告.md) | 从提示词到成片的完整价格结论(5/10/15 秒)、三种情形(A/B/C)核验、实测证据链、价格冲突、缺口 |
| [03-下一阶段开发goal.md](03-下一阶段开发goal.md) | 基于已查明事实的下一步:企业 Key 核价 → 币值对账 → 方式 A 资料包定稿 → 条件触发的托管立项 |

## 数据(机器可读)

| 文件 | 内容 |
| --- | --- |
| [data/runninghub-api-registry.json](data/runninghub-api-registry.json) | 主注册表:14 接口族 + 422 模型能力(参数 schema/分辨率/时长/音频/768P·2K 标记/价格/验证状态)+ MiniMax 价格锚点 + 4 条实测费用证据 + 9 条缺口 |
| [data/model-capabilities.csv](data/model-capabilities.csv) | 人工可读扁平目录(422 行) |
| [data/cost-768p.csv](data/cost-768p.csv) | 768P 从头生成费用对照(9 行 × 21 列,价格类型四分:官方标价/实测/推算/缺口) |
| [data/cost-2k.csv](data/cost-2k.csv) | 2K 从头生成费用对照(12 行,含直出与两阶段路线) |
| [data/sources-snapshot.json](data/sources-snapshot.json) | 来源快照(URL/时间/SHA256) |

## 接入原型(供别人使用,方式 A)

- [examples/python/rh_min_client.py](examples/python/rh_min_client.py)
  ——零依赖最小客户端:通用传输(鉴权/上传/预估/提交/轮询/取消/
  工作流/AI 应用)与模型参数分离,`RH_API_KEY` 环境变量注入,无硬编码密钥。
- [examples/curl/](examples/curl/) ——五个可直接执行的场景:
  `01` H3 768P 直出、`02` H3 2K 直出、`03` 768P→2K 官方两阶段、
  `04` AI 应用路线(个人 Key,已实测)、`05` ComfyUI 工作流路线。

## 更新方法

```bash
python3 scripts/rh_survey_build_registry.py      # 重拉官方快照,重建注册表与目录
python3 scripts/rh_survey_build_cost_tables.py   # 修订价格后重建两张费用 CSV
```

安全约定:任何交付不入库 API Key/Cookie/令牌/私人任务签名链接;
费用证据仅引用 taskId 与 usage 字段。
