import torch
from typing_extensions import override

import comfy.utils
from comfy_api.latest import ComfyExtension, io

from .layout_math import compute_layout, expand_bbox


def _parse_hex_color(value):
    color = value.strip().lstrip("#")
    if len(color) != 6 or any(character not in "0123456789abcdefABCDEF" for character in color):
        raise ValueError("background_color must use #RRGGBB, for example #FFFFFF")
    packed = int(color, 16)
    return ((packed >> 16) & 255, (packed >> 8) & 255, packed & 255)


def _resize(tensor, width, height, method):
    return comfy.utils.common_upscale(tensor, width, height, method, "disabled")


class ProductLayoutByMask(io.ComfyNode):
    """Crop a foreground by its mask, scale it by canvas ratios, and composite it."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ProductLayoutByMask",
            display_name="Product Layout by Mask",
            category="image/ecommerce",
            description=(
                "Automatically crops the product from its foreground mask, fits it into a "
                "relative safe area, and composites it on a solid canvas."
            ),
            inputs=[
                io.Image.Input("image", tooltip="Original product RGB image."),
                io.Mask.Input("mask", tooltip="White foreground mask, normally from BiRefNet."),
                io.Int.Input("canvas_width", default=576, min=64, max=16384, step=8),
                io.Int.Input("canvas_height", default=1024, min=64, max=16384, step=8),
                io.Float.Input("max_width_percent", default=88.0, min=1.0, max=100.0, step=0.5),
                io.Float.Input("max_height_percent", default=65.0, min=1.0, max=100.0, step=0.5),
                io.Float.Input("center_x_percent", default=50.0, min=1.0, max=100.0, step=0.5),
                io.Float.Input("center_y_percent", default=43.5, min=1.0, max=100.0, step=0.5),
                io.Float.Input("mask_threshold", default=0.1, min=0.0, max=1.0, step=0.01),
                io.Float.Input("crop_padding_percent", default=1.0, min=0.0, max=50.0, step=0.5),
                io.String.Input("background_color", default="#FFFFFF"),
                io.Combo.Input(
                    "interpolation",
                    options=["lanczos", "bicubic", "bilinear", "area", "nearest-exact"],
                ),
                io.Combo.Input("allow_upscale", options=["yes", "no"]),
            ],
            outputs=[
                io.Image.Output("image", display_name="composited image"),
                io.Mask.Output("mask", display_name="positioned mask"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image,
        mask,
        canvas_width,
        canvas_height,
        max_width_percent,
        max_height_percent,
        center_x_percent,
        center_y_percent,
        mask_threshold,
        crop_padding_percent,
        background_color,
        interpolation,
        allow_upscale,
    ):
        if image.ndim != 4 or image.shape[-1] < 3:
            raise ValueError("image must be a ComfyUI IMAGE tensor with at least three channels")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        elif mask.ndim == 4 and mask.shape[-1] == 1:
            mask = mask[..., 0]
        if mask.ndim != 3:
            raise ValueError("mask must be a ComfyUI MASK tensor")
        if mask.shape[0] not in (1, image.shape[0]):
            raise ValueError("mask batch must be 1 or match the image batch")

        background_rgb = _parse_hex_color(background_color)
        background = torch.tensor(
            background_rgb,
            dtype=image.dtype,
            device=image.device,
        ).div(255.0)

        output_images = []
        output_masks = []
        for batch_index in range(image.shape[0]):
            source = image[batch_index : batch_index + 1, :, :, :3]
            source_mask = mask[0 if mask.shape[0] == 1 else batch_index].to(device=image.device)

            if source_mask.shape != source.shape[1:3]:
                source_mask = _resize(
                    source_mask.unsqueeze(0).unsqueeze(0),
                    source.shape[2],
                    source.shape[1],
                    "bilinear",
                )[0, 0]

            foreground = torch.nonzero(source_mask > mask_threshold, as_tuple=False)
            if foreground.numel() == 0:
                raise ValueError(
                    f"mask batch {batch_index} has no foreground above threshold {mask_threshold}"
                )

            y0 = int(foreground[:, 0].min().item())
            y1 = int(foreground[:, 0].max().item())
            x0 = int(foreground[:, 1].min().item())
            x1 = int(foreground[:, 1].max().item())
            x0, y0, x1, y1 = expand_bbox(
                x0,
                y0,
                x1,
                y1,
                source.shape[2],
                source.shape[1],
                crop_padding_percent,
            )

            cropped_image = source[:, y0 : y1 + 1, x0 : x1 + 1, :]
            cropped_mask = source_mask[y0 : y1 + 1, x0 : x1 + 1]
            x, y, width, height = compute_layout(
                cropped_image.shape[2],
                cropped_image.shape[1],
                canvas_width,
                canvas_height,
                max_width_percent,
                max_height_percent,
                center_x_percent,
                center_y_percent,
                allow_upscale == "yes",
            )

            resized_image = _resize(
                cropped_image.movedim(-1, 1),
                width,
                height,
                interpolation,
            ).movedim(1, -1).clamp(0.0, 1.0)
            resized_mask = _resize(
                cropped_mask.unsqueeze(0).unsqueeze(0),
                width,
                height,
                "bilinear",
            )[0, 0].clamp(0.0, 1.0)

            canvas = background.view(1, 1, 1, 3).expand(
                1,
                canvas_height,
                canvas_width,
                3,
            ).clone()
            canvas_mask = torch.zeros(
                (1, canvas_height, canvas_width),
                dtype=source_mask.dtype,
                device=image.device,
            )
            alpha = resized_mask.view(1, height, width, 1).to(dtype=image.dtype)
            destination = canvas[:, y : y + height, x : x + width, :]
            canvas[:, y : y + height, x : x + width, :] = (
                resized_image * alpha + destination * (1.0 - alpha)
            )
            canvas_mask[:, y : y + height, x : x + width] = resized_mask
            output_images.append(canvas)
            output_masks.append(canvas_mask)

        return io.NodeOutput(torch.cat(output_images, dim=0), torch.cat(output_masks, dim=0))


class ProductLayoutExtension(ComfyExtension):
    @override
    async def get_node_list(self):
        return [ProductLayoutByMask]


async def comfy_entrypoint():
    return ProductLayoutExtension()
