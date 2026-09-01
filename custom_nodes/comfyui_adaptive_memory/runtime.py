from __future__ import annotations

import ctypes
import logging
import os
import platform
from dataclasses import dataclass
from typing import Callable

import torch

from .adaptive_policy import (
    H3MemoryDecision,
    MemorySnapshot,
    choose_h3_memory_policy,
    choose_prefetch,
)


def read_system_memory_mb() -> tuple[float, float]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return memory.total / (1024 * 1024), memory.available / (1024 * 1024)
    except Exception:
        pass

    if platform.system() == "Windows":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 * 1024), status.ullAvailPhys / (1024 * 1024)

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        available = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / (1024 * 1024), available * page_size / (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return 0.0, 0.0


def capture_memory_snapshot(device: torch.device, async_streams: int) -> MemorySnapshot:
    total_ram_mb, available_ram_mb = read_system_memory_mb()
    total_vram_mb = free_vram_mb = 0.0
    if device.type == "cuda":
        free_bytes, total_bytes = torch.cuda.mem_get_info(device)
        total_vram_mb = total_bytes / (1024 * 1024)
        free_vram_mb = free_bytes / (1024 * 1024)
    return MemorySnapshot(
        total_vram_mb=total_vram_mb,
        free_vram_mb=free_vram_mb,
        total_ram_mb=total_ram_mb,
        available_ram_mb=available_ram_mb,
        async_streams=async_streams,
    )


@dataclass
class AdaptiveH3Settings:
    profile: str
    reserve_vram_mb: int
    min_chunk_tokens: int
    max_chunk_tokens: int
    manual_chunk_tokens: int
    prefetch_mode: str
    hidden_size: int
    ffn_hidden_size: int
    model_size_mb: float
    verbose: bool


class AdaptiveH3RuntimeState:
    def __init__(self, settings: AdaptiveH3Settings):
        self.settings = settings
        self.snapshot: MemorySnapshot | None = None
        self.decision: H3MemoryDecision | None = None
        self.forward_index = 0
        self._last_logged_signature = None

    def begin_forward(self, device: torch.device, async_streams: int) -> None:
        self.forward_index += 1
        self.snapshot = capture_memory_snapshot(device, async_streams)
        self.decision = None

    def resolve(self, x: torch.Tensor) -> H3MemoryDecision:
        if self.decision is not None:
            return self.decision
        if x.ndim < 2 or x.shape[-1] != self.settings.hidden_size:
            raise ValueError(
                "MiniMax H3 adaptive MLP expected [..., tokens, hidden] with "
                f"hidden={self.settings.hidden_size}, got {tuple(x.shape)}"
            )
        if self.snapshot is None:
            self.begin_forward(x.device, async_streams=0)
        token_count = x.numel() // x.shape[-1]
        self.decision = choose_h3_memory_policy(
            snapshot=self.snapshot,
            token_count=token_count,
            hidden_size=self.settings.hidden_size,
            ffn_hidden_size=self.settings.ffn_hidden_size,
            element_size=x.element_size(),
            profile=self.settings.profile,
            reserve_vram_mb=self.settings.reserve_vram_mb,
            min_chunk_tokens=self.settings.min_chunk_tokens,
            max_chunk_tokens=self.settings.max_chunk_tokens,
            manual_chunk_tokens=self.settings.manual_chunk_tokens,
            prefetch_mode=self.settings.prefetch_mode,
            model_size_mb=self.settings.model_size_mb,
        )
        signature = (
            self.decision.chunk_tokens,
            self.decision.prefetch_enabled,
            self.decision.prefetch_reason,
        )
        if self.settings.verbose and signature != self._last_logged_signature:
            logging.info(
                "Adaptive H3 memory: chunk=%d tokens, scratch~%.0f MiB, "
                "free VRAM=%.0f MiB, available RAM=%.0f MiB, prefetch=%s (%s)",
                self.decision.chunk_tokens,
                self.decision.estimated_scratch_mb,
                self.snapshot.free_vram_mb,
                self.snapshot.available_ram_mb,
                "on" if self.decision.prefetch_enabled else "off",
                self.decision.prefetch_reason,
            )
            self._last_logged_signature = signature
        return self.decision

    def resolve_prefetch(self) -> tuple[bool, str]:
        if self.snapshot is None:
            return False, "runtime snapshot is not available"
        return choose_prefetch(
            snapshot=self.snapshot,
            mode=self.settings.prefetch_mode,
            reserve_vram_mb=self.settings.reserve_vram_mb,
            model_size_mb=self.settings.model_size_mb,
        )


class AdaptiveH3MLPForward:
    """Numerically equivalent H3 MLP execution with a runtime-sized token window."""

    def __init__(
        self,
        original_forward: Callable[[torch.Tensor], torch.Tensor],
        state: AdaptiveH3RuntimeState,
    ):
        self.original_forward = original_forward
        self.state = state

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        chunk_tokens = self.state.resolve(x).chunk_tokens
        hidden_size = x.shape[-1]
        token_count = x.numel() // hidden_size
        if token_count <= chunk_tokens:
            return self.original_forward(x)

        flat_x = x.reshape(token_count, hidden_size)
        flat_output = torch.empty_like(flat_x)
        for start in range(0, token_count, chunk_tokens):
            end = min(start + chunk_tokens, token_count)
            chunk_output = self.original_forward(flat_x[start:end])
            flat_output[start:end].copy_(chunk_output)
            del chunk_output
        return flat_output.reshape(x.shape)
