# RunningHub H3 卫衣等条件复跑

这次不再发明新路线，而是把本地已经视觉验收通过的 MiniMax H3 卫衣案例按相同条件移植到 RunningHub。目标只有一个：先证明云端也能得到黑色连帽卫衣、长袖、宽松轮廓和胸前 `1977`，再讨论通用化。

> 当前状态：**2026-09-09 已通过 RunningHub 云端 API 实跑验收**（taskId `2097529689961885697`，四项标准全过）。API 路线的完整过程与成本见[第 14 章](14-RunningHub-H3视频能力单元API调研.md)。

## 1. 为什么上一版失败

旧 H3 平台版并不是本地成功版的等条件复跑，它同时改坏了三个变量：

| 项目 | 本地已通过版 | 旧 RunningHub H3 版 |
| --- | --- | --- |
| 视频片段 | `5.0–10.2 秒` | `0–5.2 秒` |
| 商品提示词 | 明确 hoodie、长袖、帽子、口袋、袖口和 `1977` | 泛化服装，并错误保留 `flower positions` |
| 文字约束 | 明确 `1977` 是商品自带文字，必须保留 | 笼统禁止 logo/文字，与商品冲突 |
| 参考帧率 | 显式重采样到 `24 FPS` | 30 FPS 原帧直接进入 H3，随后只截前 124 帧 |

后来尝试的 Wan V2 也不适合这个输入。Wan Animate 的参考图语义是完整人物/角色图，不是平铺服装图，所以它只生成了黑色内搭，没有建立卫衣与人体的穿着关系。

## 2. 导入正确文件

下载并导入：

[`workflows/rh-h3-hoodie-v3.json`](workflows/rh-h3-hoodie-v3.json)

文件名是 `rh-h3-hoodie-v3.json`，共 20 个字符，没有超过 RunningHub 的 50 字限制。

这份图直接由本地已通过的 `1977` 卫衣工作流派生，只移除了 RunningHub 没有的六个内存管理节点，并把解码改为平台已有的官方节点。商品端口、视频端口、基础模型、LoRA、采样器、固定 seed、0.2 MP、124 帧以及卫衣专用提示词均未泛化。

## 3. 先准备 24 FPS 完整参考视频

本地原始对标视频是 `30 FPS`。ComfyUI H3 节点要求参考视频按 `24 FPS` 理解；如果把 30 FPS 帧直接送入，它只会截取前 124 帧，相当于只看约 4.13 秒，动作时间轴与本地成功版不一致。

在 Windows 命令提示符执行：

```bat
ffmpeg -y -i "yinghai-copy-hot-video-v2-01-benchmark.mp4" -vf "fps=24" -an -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p "yinghai-benchmark-24fps.mp4"
```

这里要转换**完整视频**，不要提前只截后半段。工作流里的 `Video Slice` 会继续按本地成功条件截取 `5.0–10.2 秒`。

转换后核对：

```bat
ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate,width,height -show_entries format=duration -of default=noprint_wrappers=1 "yinghai-benchmark-24fps.mp4"
```

必须看到 `avg_frame_rate=24/1`，时长应仍约 `10.87 秒`。

## 4. RunningHub 只上传两个文件

### 4.1 Picture 1

找到：

```text
① 上传1977卫衣商品图｜Picture 1（固定验收）
```

上传与本地成功版相同的 `01-product-1977-hoodie.png`。不要先换成另一件商品。

### 4.2 Video 1

找到：

```text
② 上传24FPS完整对标视频｜Video 1（取5.0–10.2秒）
```

上传刚生成的 `yinghai-benchmark-24fps.mp4`，不要再上传原始 30 FPS 文件，也不要上传只截过后半段的短片。

### 4.3 不要修改提示词

节点：

```text
③ 固定验收提示词｜不要修改
```

已经写明以下商品身份：

- black pullover hoodie；
- long sleeves、hood、kangaroo pocket；
- ribbed cuffs and hem；
- exact white `1977` chest print；
- 不复制 Video 1 的白色露肩上衣和白色腰带。

首次复跑不要改提示词、seed、时长、分辨率、模型或 LoRA。一次只验证“本地成功条件能否在 RunningHub 重现”。

## 5. 运行后怎么判定

以下四项必须同时满足：

| 检查项 | 通过 | 失败 |
| --- | --- | --- |
| 上衣类型 | 黑色连帽卫衣 | 内衣、露肩上衣、连衣裙或其他上装 |
| 结构 | 帽子、长袖、宽松轮廓可识别 | 无帽、无袖、紧身内搭 |
| 商品文字 | 胸前可读出或稳定识别 `1977` | 没有文字或变成无关 Logo |
| 动作片段 | 是后半段近景/摘墨镜动作 | 仍是前半段行走片段 |

不要把“任务完成”“视频能播放”当作通过。只要没有穿上卫衣，就把任务 ID、运行时长、最终视频截图记入本文的实跑记录，不继续提高分辨率。

## 6. 通过后再做通用化

固定案例通过后，按下面顺序每次只换一个变量：

1. 保持视频、模型和参数不变，只换另一件结构明显的服装，并同步改商品提示词。
2. 保持已通过商品不变，只换一个预先转换为 24 FPS 的参考视频。
3. 两项分别通过后，才允许同时换商品和视频。
4. 最后再从 0.2 MP 提高分辨率。

这种顺序可以区分“商品语义失败”“视频时序失败”和“算力/画质失败”，避免一次改变全部条件后只能猜原因。

## 7. 生成与验证留痕

确定性生成命令：

```bash
node scripts/derive_runninghub_h3_workflow.mjs \
  docs/04-电商AI工作流/workflows/ecommerce-yinghai-copy-hot-video-h3-nvfp4-0.2mp-hoodie-second-half.json \
  docs/04-电商AI工作流/workflows/rh-h3-hoodie-v3.json
```

本地 H3 成功证据见[第 10 章](10-映海爆款带货视频本地复刻.md)：RTX 5060 8 GB 上生成 `352×608`、`24 FPS`、`5.167 秒`视频，耗时 `120.39 秒`；五个抽帧中均能识别 `1977`，帽子、长袖和宽松版型通过，墨镜动作时序只部分通过。

### RunningHub 实跑记录

| 日期 | 任务 ID | 耗时 | 商品替换 | 动作片段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-09 | `2097529689961885697` | 67 秒（热实例）| ✅ 黑色连帽卫衣上身，帽子/长袖/宽松版型/口袋齐全 | ✅ t≈2s 戴墨镜抬手 → t≈4s 摘下露脸 | **四项验收全部通过**，优于本地版（本地墨镜时序仅部分通过）。0.2MP、352×608、24FPS、5.167 秒，与本地成功版规格一致。成本 14 RH 币（≈0.21 币/秒） |

> 本次实跑走的是 **API 路线**（非网页手动运行）：媒体烤进 API 格式工作流直传，API 强制重置 seed 后一次通过。细节、成本与全部失败对照见[第 14 章 API 调研](14-RunningHub-H3视频能力单元API调研.md) §6。
