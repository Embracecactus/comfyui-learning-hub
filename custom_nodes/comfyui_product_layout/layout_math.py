def expand_bbox(x0, y0, x1, y1, image_width, image_height, padding_percent):
    """Expand an inclusive foreground bounding box without leaving the image."""
    if x1 < x0 or y1 < y0:
        raise ValueError("foreground bounding box is empty")
    if image_width < 1 or image_height < 1:
        raise ValueError("image dimensions must be positive")
    if padding_percent < 0:
        raise ValueError("padding_percent must be non-negative")

    foreground_width = x1 - x0 + 1
    foreground_height = y1 - y0 + 1
    padding = round(max(foreground_width, foreground_height) * padding_percent / 100.0)
    return (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(image_width - 1, x1 + padding),
        min(image_height - 1, y1 + padding),
    )


def compute_layout(
    crop_width,
    crop_height,
    canvas_width,
    canvas_height,
    max_width_percent,
    max_height_percent,
    center_x_percent,
    center_y_percent,
    allow_upscale=True,
):
    """Fit a cropped foreground into a relative safe area and return x, y, w, h."""
    for name, value in (
        ("crop_width", crop_width),
        ("crop_height", crop_height),
        ("canvas_width", canvas_width),
        ("canvas_height", canvas_height),
    ):
        if value < 1:
            raise ValueError(f"{name} must be positive")

    for name, value in (
        ("max_width_percent", max_width_percent),
        ("max_height_percent", max_height_percent),
        ("center_x_percent", center_x_percent),
        ("center_y_percent", center_y_percent),
    ):
        if not 0 < value <= 100:
            raise ValueError(f"{name} must be in (0, 100]")

    max_width = max(1, round(canvas_width * max_width_percent / 100.0))
    max_height = max(1, round(canvas_height * max_height_percent / 100.0))
    scale = min(max_width / crop_width, max_height / crop_height)
    if not allow_upscale:
        scale = min(scale, 1.0)

    width = max(1, min(canvas_width, round(crop_width * scale)))
    height = max(1, min(canvas_height, round(crop_height * scale)))
    center_x = canvas_width * center_x_percent / 100.0
    center_y = canvas_height * center_y_percent / 100.0
    x = round(center_x - width / 2.0)
    y = round(center_y - height / 2.0)
    x = min(max(0, x), canvas_width - width)
    y = min(max(0, y), canvas_height - height)
    return x, y, width, height


def compute_text_origin(
    canvas_width,
    canvas_height,
    text_bbox,
    x_percent,
    y_percent,
    anchor,
    keep_inside=True,
):
    """Return the PIL draw origin for a text bounding box and percentage anchor."""
    if canvas_width < 1 or canvas_height < 1:
        raise ValueError("canvas dimensions must be positive")
    if not 0 <= x_percent <= 100 or not 0 <= y_percent <= 100:
        raise ValueError("text x/y percentages must be in [0, 100]")

    try:
        vertical, horizontal = anchor.split("_", 1)
    except ValueError as error:
        raise ValueError(f"unsupported text anchor: {anchor}") from error
    if vertical not in {"top", "center", "bottom"} or horizontal not in {
        "left",
        "center",
        "right",
    }:
        raise ValueError(f"unsupported text anchor: {anchor}")

    bbox_left, bbox_top, bbox_right, bbox_bottom = text_bbox
    block_width = bbox_right - bbox_left
    block_height = bbox_bottom - bbox_top
    if block_width < 0 or block_height < 0:
        raise ValueError("text bounding box is invalid")

    target_x = canvas_width * x_percent / 100.0
    target_y = canvas_height * y_percent / 100.0
    desired_left = {
        "left": target_x,
        "center": target_x - block_width / 2.0,
        "right": target_x - block_width,
    }[horizontal]
    desired_top = {
        "top": target_y,
        "center": target_y - block_height / 2.0,
        "bottom": target_y - block_height,
    }[vertical]

    if keep_inside:
        desired_left = min(max(0.0, desired_left), max(0.0, canvas_width - block_width))
        desired_top = min(max(0.0, desired_top), max(0.0, canvas_height - block_height))

    return round(desired_left - bbox_left), round(desired_top - bbox_top)
