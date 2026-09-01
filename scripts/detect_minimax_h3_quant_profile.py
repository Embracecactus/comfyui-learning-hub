#!/usr/bin/env python3
"""Recommend a conservative MiniMax H3 quantized low-memory profile."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
from typing import Any


def memory_tier(vram_gib: float) -> dict[str, Any]:
    if vram_gib <= 8.5:
        return {
            "tier": "8GB",
            "adaptive_profile": "auto_stable",
            "reserve_vram_mb": 1024,
            "min_chunk_tokens": 1024,
            "max_chunk_tokens": 4096,
            "prefetch_mode": "auto",
            "megapixels": 0.1,
        }
    if vram_gib <= 12.5:
        return {
            "tier": "12GB",
            "adaptive_profile": "auto_balanced",
            "reserve_vram_mb": 1024,
            "min_chunk_tokens": 1024,
            "max_chunk_tokens": 8192,
            "prefetch_mode": "auto",
            "megapixels": 0.2,
        }
    if vram_gib <= 16.5:
        return {
            "tier": "16GB",
            "adaptive_profile": "auto_balanced",
            "reserve_vram_mb": 1280,
            "min_chunk_tokens": 2048,
            "max_chunk_tokens": 8192,
            "prefetch_mode": "auto",
            "megapixels": 0.4,
        }
    if vram_gib <= 24.5:
        return {
            "tier": "24GB",
            "adaptive_profile": "auto_speed",
            "reserve_vram_mb": 1536,
            "min_chunk_tokens": 2048,
            "max_chunk_tokens": 16384,
            "prefetch_mode": "auto",
            "megapixels": 0.6,
        }
    return {
        "tier": ">24GB",
        "adaptive_profile": "auto_speed",
        "reserve_vram_mb": 2048,
        "min_chunk_tokens": 4096,
        "max_chunk_tokens": 32768,
        "prefetch_mode": "auto",
        "megapixels": 0.98,
    }


def recommend_profile(
    *,
    backend: str,
    vram_gib: float,
    compute_major: int | None = None,
    compute_minor: int | None = None,
    cuda_major: int | None = None,
    amd_arch: str = "",
    system_ram_gib: float | None = None,
    available_ram_gib: float | None = None,
    native_backend_ready: bool | None = None,
    native_capabilities: set[str] | None = None,
    available_capabilities: set[str] | None = None,
) -> dict[str, Any]:
    recommendation: dict[str, Any] = {
        "backend": backend,
        "vram_gib": round(vram_gib, 2),
        **memory_tier(vram_gib),
        "supported": False,
        "workflow_profile": None,
        "text_encoder": None,
        "warnings": [],
        "stage_release": True,
    }

    if backend == "cuda":
        capability = (compute_major or 0, compute_minor or 0)
        recommendation["compute_capability"] = f"{capability[0]}.{capability[1]}"
        candidate = None
        required_native_capabilities: set[str] = set()
        required_available_capabilities: set[str] = set()
        if capability[0] >= 10:
            candidate = (
                "quantized-nvfp4-low-vram",
                "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            )
            # The official NVFP4 Qwen file marks its linear layers as
            # full_precision_matrix_mult, so ComfyUI dequantizes NVFP4 weights
            # instead of calling scaled_mm_nvfp4. Its embedding table is stored
            # as int8_tensorwise and can use the enabled eager fallback.
            required_native_capabilities = {"int8_linear", "dequantize_nvfp4"}
            required_available_capabilities = {"dequantize_int8_embedding"}
        elif capability >= (7, 5):
            candidate = (
                "quantized-int8-low-vram",
                "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
            )
            required_native_capabilities = {"int8_linear"}

        if candidate is not None:
            recommendation.update(
                workflow_profile=candidate[0],
                text_encoder=candidate[1],
            )

        runtime_ready = True
        if (cuda_major or 0) < 13:
            runtime_ready = False
            recommendation["warnings"].append(
                "ComfyUI 0.33 optimized quantized CUDA operations require a cu130-or-newer PyTorch build."
            )
        if native_backend_ready is not True:
            runtime_ready = False
            recommendation["warnings"].append(
                "The enabled comfy-kitchen CUDA backend was not confirmed; inspect the runtime Native ops log before loading weights."
            )
        capabilities = native_capabilities or set()
        all_capabilities = available_capabilities or set()

        # A future/new NVIDIA GPU may satisfy the SM requirement while its
        # installed backend lacks the NVFP4 loader path. Prefer a working INT8
        # ConvRot route over reporting the entire machine unsupported.
        nvfp4_missing_native = {"int8_linear", "dequantize_nvfp4"} - capabilities
        nvfp4_missing_available = {"dequantize_int8_embedding"} - all_capabilities
        int8_ready = runtime_ready and not ({"int8_linear"} - capabilities)
        if (
            candidate is not None
            and candidate[0] == "quantized-nvfp4-low-vram"
            and (nvfp4_missing_native or nvfp4_missing_available)
            and int8_ready
        ):
            candidate = (
                "quantized-int8-low-vram",
                "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
            )
            required_native_capabilities = {"int8_linear"}
            required_available_capabilities = set()
            recommendation.update(
                workflow_profile=candidate[0],
                text_encoder=candidate[1],
            )
            recommendation["warnings"].append(
                "NVFP4 loader capabilities are incomplete; selected the larger INT8 ConvRot text encoder fallback."
            )

        missing_native_capabilities = sorted(required_native_capabilities - capabilities)
        if candidate is not None and missing_native_capabilities:
            runtime_ready = False
            recommendation["warnings"].append(
                "comfy-kitchen CUDA is missing required native capabilities: "
                + ", ".join(missing_native_capabilities)
            )
        missing_available_capabilities = sorted(
            required_available_capabilities - all_capabilities
        )
        if candidate is not None and missing_available_capabilities:
            runtime_ready = False
            recommendation["warnings"].append(
                "No enabled comfy-kitchen backend exposes required fallback capabilities: "
                + ", ".join(missing_available_capabilities)
            )
        recommendation["required_cuda_capabilities"] = sorted(
            required_native_capabilities
        )
        recommendation["required_any_backend_capabilities"] = sorted(
            required_available_capabilities
        )

        if candidate is not None and runtime_ready:
            recommendation["supported"] = True
        if candidate is not None and candidate[0] == "quantized-int8-low-vram":
            recommendation["warnings"].append(
                "INT8 ConvRot is the compatibility candidate; native execution must be confirmed in the ComfyUI Native ops log."
            )
        if candidate is None:
            recommendation["warnings"].append(
                "This NVIDIA compute capability has no validated MiniMax H3 low-memory quantized path in the current project."
            )
    elif backend == "rocm":
        recommendation["amd_arch"] = amd_arch
        matrix_core_arch = amd_arch.startswith(("gfx11", "gfx12")) or amd_arch in {
            "gfx908",
            "gfx90a",
            "gfx940",
            "gfx941",
            "gfx942",
            "gfx950",
        }
        if matrix_core_arch:
            recommendation["workflow_profile"] = "quantized-int8-low-vram"
            recommendation["text_encoder"] = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
            recommendation["warnings"].append(
                "Experimental only: ROCm needs Triton 3.7+ and explicit --enable-triton-backend; complete video validation is required."
            )
        else:
            recommendation["warnings"].append(
                "Current ComfyUI source does not provide a safe accelerated H3 INT8 path for this AMD architecture."
            )
    else:
        recommendation["warnings"].append(
            "No recommended native MiniMax H3 quantized low-memory backend is available for this device type."
        )

    recommendation["diffusion_model"] = (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        if recommendation["workflow_profile"]
        else None
    )
    if recommendation["workflow_profile"]:
        largest_stage_gib = (
            19.53
            if recommendation["workflow_profile"] == "quantized-nvfp4-low-vram"
            else 25.28
        )
        recommendation["largest_model_stage_gib"] = largest_stage_gib
        if system_ram_gib is None or available_ram_gib is None:
            recommendation["io_mode"] = "detect-at-runtime"
        elif (
            system_ram_gib >= largest_stage_gib + 8
            and available_ram_gib >= largest_stage_gib + 4
        ):
            recommendation["io_mode"] = "ram-assisted"
        else:
            recommendation["io_mode"] = "disk-streaming"
            recommendation["warnings"].append(
                "Total or currently available RAM misses the conservative stage headroom; keep disk streaming and staged release enabled."
            )
    recommendation["first_run"] = {
        "aspect_ratio": "9:16",
        "duration_seconds": 5,
        "steps": 4,
        "turbo": True,
        "ref_image_size": "match",
        "vae_tile_size": 256,
        "vae_temporal_size": 32,
    }
    return recommendation


def inspect_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
    import torch

    runtime: dict[str, Any] = {
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "rocm_runtime": torch.version.hip,
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        runtime["system_ram_gib"] = round(memory.total / (1024**3), 2)
        runtime["available_ram_gib"] = round(memory.available / (1024**3), 2)
    except Exception:
        runtime["system_ram_gib"] = None
        runtime["available_ram_gib"] = None
    kitchen: dict[str, Any] = {"available": False, "backends": {}}
    try:
        comfy_root = Path(sys.executable).resolve().parents[2]
        if (comfy_root / "comfy").is_dir() and str(comfy_root) not in sys.path:
            sys.path.insert(0, str(comfy_root))
        import comfy.cli_args  # noqa: F401 - initializes the active Comfy arguments
        import comfy.quant_ops  # noqa: F401 - applies backend enable/disable gates
        import comfy_kitchen

        kitchen["available"] = True
        kitchen["version"] = importlib.metadata.version("comfy-kitchen")
        kitchen["backends"] = comfy_kitchen.list_backends()
    except Exception as exc:  # Diagnostic output must survive a broken optional backend.
        kitchen["error"] = f"{type(exc).__name__}: {exc}"

    if not torch.cuda.is_available():
        return recommend_profile(
            backend="other",
            vram_gib=0,
            system_ram_gib=runtime["system_ram_gib"],
            available_ram_gib=runtime["available_ram_gib"],
        ), {**runtime, "comfy_kitchen": kitchen}

    properties = torch.cuda.get_device_properties(0)
    vram_gib = properties.total_memory / (1024**3)
    runtime["device_name"] = properties.name

    if torch.version.hip:
        amd_arch = getattr(properties, "gcnArchName", "").split(":", 1)[0]
        recommendation = recommend_profile(
            backend="rocm",
            vram_gib=vram_gib,
            amd_arch=amd_arch,
            system_ram_gib=runtime["system_ram_gib"],
            available_ram_gib=runtime["available_ram_gib"],
        )
    else:
        cuda_major = int(str(torch.version.cuda).split(".", 1)[0]) if torch.version.cuda else 0
        cuda_backend = kitchen["backends"].get("cuda", {})
        native_backend_ready = bool(
            cuda_backend.get("available") and not cuda_backend.get("disabled")
        )
        enabled_capabilities: set[str] = set()
        for backend_info in kitchen["backends"].values():
            if backend_info.get("available") and not backend_info.get("disabled"):
                enabled_capabilities.update(backend_info.get("capabilities", []))
        recommendation = recommend_profile(
            backend="cuda",
            vram_gib=vram_gib,
            compute_major=properties.major,
            compute_minor=properties.minor,
            cuda_major=cuda_major,
            system_ram_gib=runtime["system_ram_gib"],
            available_ram_gib=runtime["available_ram_gib"],
            native_backend_ready=native_backend_ready,
            native_capabilities=set(cuda_backend.get("capabilities", [])),
            available_capabilities=enabled_capabilities,
        )
    return recommendation, {**runtime, "comfy_kitchen": kitchen}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    recommendation, runtime = inspect_runtime()
    result = {"runtime": runtime, "recommendation": recommendation}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"GPU: {runtime.get('device_name', 'not detected')}")
        print(f"Backend: {recommendation['backend']}")
        print(f"VRAM tier: {recommendation['tier']} ({recommendation['vram_gib']} GiB)")
        print(f"Workflow profile: {recommendation['workflow_profile'] or 'unsupported'}")
        print(f"Text encoder: {recommendation['text_encoder'] or 'none'}")
        print(
            "Adaptive node: "
            f"{recommendation['adaptive_profile']} / "
            f"{recommendation['min_chunk_tokens']}-{recommendation['max_chunk_tokens']} tokens / "
            f"reserve={recommendation['reserve_vram_mb']} MiB / "
            f"prefetch={recommendation['prefetch_mode']}"
        )
        print(f"I/O mode: {recommendation.get('io_mode', 'unsupported')}")
        print(f"First-run megapixels: {recommendation['megapixels']}")
        for warning in recommendation["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if recommendation["supported"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
