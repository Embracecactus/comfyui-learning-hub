from __future__ import annotations

from dataclasses import dataclass


MIB = 1024 * 1024


@dataclass(frozen=True)
class MemorySnapshot:
    total_vram_mb: float
    free_vram_mb: float
    total_ram_mb: float
    available_ram_mb: float
    async_streams: int


@dataclass(frozen=True)
class H3MemoryDecision:
    chunk_tokens: int
    activation_budget_mb: float
    estimated_scratch_mb: float
    prefetch_enabled: bool
    prefetch_reason: str


PROFILE_LIMITS = {
    "auto_stable": (0.12, 4096),
    "auto_balanced": (0.22, 8192),
    "auto_speed": (0.35, 32768),
}


def _align_down(value: int, alignment: int) -> int:
    return value - value % alignment


def estimate_h3_mlp_scratch_bytes_per_token(
    hidden_size: int,
    ffn_hidden_size: int,
    element_size: int,
) -> int:
    """Conservative SwiGLU scratch estimate, independent of weight precision.

    Quantized weights reduce model residency, but H3 activations are still normally
    fp16/bf16.  fc1 emits 2*ffn rows, SwiGLU keeps roughly ffn rows, and fc2 emits
    hidden rows.  The 1.20 guard covers allocator/workspace variation.
    """

    if min(hidden_size, ffn_hidden_size, element_size) <= 0:
        raise ValueError("H3 dimensions and element size must be positive")
    elements = 3 * ffn_hidden_size + hidden_size
    return int(elements * element_size * 1.20)


def choose_h3_memory_policy(
    *,
    snapshot: MemorySnapshot,
    token_count: int,
    hidden_size: int,
    ffn_hidden_size: int,
    element_size: int,
    profile: str,
    reserve_vram_mb: int,
    min_chunk_tokens: int,
    max_chunk_tokens: int,
    manual_chunk_tokens: int,
    prefetch_mode: str,
    model_size_mb: float,
) -> H3MemoryDecision:
    if token_count <= 0:
        raise ValueError("token_count must be positive")
    if min_chunk_tokens <= 0 or max_chunk_tokens < min_chunk_tokens:
        raise ValueError("invalid adaptive chunk limits")

    bytes_per_token = estimate_h3_mlp_scratch_bytes_per_token(
        hidden_size, ffn_hidden_size, element_size
    )
    persistent_output_mb = token_count * hidden_size * element_size / MIB

    if profile == "manual":
        chunk_tokens = manual_chunk_tokens
        activation_budget_mb = chunk_tokens * bytes_per_token / MIB
    else:
        if profile not in PROFILE_LIMITS:
            raise ValueError(f"unsupported adaptive profile: {profile}")
        fraction, profile_max = PROFILE_LIMITS[profile]
        free_after_reserve = max(
            0.0,
            snapshot.free_vram_mb - reserve_vram_mb - persistent_output_mb,
        )
        activation_budget_mb = max(64.0, min(2048.0, free_after_reserve * fraction))
        raw_tokens = int(activation_budget_mb * MIB / bytes_per_token)
        chunk_tokens = _align_down(max(raw_tokens, min_chunk_tokens), 256)
        chunk_tokens = min(chunk_tokens, profile_max, max_chunk_tokens)

    chunk_tokens = max(min_chunk_tokens, min(chunk_tokens, max_chunk_tokens, token_count))
    if token_count >= 256 and chunk_tokens >= 256:
        chunk_tokens = max(256, _align_down(chunk_tokens, 256))

    estimated_scratch_mb = chunk_tokens * bytes_per_token / MIB
    prefetch_enabled, prefetch_reason = choose_prefetch(
        snapshot=snapshot,
        mode=prefetch_mode,
        reserve_vram_mb=reserve_vram_mb,
        model_size_mb=model_size_mb,
    )
    return H3MemoryDecision(
        chunk_tokens=chunk_tokens,
        activation_budget_mb=activation_budget_mb,
        estimated_scratch_mb=estimated_scratch_mb,
        prefetch_enabled=prefetch_enabled,
        prefetch_reason=prefetch_reason,
    )


def choose_prefetch(
    *,
    snapshot: MemorySnapshot,
    mode: str,
    reserve_vram_mb: int,
    model_size_mb: float,
) -> tuple[bool, str]:
    if mode == "disable":
        return False, "disabled by workflow"
    if snapshot.async_streams <= 0:
        return False, "async offload has no active stream"

    if mode == "keep":
        return True, "explicitly enabled and async offload is active"
    if mode != "auto":
        raise ValueError(f"unsupported prefetch mode: {mode}")

    vram_margin_mb = snapshot.free_vram_mb - reserve_vram_mb
    if vram_margin_mb < 768:
        return False, "less than 768 MiB VRAM remains above the reserve"

    required_ram_mb = max(2048.0, min(8192.0, model_size_mb * 0.12 + 1024.0))
    if snapshot.available_ram_mb > 0 and snapshot.available_ram_mb < required_ram_mb:
        return False, "available system RAM is too low for safe block-ahead reads"
    return True, "VRAM, RAM, and async offload allow one-block-ahead prefetch"
