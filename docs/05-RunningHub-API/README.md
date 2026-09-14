# RunningHub API 调研与接入资料(docs/05)

2026-09-13 完成的 RunningHub 全量公开 API 盘点、可复用接入方案,
以及从头生成 768P / 2K 视频的完整费用核验。

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
