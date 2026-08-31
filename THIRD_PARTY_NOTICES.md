# Third-Party Notices

## Comfy-Org/workflow_templates

The files
`docs/04-电商AI工作流/workflows/ecommerce-reference-main-image-flux2-klein.json`
and
`docs/04-电商AI工作流/workflows/ecommerce-yinghai-hoodie-comparison-flux2-klein.json`
and
`docs/04-电商AI工作流/workflows/ecommerce-yinghai-hoodie-model-full-flux2-klein.json`
and
`docs/04-电商AI工作流/workflows/ecommerce-yinghai-hoodie-model-close-flux2-klein.json`
and
`docs/04-电商AI工作流/workflows/ecommerce-minimax-h3-local-ref2va.json`
are derived from:

```text
https://github.com/Comfy-Org/workflow_templates
templates/image_flux2_klein_image_edit_4b_distilled.json
templates/video_minimax_h3_r2v.json
```

The upstream project is distributed under the MIT License:

```text
MIT License

Copyright (c) 2023-present Comfy Org

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Upstream license source:
<https://github.com/Comfy-Org/workflow_templates/blob/main/LICENSE>

## MiniMax H3 local model dependencies

`docs/04-电商AI工作流/workflows/ecommerce-minimax-h3-local-ref2va.json`
references the following local model files without redistributing them:

```text
diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors
text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
vae/minimax_h3_video_vae_fp16.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors
loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
```

The model files are hosted at:
<https://huggingface.co/Comfy-Org/MiniMax-H3>

MiniMax H3 is distributed under the MiniMax H3 Community License Agreement,
not the MIT License used by the workflow template repository. Review the
current license in the model repository before deployment or commercial use.

## RealESRGAN_x4plus local model dependency

`docs/04-电商AI工作流/workflows/ecommerce-generic-product-layout-2k-branded.json`
references the local model file `RealESRGAN_x4plus.pth`. The model file is not
redistributed in this repository. The tutorial downloads it from a mirror of:

```text
https://github.com/xinntao/Real-ESRGAN
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
```

Real-ESRGAN is distributed under the BSD 3-Clause License. Upstream license:
<https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE>

The expected SHA-256 for the local model dependency is:

```text
4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1
```
