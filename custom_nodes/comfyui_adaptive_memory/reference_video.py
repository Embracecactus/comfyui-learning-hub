"""Temporal preprocessing helpers for MiniMax H3 reference videos."""

import math


DEFAULT_TARGET_FPS = 24.0
DEFAULT_MAX_SECONDS = 5.2
MAX_SECONDS = 15.0


def h3_reference_frame_indices(
    frame_count: int,
    source_fps: float,
    target_fps: float = DEFAULT_TARGET_FPS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> tuple[int, ...]:
    """Return nearest-neighbor source-frame indices in H3's temporal layout.

    The returned count is rounded down to ``n % 17 == 5`` and never falls
    below five.  ``max_seconds`` is bounded by the node's 15-second safety
    limit; invalid frame and rate values are rejected explicitly.
    """
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 1:
        raise ValueError("frame_count must be a positive integer")
    for name, value in (("source_fps", source_fps), ("target_fps", target_fps), ("max_seconds", max_seconds)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    if source_fps <= 0:
        raise ValueError("source_fps must be greater than zero")
    if target_fps <= 0:
        raise ValueError("target_fps must be greater than zero")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be greater than zero")

    duration = min(frame_count / source_fps, min(max_seconds, MAX_SECONDS))
    requested_count = math.floor(duration * target_fps)
    output_count = max(5, requested_count)
    if output_count > 5:
        output_count -= (output_count - 5) % 17

    # Sample at target-rate timestamps and round to the nearest source frame.
    # Clipping also makes the minimum-five-frame rule safe for very short clips.
    return tuple(
        min(frame_count - 1, math.floor(index * source_fps / target_fps + 0.5))
        for index in range(output_count)
    )
