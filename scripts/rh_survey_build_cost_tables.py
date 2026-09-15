#!/usr/bin/env python3
"""Generate the 768P / 2K from-scratch video cost tables (CSV).

Prices are traced to exactly one of four provenance classes (价格类型):
  official_listed  官方标价(devloper-kit pricing snapshot 2026-04-29)
  measured         实测扣费(本仓库运行记录, 字段级引用)
  derived          推算(按已确认的官方每秒计费规则换算, 锚点注明)
  unlisted_gap     平台未公开价格(明确缺口, 不猜测)

Per-second costs use 成片秒(output seconds), never GPU/task seconds.
Coin amounts (consumeCoins) are kept in their own unit and never silently
converted to CNY (public exchange rate unresolved — see gaps).
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/05-RunningHub-API/data"

COLS = ["模型/端点", "调用渠道及Key条件", "地区", "生成方式", "分辨率标签", "实际像素",
        "支持时长(秒)", "音频", "阶段结构", "计费单位", "独立收费项明细",
        "5秒总价", "10秒总价", "15秒总价", "每成片秒成本", "币种/积分单位",
        "价格类型", "价格来源", "核验日期", "验证状态", "未确认事项"]

KIT_SNAPSHOT = "developer-kit/pricing.public.json 快照 public-2026-04-29"
MM_CN = "platform.minimax.cn/docs/guides/pricing-paygo(MiniMax 原厂参考价, 非 RunningHub 报价)"
MM_USD = "platform.minimax.io/docs/guides/pricing-paygo(MiniMax 原厂参考价)"
RUN_2K = "本仓库 run.json taskId=2098737586251202562(2026-09-12 实测, 2026-09-13 复核)"
BLOCK_414 = ("2026-09-14 起账户算力值耗尽:工作流与 AI 应用创建均被 414 拒(零扣费), "
             "复现需充值;原厂参考价≠RunningHub 报价,不构成平台价格下界证明")
UNVERIFIED_STD = ("RunningHub 平台侧价格未公开(官方定价文件无 H3 条目, "
                  "price-preview 需企业级-共享 Key);按 MiniMax 原厂参考价推算, "
                  "平台实际加价/折扣未知;" + BLOCK_414)


def mm_row(endpoint, mode, pixels, note="", audio="原生带音轨, 不另收费(MiniMax 原厂: 音频输入免费)"):
    return ["minimax/hailuo-h3 系列 " + endpoint.split("/")[-1] + f"({endpoint})",
            "标准模型 API·仅企业级-共享 Key", "CN", mode, "768P", pixels,
            "5–15(逐秒)", audio, "单阶段·单任务", "元/成片秒",
            "第三方模型费一项" + note,
            "¥2.50", "¥5.00", "¥7.50", "¥0.50", "CNY",
            "推算(MiniMax 原厂参考价)", MM_CN, "2026-09-13",
            "schema_verified(未实测)", UNVERIFIED_STD]


rows_768p = [
    mm_row("minimax/hailuo-h3/text-to-video", "文生视频", "推断 1344×768@16:9(未实测)"),
    mm_row("minimax/hailuo-h3/image-to-video", "图生视频(首/尾帧)",
           "推断(未实测)", note=";图片输入>5 张 ¥0.20/张另计"),
    mm_row("minimax/hailuo-h3/multimodal-to-video", "多模态参考(图/视频/音频)",
           "推断(未实测)", note=";图片>5 张 ¥0.20/张另计;视频输入按 ¥0.50/秒另计"),
    ["minimax/hailuo-h3-max/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频(ratio 必填)", "768P", "推断(未实测)", "5–15(逐秒)",
     "H3-Max 系列(T2V/I2V)", "单阶段·单任务", "元/成片秒", "第三方模型费一项",
     "¥2.50", "¥5.00", "¥7.50", "¥0.50", "CNY", "推算(MiniMax 原厂参考价)", MM_CN,
     "2026-09-13", "schema_verified(未实测)", UNVERIFIED_STD],
    ["minimax/hailuo-h3-max/image-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "图生视频(首/尾帧)", "768P", "推断(未实测)", "5–15(逐秒)",
     "H3-Max 系列", "单阶段·单任务", "元/成片秒", "第三方模型费一项",
     "¥2.50", "¥5.00", "¥7.50", "¥0.50", "CNY", "推算(MiniMax 原厂参考价)", MM_CN,
     "2026-09-13", "schema_verified(未实测)", UNVERIFIED_STD],
    ["minimax/h3-max-turbo/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频", "768p", "未确认", "5–15(逐秒)", "未确认", "单阶段·单任务",
     "未确认", "未确认", "缺口", "缺口", "缺口", "缺口", "—", "unlisted_gap",
     "官方定价文件无此新端点条目(2026-04 快照后新增)", "2026-09-13",
     "schema_verified", "价格缺口:需企业 Key 调 price-preview 或平台页面确认"],
    ["minimax/h3-max-turbo/image-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "图生视频", "768p", "未确认", "5–15(逐秒)", "未确认", "单阶段·单任务",
     "未确认", "未确认", "缺口", "缺口", "缺口", "缺口", "—", "unlisted_gap",
     "同上", "2026-09-13", "schema_verified", "价格缺口"],
    ["minimax/hailuo-h3/text-to-video(768P 档)", "AI 应用 API·个人消费 Key 可用(官方应用按实际用量计费)",
     "CN", "文生视频", "768P", "未实测", "5–15(逐秒)", "原生带音轨",
     "单任务(应用内封装)", "元/成片秒 + 平台币", "第三方模型费 + 平台算力币(768P 未实测)",
     "≈¥2.50 + 若干币", "≈¥5.00 + 若干币", "≈¥7.50 + 若干币", "≈¥0.50 + 币", "CNY+RH币",
     "推算(以 2K 实测结构外推, 见 2K 表第 1 行;2026-09-14 复现被 414 阻塞)", MM_CN + ";币值缺口未定;2026-09-14 复现被 414 阻塞",
     "2026-09-13", "推算(768P 未实测)", "平台币部分未实测且币→元比例未定"],
    ["(说明行) 工作流 API 路线", "工作流 API·个人 Key 可用", "CN",
     "任意自上架 ComfyUI 工作流", "由工作流决定(非 768P 档)", "实测 352×608@0.2MP 案例",
     "任意", "由工作流决定", "单任务", "平台币/运行秒",
     "仅机器运行秒计币(实测 21s→5 币, 28s→6 币, 67s→14 币, 76s→16 币 ≈0.21 币/秒), 失败也计费",
     "不适用", "不适用", "不适用", "实测 ≈0.21 币/运行秒(≠每成片秒)", "RH币",
     "实测(工作流算力口径)", "doc14 §6 实跑记录(2026-09-09)", "2026-09-09",
     "real_run_success", "工作流路线无 768P 模型档概念, 与模型价不可直接比较"],
]

rows_2k = [
    ["minimax/hailuo-h3/text-to-video(2K 档)", "AI 应用 API·个人消费 Key 可用(官方应用 2083105376052006914)",
     "CN", "文生视频", "2K", "实测 2560×1440@24fps", "5–15(逐秒)",
     "实测带 AAC 音轨, 未单独收费", "单任务·报价全含(未出现内部 768P 独立扣费)",
     "元(第三方) + RH币(平台)", "第三方模型费 ¥3.85(实测) + 平台算力币 7 币(实测);两个 usage 挂同一 taskId 链(parent 2098737586251202562 + child 2098737633676382210), 不重复累计",
     "实测 ¥3.85 + 7 币", "推算 ¥7.70 + 币", "推算 ¥11.55 + 币", "实测 ¥0.77/成片秒 + 币",
     "CNY+RH币", "实测(5s);10/15s 推算(官方按秒计费, 线性)", RUN_2K,
     "2026-09-12(09-13 复核)", "real_run_success+cost_verified",
     "10/15s 未实测;币→元未定;¥0.77/s 与 MiniMax 原厂标价 ¥0.80/s 差 3.7%(渠道折扣或汇率, 保留冲突证据);2026-09-14 同应用同参数复跑被 414(账户算力值耗尽), 渠道仍以 09-12 成功样本为准"],
    ["minimax/hailuo-h3/text-to-video(2K 档)", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频", "2K", "推断 2560×1440(同应用实测产物)", "5–15(逐秒)",
     "原生带音轨不另收费", "单阶段·单任务(报价全含)", "元/成片秒", "第三方模型费一项",
     "¥4.00", "¥8.00", "¥12.00", "¥0.80", "CNY", "推算(MiniMax 原厂参考价)", MM_CN,
     "2026-09-13", "schema_verified(未实测)",
     "实测第三方费为 ¥0.77/s, 标价口径 ¥0.80/s;RH 平台侧价格未公开"],
    ["minimax/hailuo-h3/image-to-video(2K 档)", "标准模型 API·仅企业级-共享 Key", "CN",
     "图生视频(首/尾帧)", "2K", "推断(未实测)", "5–15(逐秒)", "原生带音轨",
     "单阶段·单任务", "元/成片秒", "第三方模型费;图片>5 张 ¥0.20/张",
     "¥4.00", "¥8.00", "¥12.00", "¥0.80", "CNY", "推算(MiniMax 原厂参考价: t2v/i2v 同价)",
     MM_CN + " + " + MM_USD, "2026-09-13", "schema_verified(未实测)", UNVERIFIED_STD],
    ["minimax/hailuo-h3/multimodal-to-video(2K 档)", "标准模型 API·仅企业级-共享 Key", "CN",
     "多模态参考", "2K", "推断(未实测)", "5–15(逐秒)", "原生带音轨",
     "单阶段·单任务", "元/成片秒",
     "第三方模型费;图片>5 张 ¥0.20/张;视频输入 ¥0.80/秒",
     "¥4.00", "¥8.00", "¥12.00", "¥0.80", "CNY", "推算(MiniMax 原厂参考价)", MM_CN,
     "2026-09-13", "schema_verified(未实测)",
     UNVERIFIED_STD + ";输入视频费依输入时长"],
    ["minimax/hailuo-h3 两阶段 768P→2K(官方 regeneration 路线, 情形 C)",
     "标准模型 API·仅企业级-共享 Key", "CN",
     "先 768P 文生/图生/多模态 → regeneration-*-to-video 再生成 2K",
     "768P→2K", "源 768P + 成片 2K(实测 2560×1440 同规格)", "5–15(逐秒)",
     "原生带音轨(regen 要求源含音轨)", "多阶段·两个 taskId 独立收费, 须合并对账",
     "元/成片秒",
     "阶段1: 768P 生成 ¥0.50/秒;阶段2(regeneration): 输出 ¥0.30/秒 + 源视频输入重计 ¥0.30/秒;图片>5 张 ¥0.15/张",
     "¥5.50", "¥11.00", "¥16.50", "¥1.10", "CNY",
     "推算(MiniMax 原厂参考价;两阶段合计)", MM_CN + ";端点契约 " + "runninghub.ai api-498427804",
     "2026-09-13", "schema_verified(未实测)",
     "同规格下比直出 2K(¥0.80/s)贵 ~37%;仅在需要保留 768P 中间产物时选用"],
    ["minimax/hailuo-h3 768P → rhart-video/video-upscaler(targetResolution=2k)",
     "标准模型 API·仅企业级-共享 Key(跨模型家族组合)", "CN",
     "先 768P 生成 → 通用视频超分到 2K", "768P→2K", "未实测",
     "阶段1: 5–15;阶段2: 按输入视频", "阶段1 原生音轨;超分不生成音频",
     "多阶段·两个 taskId 独立收费", "元/成片秒",
     "阶段1: 768P ¥0.50/秒(原厂参考价);阶段2: 超分 ¥0.35/秒(官方标价)",
     "¥4.25", "¥8.50", "¥12.75", "¥0.85", "CNY",
     "推算(混合口径: 原厂参考价+官方标价快照)", KIT_SNAPSHOT + " + " + MM_CN,
     "2026-09-13", "schema_verified(组合未实测)",
     "与直出 2K 接近(¥0.85 vs ¥0.80);超分会改变画面细节, 与原生 2K 不可视为同质量"],
    ["rhart-video/sparkvideo-2.0/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频", "2k", "官方未公布像素映射(标签档)", "4–15(逐秒)",
     "generateAudio 开关;官方标价未按音轨分档(是否加价未确认)", "单阶段·单任务",
     "元/成片秒", "模型费一项",
     "¥8.10", "¥16.20", "¥24.30", "¥1.62", "CNY", "官方标价(快照)", KIT_SNAPSHOT,
     "快照 2026-04-29(09-13 引用)", "doc_verified(未实测)",
     "快照距今近 5 个月, 提交前应以 price-preview 复核;2k 实际像素未公布"],
    ["rhart-video/sparkvideo-2.0-fast/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频(快档)", "2k", "未公布", "4–15(逐秒)", "同上", "单阶段·单任务",
     "元/成片秒", "模型费一项", "¥7.10", "¥14.20", "¥21.30", "¥1.42", "CNY",
     "官方标价(快照)", KIT_SNAPSHOT, "快照 2026-04-29", "doc_verified(未实测)",
     "同上"],
    ["rhart-video/sparkvideo-2.0-mini/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频(mini 档)", "2k", "未公布", "4–15(逐秒)", "同上", "单阶段·单任务",
     "元/成片秒", "模型费一项", "¥5.10", "¥10.20", "¥15.30", "¥1.02", "CNY",
     "官方标价(快照)", KIT_SNAPSHOT, "快照 2026-04-29", "doc_verified(未实测)",
     "同上"],
    ["vidu/image-to-video-q3-pro", "标准模型 API·仅企业级-共享 Key", "CN",
     "图生视频(t2v 无 2k 档)", "2k", "未公布", "1–16(逐秒)",
     "audio 参数;标价未按音轨分档", "单阶段·单任务", "元/成片秒", "模型费一项",
     "¥5.45", "¥10.90", "¥16.35", "¥1.09", "CNY", "官方标价(快照)", KIT_SNAPSHOT,
     "快照 2026-04-29", "doc_verified(未实测)", "同上;仅 i2v 支持 2k"],
    ["bytedance/seedance-2.5-token/text-to-video 等 3 端点", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生/图生/多模态", "2k", "未公布", "4–30(逐秒)", "未确认",
     "单阶段·单任务", "未确认", "未确认", "缺口", "缺口", "缺口", "缺口", "—",
     "unlisted_gap", "2026-04 快照后新增端点, 官方定价文件无条目", "2026-09-13",
     "schema_verified", "价格缺口:需 price-preview(企业 Key)或平台页面确认"],
    ["(参照行, 非 2K) alibaba/wan-2.7/text-to-video", "标准模型 API·仅企业级-共享 Key", "CN",
     "文生视频", "1080P(最高档, 无 2K)", "未实测", "2–15(逐秒)", "audioUrl 输入",
     "单阶段·单任务", "元/成片秒", "模型费一项", "¥4.25", "¥8.50", "¥12.75",
     "¥0.85", "CNY", "官方标价(快照)", KIT_SNAPSHOT, "快照 2026-04-29",
     "doc_verified(未实测)", "参照档:wan-2.7 最高 1080P, 不冒充 2K, 不参与 2K 比较"],
]


def write_csv(name: str, rows: list[list[str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    print(f"{path}: {len(rows)} rows")


if __name__ == "__main__":
    write_csv("cost-768p.csv", rows_768p)
    write_csv("cost-2k.csv", rows_2k)
