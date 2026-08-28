import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageColor, ImageDraw, ImageFont

from comfy_api.latest import io

from .layout_math import compute_text_origin


FONT_EXTENSIONS = {".ttf", ".ttc", ".otf"}
PREFERRED_FONTS = (
    "NotoSansSC-VF.ttf",
    "NotoSansCJK-Regular.ttc",
    "msyh.ttc",
    "simhei.ttf",
    "Deng.ttf",
    "DejaVuSans.ttf",
)


def _font_directories():
    candidates = []
    windows_directory = os.environ.get("WINDIR")
    if windows_directory:
        candidates.append(Path(windows_directory) / "Fonts")
    candidates.extend(
        [
            Path("C:/Windows/Fonts"),
            Path("/usr/share/fonts/truetype"),
            Path("/usr/share/fonts/opentype"),
            Path.home() / ".fonts",
        ]
    )
    return candidates


def _font_index():
    fonts = {}
    for directory in _font_directories():
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS:
                fonts.setdefault(path.name, path)
    return fonts


def _font_options():
    return ["auto", *sorted(_font_index(), key=str.casefold)]


def _resolve_font(font_name):
    fonts = _font_index()
    if font_name != "auto" and font_name in fonts:
        return fonts[font_name]
    for preferred in PREFERRED_FONTS:
        if preferred in fonts:
            return fonts[preferred]
    if fonts:
        return fonts[sorted(fonts, key=str.casefold)[0]]
    raise ValueError(
        "No TrueType/OpenType font was found. Install Noto Sans SC or choose a valid system font."
    )


def _wrap_line(draw, line, font, max_width, stroke_width):
    if not line:
        return [""]

    chunks = []
    current = ""
    for character in line:
        candidate = current + character
        bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=stroke_width)
        if current and bbox[2] - bbox[0] > max_width:
            chunks.append(current.rstrip())
            current = character.lstrip()
        else:
            current = candidate
    chunks.append(current)
    return chunks


def _wrap_text(draw, text, font, max_width, stroke_width):
    lines = []
    for raw_line in text.split("\n"):
        lines.extend(_wrap_line(draw, raw_line, font, max_width, stroke_width))
    return "\n".join(lines)


class ProductTextOverlay(io.ComfyNode):
    """Place crisp editable text by canvas-relative coordinates and a system font."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ProductTextOverlay",
            display_name="Product Text Overlay",
            category="image/ecommerce",
            description=(
                "Draw deterministic brand or selling-point text after final image resizing. "
                "Position and font size use canvas percentages."
            ),
            inputs=[
                io.Image.Input("images"),
                io.String.Input("text", multiline=True, default="填写真实卖点\\n第二行卖点"),
                io.Combo.Input("font_name", options=_font_options(), default="auto"),
                io.Float.Input("font_size_percent", default=2.4, min=0.2, max=30.0, step=0.1),
                io.Float.Input("x_percent", default=7.5, min=0.0, max=100.0, step=0.1),
                io.Float.Input("y_percent", default=7.0, min=0.0, max=100.0, step=0.1),
                io.Combo.Input(
                    "anchor",
                    options=[
                        "top_left",
                        "top_center",
                        "top_right",
                        "center_left",
                        "center_center",
                        "center_right",
                        "bottom_left",
                        "bottom_center",
                        "bottom_right",
                    ],
                    default="top_left",
                ),
                io.Combo.Input("align", options=["left", "center", "right"], default="left"),
                io.Color.Input("color", default="#111111"),
                io.Float.Input("max_width_percent", default=85.0, min=1.0, max=100.0, step=0.5),
                io.Float.Input("line_spacing_percent", default=25.0, min=0.0, max=200.0, step=5.0),
                io.Float.Input("stroke_width_percent", default=0.0, min=0.0, max=30.0, step=0.5),
                io.Color.Input("stroke_color", default="#FFFFFF"),
                io.Combo.Input("keep_inside", options=["yes", "no"], default="yes"),
            ],
            outputs=[io.Image.Output("images")],
        )

    @classmethod
    def execute(
        cls,
        images,
        text,
        font_name,
        font_size_percent,
        x_percent,
        y_percent,
        anchor,
        align,
        color,
        max_width_percent,
        line_spacing_percent,
        stroke_width_percent,
        stroke_color,
        keep_inside,
    ):
        if images.ndim != 4 or images.shape[-1] < 3:
            raise ValueError("images must be a ComfyUI IMAGE tensor with at least three channels")
        text = text.replace("\\n", "\n").replace("\\t", "\t")
        if not text.strip():
            return io.NodeOutput(images)

        height, width = images.shape[1:3]
        font_pixels = max(1, round(height * font_size_percent / 100.0))
        stroke_pixels = max(0, round(font_pixels * stroke_width_percent / 100.0))
        spacing_pixels = max(0, round(font_pixels * line_spacing_percent / 100.0))
        font = ImageFont.truetype(str(_resolve_font(font_name)), font_pixels)

        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        wrapped = _wrap_text(
            draw,
            text,
            font,
            max(1, round(width * max_width_percent / 100.0)),
            stroke_pixels,
        )
        bbox = draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            align=align,
            spacing=spacing_pixels,
            stroke_width=stroke_pixels,
        )
        origin = compute_text_origin(
            width,
            height,
            bbox,
            x_percent,
            y_percent,
            anchor,
            keep_inside == "yes",
        )
        draw.multiline_text(
            origin,
            wrapped,
            font=font,
            fill=ImageColor.getrgb(color),
            align=align,
            spacing=spacing_pixels,
            stroke_width=stroke_pixels,
            stroke_fill=ImageColor.getrgb(stroke_color),
        )

        overlay = np.asarray(layer, dtype=np.float32) / 255.0
        overlay_rgb = torch.from_numpy(overlay[:, :, :3]).to(images.device, images.dtype)
        overlay_alpha = torch.from_numpy(overlay[:, :, 3:4]).to(images.device, images.dtype)
        result = images[..., :3] * (1.0 - overlay_alpha) + overlay_rgb * overlay_alpha
        if images.shape[-1] > 3:
            result = torch.cat((result, images[..., 3:]), dim=-1)
        return io.NodeOutput(result)
