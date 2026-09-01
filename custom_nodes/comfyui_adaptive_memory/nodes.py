from __future__ import annotations

import inspect
import logging

import torch
from typing_extensions import override

import comfy.model_management
import comfy.patcher_extension
from comfy_extras.nodes_audio import vae_decode_audio
from comfy.ldm.minimax.model import MiniMaxH3Model
from comfy_api.latest import ComfyExtension, io

from .runtime import AdaptiveH3MLPForward, AdaptiveH3RuntimeState, AdaptiveH3Settings


ADAPTIVE_WRAPPER_KEY = "comfyui_adaptive_memory_h3"
UNLOAD_SUPPORTS_ALL_DEVICES = (
    "all_devices" in inspect.signature(comfy.model_management.unload_model_and_clones).parameters
)


def _infer_ffn_hidden_size(diffusion_model: MiniMaxH3Model) -> int:
    try:
        return int(diffusion_model.blocks[0].mlp.fc1.weight.shape[0] // 2)
    except (AttributeError, IndexError, TypeError):
        return 14336


def _release_model_objects(objects) -> None:
    released = set()
    for obj in objects:
        patcher = getattr(obj, "patcher", obj)
        clone_id = getattr(patcher, "clone_base_uuid", None)
        identity = clone_id if clone_id is not None else id(patcher)
        if patcher is None or identity in released:
            continue
        if UNLOAD_SUPPORTS_ALL_DEVICES:
            comfy.model_management.unload_model_and_clones(
                patcher,
                unload_additional_models=True,
                all_devices=True,
            )
        else:
            comfy.model_management.unload_model_and_clones(patcher, unload_additional_models=True)
        released.add(identity)
    comfy.model_management.soft_empty_cache()


class AdaptiveH3DiffusionWrapper:
    def __init__(self, state: AdaptiveH3RuntimeState):
        self.state = state

    def __call__(
        self,
        executor,
        x,
        timestep,
        context,
        transformer_options=None,
        minimax_payload=None,
        **kwargs,
    ):
        options = dict(transformer_options or {})
        device = x[0].device
        streams = int(getattr(comfy.model_management, "NUM_STREAMS", 0))
        self.state.begin_forward(device, streams)
        prefetch_enabled, prefetch_reason = self.state.resolve_prefetch()
        options["prefetch_dynamic_vbars"] = prefetch_enabled
        if self.state.settings.verbose and self.state.forward_index == 1:
            logging.info(
                "Adaptive H3 memory: block prefetch %s (%s)",
                "enabled" if prefetch_enabled else "disabled",
                prefetch_reason,
            )
        # The packed stream length becomes available at the first MLP. Its adaptive
        # decision is then reused by every H3 block in this diffusion forward.
        result = executor(
            x,
            timestep,
            context,
            options,
            minimax_payload=minimax_payload,
            **kwargs,
        )
        return result


class MiniMaxH3AdaptiveMemory(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3AdaptiveMemory",
            display_name="MiniMax H3 Adaptive Memory",
            description=(
                "Sizes H3 MLP token chunks from live VRAM instead of a GPU-name table. "
                "Works with BF16, INT8, or NVFP4 weights; weight precision and activation "
                "precision are handled separately."
            ),
            category="advanced/model_patches",
            is_experimental=True,
            inputs=[
                io.Model.Input("model"),
                io.Boolean.Input("enabled", default=True),
                io.Combo.Input(
                    "profile",
                    options=["auto_stable", "auto_balanced", "auto_speed", "manual"],
                    default="auto_stable",
                ),
                io.Int.Input(
                    "reserve_vram_mb",
                    default=1024,
                    min=256,
                    max=32768,
                    step=128,
                    tooltip="VRAM kept for attention, sampler, desktop display, and allocator variation.",
                ),
                io.Combo.Input(
                    "prefetch_mode",
                    options=["auto", "disable", "keep"],
                    default="auto",
                    tooltip="Auto enables block-ahead reads only when async offload, VRAM, and RAM allow it.",
                ),
                io.Int.Input("min_chunk_tokens", default=1024, min=256, max=32768, step=256, advanced=True),
                io.Int.Input("max_chunk_tokens", default=8192, min=256, max=262144, step=256, advanced=True),
                io.Int.Input("manual_chunk_tokens", default=4096, min=256, max=262144, step=256, advanced=True),
                io.Boolean.Input("verbose", default=True, advanced=True),
            ],
            outputs=[io.Model.Output()],
        )

    @classmethod
    def execute(
        cls,
        model,
        enabled,
        profile,
        reserve_vram_mb,
        prefetch_mode,
        min_chunk_tokens,
        max_chunk_tokens,
        manual_chunk_tokens,
        verbose,
    ) -> io.NodeOutput:
        if not enabled:
            return io.NodeOutput(model)
        if min_chunk_tokens > max_chunk_tokens:
            raise ValueError("min_chunk_tokens cannot exceed max_chunk_tokens")

        diffusion_model = model.get_model_object("diffusion_model")
        if not isinstance(diffusion_model, MiniMaxH3Model):
            raise ValueError("MiniMax H3 Adaptive Memory requires a native MiniMax H3 model")

        settings = AdaptiveH3Settings(
            profile=profile,
            reserve_vram_mb=reserve_vram_mb,
            min_chunk_tokens=min_chunk_tokens,
            max_chunk_tokens=max_chunk_tokens,
            manual_chunk_tokens=manual_chunk_tokens,
            prefetch_mode=prefetch_mode,
            hidden_size=int(diffusion_model.hidden_size),
            ffn_hidden_size=_infer_ffn_hidden_size(diffusion_model),
            model_size_mb=float(model.model_size()) / (1024 * 1024),
            verbose=verbose,
        )
        state = AdaptiveH3RuntimeState(settings)
        patched = model.clone()
        for index in range(len(diffusion_model.blocks)):
            path = f"diffusion_model.blocks.{index}.mlp.forward"
            if path in model.object_patches:
                raise ValueError(
                    "MiniMax H3 Adaptive Memory cannot be stacked after another H3 MLP patch"
                )
            original_forward = patched.get_model_object(path)
            patched.add_object_patch(path, AdaptiveH3MLPForward(original_forward, state))
        patched.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL,
            ADAPTIVE_WRAPPER_KEY,
            AdaptiveH3DiffusionWrapper(state),
        )
        if verbose:
            logging.info(
                "MiniMax H3 Adaptive Memory patched %d blocks; profile=%s, reserve=%d MiB",
                len(diffusion_model.blocks),
                profile,
                reserve_vram_mb,
            )
        return io.NodeOutput(patched)


class H3ReleaseAfterConditioning(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3ReleaseAfterConditioning",
            display_name="H3 Release Encoders After Conditioning",
            description=(
                "Passes conditioning/latent through, then unloads Qwen and the reference VAEs. "
                "A later branch may reuse a VAE only after this node's data dependency; ComfyUI "
                "will load that VAE again when decode starts."
            ),
            category="advanced/model_management",
            inputs=[
                io.Clip.Input("clip"),
                io.Vae.Input("video_vae"),
                io.Vae.Input("audio_vae"),
                io.Conditioning.Input("conditioning"),
                io.Latent.Input("latent"),
                io.Boolean.Input("release", default=True),
            ],
            outputs=[io.Conditioning.Output(), io.Latent.Output()],
        )

    @classmethod
    def execute(cls, clip, video_vae, audio_vae, conditioning, latent, release) -> io.NodeOutput:
        if release:
            _release_model_objects((clip, video_vae, audio_vae))
            logging.info("Adaptive memory: released H3 text/reference encoders before sampling")
        return io.NodeOutput(conditioning, latent)

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        # Resource release is a side effect and must not disappear behind ComfyUI's cache.
        return float("NaN")


class H3ReleaseAfterSampling(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3ReleaseAfterSampling",
            display_name="H3 Release DiT After Sampling",
            description="Passes the sampled latent through and unloads the final patched H3 model before VAE decode.",
            category="advanced/model_management",
            inputs=[
                io.Model.Input("model"),
                io.Latent.Input("samples"),
                io.Boolean.Input("release", default=True),
            ],
            outputs=[io.Latent.Output()],
        )

    @classmethod
    def execute(cls, model, samples, release) -> io.NodeOutput:
        if release:
            _release_model_objects((model,))
            logging.info("Adaptive memory: released H3 DiT before VAE decode")
        return io.NodeOutput(samples)

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        # Always perform the post-sampling unload, even when upstream values fingerprint alike.
        return float("NaN")


class H3VAEDecodeTiledRelease(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3VAEDecodeTiledRelease",
            display_name="H3 VAE Decode Tiled and Release",
            description="Tiled video decode followed by targeted VAE release.",
            category="advanced/model_management",
            inputs=[
                io.Latent.Input("samples"),
                io.Vae.Input("vae"),
                io.Int.Input("tile_size", default=256, min=64, max=4096, step=32),
                io.Int.Input("overlap", default=64, min=0, max=4096, step=32),
                io.Int.Input("temporal_size", default=32, min=8, max=4096, step=4),
                io.Int.Input("temporal_overlap", default=8, min=4, max=4096, step=4),
                io.Boolean.Input("release", default=True),
            ],
            outputs=[io.Image.Output(), io.Boolean.Output("released")],
        )

    @classmethod
    def execute(
        cls,
        samples,
        vae,
        tile_size,
        overlap,
        temporal_size,
        temporal_overlap,
        release,
    ) -> io.NodeOutput:
        try:
            if tile_size < overlap * 4:
                overlap = tile_size // 4
            if temporal_size < temporal_overlap * 2:
                temporal_overlap = temporal_size // 2
            temporal_compression = vae.temporal_compression_decode()
            if temporal_compression is not None:
                temporal_size = max(2, temporal_size // temporal_compression)
                temporal_overlap = max(
                    1,
                    min(temporal_size // 2, temporal_overlap // temporal_compression),
                )
            else:
                temporal_size = None
                temporal_overlap = None

            latent = samples["samples"]
            if latent.is_nested:
                latent = latent.unbind()[0]
            compression = vae.spacial_compression_decode()
            images = vae.decode_tiled(
                latent,
                tile_x=tile_size // compression,
                tile_y=tile_size // compression,
                overlap=overlap // compression,
                tile_t=temporal_size,
                overlap_t=temporal_overlap,
            )
            if len(images.shape) == 5:
                images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
            return io.NodeOutput(images, bool(release))
        finally:
            if release:
                _release_model_objects((vae,))
                logging.info("Adaptive memory: released H3 video VAE after tiled decode")


class H3VAEDecodeAudioRelease(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3VAEDecodeAudioRelease",
            display_name="H3 VAE Decode Audio and Release",
            description=(
                "Audio decode followed by targeted VAE release. The video_release_barrier input "
                "forces video decode and its VAE release to finish first, preventing both VAEs "
                "from becoming resident together."
            ),
            category="advanced/model_management",
            inputs=[
                io.Latent.Input("samples"),
                io.Vae.Input("vae"),
                io.Boolean.Input("video_release_barrier"),
                io.Boolean.Input("release", default=True),
            ],
            outputs=[io.Audio.Output()],
        )

    @classmethod
    def execute(cls, samples, vae, video_release_barrier, release) -> io.NodeOutput:
        if not video_release_barrier:
            raise ValueError(
                "Audio decode requires the video VAE to be released first. "
                "Enable release on H3 VAE Decode Tiled and Release."
            )
        try:
            return io.NodeOutput(vae_decode_audio(vae, samples))
        finally:
            if release:
                _release_model_objects((vae,))
                logging.info("Adaptive memory: released H3 audio VAE after decode")


class AdaptiveMemoryExtension(ComfyExtension):
    @override
    async def get_node_list(self):
        return [
            MiniMaxH3AdaptiveMemory,
            H3ReleaseAfterConditioning,
            H3ReleaseAfterSampling,
            H3VAEDecodeTiledRelease,
            H3VAEDecodeAudioRelease,
        ]


async def comfy_entrypoint():
    return AdaptiveMemoryExtension()
