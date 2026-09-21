# RunningHub API 接入与成本资料

> 自动生成于证据维护版本 2026-09-21；模型集合日期 2026-09-13。这不是实时全平台或全账户验收。
> 输入：`data/handoff-evidence.json`（价格/证据/权益）与 `data/runninghub-api-registry.json`（模型契约与历史价格快照）。不要手改生成文件。


## 入口

[API与覆盖报告](01-调研报告.md) · [完整成本报告](02-768P-2K费用报告.md) · [HTML报告](runninghub-h3-2k-api.html) · [实际接入与验收](04-接入与费用验收.md) · [当天公开价目与目录复核](06-公开报价与目录复核.md)

## 当前结论

当前匿名中国站目录244项，显式2K视频26项，目标价表26/26已取得；与保留的GitHub快照分列，见06-公开报价与目录复核.md。

| 渠道 | 5秒 | 10秒 | 15秒 | 状态 |
|---|---|---|---|---|
| 企业共享H3文生2K | ¥3.85 | ¥7.70 | ¥11.55 | 2026-09-21官方公开价；非企业实扣账单 |
| 企业共享H3文生768P | ¥2.40 | ¥4.80 | ¥7.20 | 精确文生端点，不外推其他H3家族 |
| 个人AI应用2K | 历史实测 ¥3.85 + 5–7 RH币 | 按5秒样本线性模型费预算 ¥7.70 + RH币未知（未实测） | 按5秒样本线性模型费预算 ¥11.55 + RH币未知（未实测） | 混合单位，人民币总成本未闭合 |
| 768P→regeneration 2K | 两阶段各计费5秒时预算 ¥3.90（未实扣） | 两阶段各计费10秒时预算 ¥7.80（未实扣） | 两阶段各计费15秒时预算 ¥11.70（未实扣） | 公开阶段预算，不是实际账单 |
| 独占GPU应用/工作流 | 租金未知 | 利用率未知 | 摊销未知 | 租期内运行秒增量为0不代表总成本为0 |

本版本完成资料/数据/客户端一致性修复，不把“离线验收通过”当作“所有企业和两阶段账单已实跑通过”。具体缺口及关闭标准在费用报告中逐项列出。

## 生成与检查

```bash
python3 scripts/rh_survey_build_registry.py           # 离线重建；不谎报新采集日期
python3 scripts/rh_survey_build_cost_tables.py        # 同一生成器，非第二套手写价格
python3 scripts/rh_survey_build_cost_tables.py --check # 只校验，发现漂移时退出非0
python3 -m unittest discover -s tests/scripts -p 'test_rh_handoff*.py' -v
```

显式刷新模型快照使用`python3 scripts/rh_survey_build_registry.py --refresh`，或`--models-registry <官方JSON>`；可用`--pricing <官方pricing.public.json>`更新对应历史价格来源。下载失败不覆盖已提交数据；价格覆盖只匹配精确端点+分辨率。刷新目录不自动刷新价目或任务证据。

## 最小调用

```bash
CLIENT=docs/05-RunningHub-API/examples/python/rh_min_client.py
# 无密钥、无网络的计划检查
python3 "$CLIENT" run minimax/hailuo-h3/text-to-video \
  '{"prompt":"一只橙猫在雨后屋顶缓慢行走","resolution":"2K","duration":"5","ratio":"16:9"}'
# 通过安全环境变量配置RH_API_KEY后，以下只读命令可用
python3 "$CLIENT" account
python3 "$CLIENT" price minimax/hailuo-h3/text-to-video \
  '{"prompt":"一只橙猫在雨后屋顶缓慢行走","resolution":"2K","duration":"5","ratio":"16:9"}'
# 只有明确增加 --execute 才可能创建付费任务；不要在仓库或shell历史里写真实Key
```

## 数据契约

`runninghub-api-registry.json`：模型契约/历史价格；`handoff-evidence.json`：有日期的历史样本、权益和缺口，并以SHA256绑定`public-pricing-20260921.json`的当日官方网页原始报价和目录；所有CSV/报告/HTML由这些明确来源生成。新增价格必须写来源、日期、单位、精确端点与证据等级。未知不是零；页面报告不是本轮实测；实际像素不同于分辨率标签。

CSV采用UTF-8 BOM和英文机器字段。`price_per_second_cny`只表示该模型阶段单价；`five_second_cost`等才表示标注条件下的总价/预算，不完整路线必须保留`full_cost_status=incomplete`。计费输出秒、媒体秒和运行秒分别建模。
