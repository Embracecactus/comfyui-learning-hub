#!/usr/bin/env python3
"""Generate the built-in ComfyUI node reference used by this documentation.

Run from the repository root:
    python docs/01-新手入门/ComfyUI-系统学习手册/tools/generate_node_reference.py

Or point to a ComfyUI checkout elsewhere:
    python docs/01-新手入门/ComfyUI-系统学习手册/tools/generate_node_reference.py \
        --comfy-root /path/to/ComfyUI

The script intentionally excludes custom_nodes and cloud/API nodes. It loads the
checked-in ComfyUI source in CPU mode and records the metadata exposed by every
successfully registered core/extra node.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_COMFY_ROOT = REPO_ROOT / "ComfyUI"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "01-新手入门" / "ComfyUI-系统学习手册" / "节点手册" / "03-全部内置节点索引.md"
COMFY_ROOT = DEFAULT_COMFY_ROOT
OUTPUT = DEFAULT_OUTPUT


CATEGORY_TIPS = {
    "3d": "处理 3D、网格、点云或 splat 数据；使用前核对坐标系、单位、材质和导出格式。",
    "audio": "处理音频；重点核对采样率、声道、时长和批次，长音频会明显增加内存。",
    "experimental": "实验节点，接口和结果可能随版本变化；请保留可回退的工作流。",
    "image/mask": "处理遮罩；接入主工作流前先预览黑白方向、边缘和尺寸。",
    "image": "处理像素图像；重点核对宽高、批次、颜色通道和 alpha。",
    "model/conditioning": "构造或修改生成条件；注意正向/负向语义、生效区间和模型兼容性。",
    "model/latent": "处理潜空间数据；LATENT 不是可见图片，需要匹配 VAE 解码。",
    "model/loaders": "加载模型组件；先核对文件目录、模型架构、精度和配套组件。",
    "model/merging": "合并或保存模型权重；可能消耗大量内存和磁盘，并需遵守模型许可。",
    "model/patch": "修改 MODEL 的推理行为；优先跟随对应模型模板，不要无目的叠加。",
    "model/sampling": "参与噪声调度、引导或采样；固定 seed 后一次只改一个参数。",
    "model/training": "训练或构建数据集；运行前确认数据、输出目录、磁盘空间和训练配置。",
    "text": "处理文本或结构化提示词；注意空格、大小写、正则表达式和输出格式。",
    "utilities": "提供数字、逻辑、列表或通用辅助数据，常用于参数化工作流。",
    "video": "处理视频；重点核对帧率、帧数、尺寸、时长和模型的时序限制。",
}


ACTION_HINTS = (
    (r"^(Load|加载)", "加载对应资源并把它交给下游节点"),
    (r"^(Save|保存)", "把输入结果写入输出目录或指定文件"),
    (r"^(Preview|预览)", "在界面中预览输入结果，通常不作为最终落盘步骤"),
    (r"^(Empty|Create Solid|创建)", "创建一个新的空白或初始数据对象"),
    (r"(Text Encode|TextEncode|Encode)", "把输入编码成模型或下游节点需要的表示"),
    (r"(Decode)", "把编码数据解码成更接近最终媒体的表示"),
    (r"^(Upscale|Scale|Resize)", "调整输入尺寸或执行放大"),
    (r"^(Crop|Trim)", "裁剪输入的空间范围或时间范围"),
    (r"^(Blend|Composite|Join|Concatenate|Stitch)", "组合多个输入"),
    (r"^(Split|Separate|Get .* from Batch)", "从输入中拆分或提取部分数据"),
    (r"^(Merge|Batch|Rebatch|Repeat)", "合并、重组或复制批次数据"),
    (r"^(Apply|Set|ModelSampling|Patch)", "把指定配置、条件或补丁应用到输入"),
    (r"^(Detect|Run .*Detection|Extract)", "检测或提取输入中的结构化信息"),
    (r"^(Draw|Render|Visualize)", "把数据绘制或渲染为可观察结果"),
    (r"(Sampler|Sampling)", "配置或执行扩散采样过程"),
    (r"Scheduler$", "生成或调整采样使用的噪声时间表"),
    (r"^(Invert|Flip|Rotate)", "对输入执行反相、翻转或旋转变换"),
)


def md(value: Any) -> str:
    """Escape a compact value for Markdown text/table cells."""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def type_name(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "COMBO"
    raw = getattr(value, "value", value)
    return md(raw)


def compact_value(value: Any, limit: int = 80) -> str:
    if isinstance(value, str):
        rendered = repr(value)
    else:
        rendered = repr(value)
    rendered = rendered.replace("\n", " ")
    if len(rendered) > limit:
        rendered = rendered[: limit - 1] + "…"
    return md(rendered)


def options_summary(options: list[Any] | tuple[Any, ...]) -> str:
    if not options:
        return "选项由当前环境动态提供"
    shown = [compact_value(item, 32) for item in options[:10]]
    suffix = f"，另有 {len(options) - 10} 项" if len(options) > 10 else ""
    return "选项：" + "、".join(shown) + suffix


def parse_input(name: str, spec: Any) -> tuple[str, str]:
    if isinstance(spec, str) or hasattr(spec, "value"):
        return type_name(spec), "由 ComfyUI 运行时提供"
    if not isinstance(spec, (tuple, list)) or not spec:
        return "UNKNOWN", compact_value(spec)
    dtype = type_name(spec[0])
    notes: list[str] = []
    if isinstance(spec[0], (list, tuple)):
        notes.append(options_summary(spec[0]))
    config = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    for key, label in (("default", "默认"), ("min", "最小"), ("max", "最大"), ("step", "步长")):
        if key in config:
            notes.append(f"{label} {compact_value(config[key])}")
    if config.get("multiline"):
        notes.append("多行文本")
    tooltip = config.get("tooltip")
    if tooltip:
        notes.append("源码提示：" + md(tooltip))
    return dtype, "；".join(notes) if notes else "—"


def return_metadata(cls: Any) -> list[tuple[str, str]]:
    return_types = list(getattr(cls, "RETURN_TYPES", ()) or ())
    return_names = list(getattr(cls, "RETURN_NAMES", ()) or ())
    result = []
    for index, output_type in enumerate(return_types):
        name = return_names[index] if index < len(return_names) else getattr(output_type, "value", output_type)
        result.append((md(name), type_name(output_type)))
    return result


def category_tip(category: str) -> str:
    for prefix, tip in CATEGORY_TIPS.items():
        if category == prefix or category.startswith(prefix + "/"):
            return tip
    return "先根据输入、输出和官方模板确认作用；模型专用节点不要脱离对应工作流单独套用。"


def action_hint(display_name: str) -> str:
    for pattern, hint in ACTION_HINTS:
        if re.search(pattern, display_name, flags=re.IGNORECASE):
            return hint + f"；具体对象见节点名 `{md(display_name)}`。"
    return f"执行 `{md(display_name)}` 对应的专用处理；以下输入输出来自当前源码定义。"


def source_name(cls: Any) -> str:
    module = str(getattr(cls, "__module__", "unknown"))
    # Extra nodes are loaded from a path-derived module name. Keep generated
    # documentation portable instead of leaking the generator machine's path.
    comfy_prefix = str(COMFY_ROOT) + "/"
    if module.startswith(comfy_prefix):
        module = module[len(comfy_prefix) :].replace("/", ".")
    return md(module)


def generate() -> None:
    if not (COMFY_ROOT / "nodes.py").is_file():
        raise SystemExit(
            f"找不到 ComfyUI 源码：{COMFY_ROOT}\n"
            "请把 ComfyUI 克隆到仓库根目录的 ComfyUI/，或使用 --comfy-root 指定源码目录。"
        )
    sys.path.insert(0, str(COMFY_ROOT))
    # ComfyUI normally enables CLI parsing in main.py. Reproduce only CPU mode
    # here so importing node metadata never tries to initialize CUDA.
    import comfy.options

    comfy.options.enable_args_parsing()
    sys.argv = [sys.argv[0], "--cpu"]
    logging.getLogger().setLevel(logging.ERROR)

    import nodes
    from comfyui_version import __version__

    failed = asyncio.run(nodes.init_extra_nodes(init_custom_nodes=False, init_api_nodes=False))

    grouped: dict[str, list[tuple[str, str, Any]]] = defaultdict(list)
    for class_name, cls in nodes.NODE_CLASS_MAPPINGS.items():
        category = str(getattr(cls, "CATEGORY", "未分类") or "未分类")
        display_name = nodes.NODE_DISPLAY_NAME_MAPPINGS.get(class_name, class_name)
        grouped[category].append((str(display_name), class_name, cls))

    failed_summary = ", ".join(failed) if failed else "无"
    if failed == ["nodes_replacements.py"]:
        failed_summary += "（无服务端的导出环境未注册旧节点迁移规则；该模块不声明新节点，不影响节点数量）"

    lines = [
        "# 全部内置节点索引",
        "",
        f"> 自动生成于 ComfyUI `{__version__}` 本地源码；共记录 **{len(nodes.NODE_CLASS_MAPPINGS)}** 个成功注册的非 API 内置节点。",
        "> 不包含 `custom_nodes/` 第三方节点和 `comfy_api_nodes/` 云端/API 节点。节点随版本、可选依赖和硬件变化。",
        "",
        "## 如何使用",
        "",
        "- 浏览器或编辑器中按 `Ctrl/Cmd + F` 搜索节点英文显示名或内部类名。",
        "- `required` 必须提供；`optional` 可不接；`hidden` 由运行时提供。",
        "- `COMBO` 是下拉选择；模型文件类选项会根据本机目录动态变化。",
        "- 源码说明保留英文原文，避免自动翻译扭曲模型专用语义；中文用途提示用于快速判断类别。",
        "- 高频节点的中文接线和参数解释见 [基础核心节点逐项详解](01-基础核心节点逐项详解.md)。",
        "",
        "## 生成范围",
        "",
        f"- 成功载入：`{len(nodes.NODE_CLASS_MAPPINGS)}` 个节点。",
        f"- 未完整初始化的 extra 模块：{failed_summary}。",
        "- 前端专用的 Reroute、Note、Group 等不在 Python 注册表内，见 [如何读懂任何节点](00-如何读懂任何节点.md)。",
        "",
        "## 分类目录",
        "",
    ]

    for category in sorted(grouped, key=str.casefold):
        anchor = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", category).strip("-").lower()
        lines.append(f"- [{md(category)}（{len(grouped[category])}）](#{anchor})")

    for category in sorted(grouped, key=str.casefold):
        items = sorted(grouped[category], key=lambda item: (item[0].casefold(), item[1].casefold()))
        anchor = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", category).strip("-").lower()
        lines.extend(["", f'<a id="{anchor}"></a>', "", f"## {md(category)}", "", category_tip(category), ""])
        for display_name, class_name, cls in items:
            flags = []
            if getattr(cls, "DEPRECATED", False):
                flags.append("已弃用")
            if getattr(cls, "EXPERIMENTAL", False):
                flags.append("实验性")
            if getattr(cls, "OUTPUT_NODE", False):
                flags.append("输出节点")
            flag_text = "；".join(flags) if flags else "普通节点"
            lines.extend(
                [
                    f"### {md(display_name)}",
                    "",
                    f"- **内部类名**：`{md(class_name)}`",
                    f"- **源码模块**：`{source_name(cls)}`",
                    f"- **标记**：{flag_text}",
                    f"- **用途提示**：{action_hint(display_name)}",
                ]
            )
            description = getattr(cls, "DESCRIPTION", None)
            if description:
                lines.append(f"- **源码说明（原文）**：{md(description)}")
            lines.extend(["", "| 输入 | 类型 | 必需性 | 默认值/范围/说明 |", "|---|---|---|---|"])
            try:
                input_groups = cls.INPUT_TYPES() or {}
            except Exception as exc:  # pragma: no cover - environment-dependent metadata
                input_groups = {}
                lines.append(f"| — | — | — | 读取元数据失败：{md(exc)} |")
            wrote_input = False
            for group in ("required", "optional", "hidden"):
                for input_name, spec in (input_groups.get(group, {}) or {}).items():
                    wrote_input = True
                    dtype, notes = parse_input(input_name, spec)
                    lines.append(f"| `{md(input_name)}` | `{dtype}` | {group} | {notes} |")
            if not wrote_input:
                lines.append("| — | — | — | 无公开输入 |")

            outputs = return_metadata(cls)
            lines.extend(["", "| 输出 | 类型 |", "|---|---|"])
            if outputs:
                for output_name, output_type in outputs:
                    lines.append(f"| `{output_name}` | `{output_type}` |")
            else:
                lines.append("| — | 无公开输出 |")
            lines.extend(["", f"**小白提醒**：{category_tip(category)}", ""])

    lines.extend(
        [
            "---",
            "",
            "## 更新本索引",
            "",
            "在仓库根目录执行：",
            "",
            "```bash",
            "python docs/01-新手入门/ComfyUI-系统学习手册/tools/generate_node_reference.py",
            "```",
            "",
            "生成器只读取 ComfyUI 源码的节点元数据，并覆盖本文件。默认查找仓库根目录下被 Git 忽略的 `ComfyUI/`；也可用 `--comfy-root /path/to/ComfyUI` 指定其他源码目录。",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} with {len(nodes.NODE_CLASS_MAPPINGS)} nodes")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 ComfyUI 非 API 内置节点 Markdown 索引")
    parser.add_argument(
        "--comfy-root",
        type=Path,
        default=DEFAULT_COMFY_ROOT,
        help="ComfyUI 源码目录，默认使用仓库根目录下的 ComfyUI/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="索引输出文件路径",
    )
    args = parser.parse_args()

    global COMFY_ROOT, OUTPUT
    COMFY_ROOT = args.comfy_root.expanduser().resolve()
    OUTPUT = args.output.expanduser().resolve()
    generate()


if __name__ == "__main__":
    main()
