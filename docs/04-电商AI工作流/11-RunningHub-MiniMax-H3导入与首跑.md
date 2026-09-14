# RunningHub MiniMax H3 导入与首跑

这是一份给小白使用的 RunningHub 迁移说明。它对应“商品/服装主图 + 提示词 + 动作参考视频 → 竖屏带货视频”的独立工作流，不依赖本项目给 RTX 5060 准备的低显存自定义节点。

> **2026-09-02 实跑结论：只通过了 RunningHub 导入和生成兼容性，没有通过换装功能验收。** 实际输出仍基本是参考视频里的黑色花裙人物，上传的 `1977` 卫衣没有取得服装控制权。复盘确认，本版错误地把本地成功版的后半段和卫衣专用提示词改成了前半段与通用提示词。本文和 JSON 仅保留为失败对照；请改用[RunningHub H3 卫衣等条件复跑](13-RunningHub-H3卫衣等条件复跑.md)。

## 1. 下载工作流

导入这个文件：

[`workflows/yinghai-h3-runninghub-0.2mp.json`](workflows/yinghai-h3-runninghub-0.2mp.json)

不要把文件名带有 `low-vram` 的本地版上传到 RunningHub。本地版依赖 `comfyui_adaptive_memory`，RunningHub 没有这些项目私有节点。

## 2. 导入后先看什么

工作流应当不再出现以下六个红色缺失节点：

- `MiniMaxH3AdaptiveMemory`
- `H3ReleaseAfterConditioning`
- `H3ReleaseAfterSampling`
- `H3VAEDecodeTiledRelease`
- `H3VAEDecodeAudioRelease`
- `H3ReferenceVideoFrames24FPS`

如果页面提示“媒体未选择”，这是正常的：为了避免携带本机文件名，RunningHub 版故意把图片和视频输入清空了。

## 3. 按编号填写三个输入

### ① 上传商品/服装主图

找到标题为“① 上传商品/服装主图｜Picture 1（必选）”的 `LoadImage` 节点。

- 建议主体清晰、遮挡少。
- 白底图、模特实拍图都可以先测试。
- 商品外观以这张图为准。

### ② 上传动作参考视频

找到标题为“② 上传动作参考视频｜Video 1”的 `LoadVideo` 节点。

- 建议预先转成 **24 FPS**。
- 建议视频长度至少 **5.2 秒**。
- 当前工作流读取开头 5.2 秒。
- 参考视频只提供动作、镜头运动、节奏和场景，不应覆盖商品身份。

官方 `MiniMaxH3ReferenceToVideo` 会在内部把参考帧裁剪为 H3 合法的 `17n+5` 数量。工作流因此不再需要本地的 `H3ReferenceVideoFrames24FPS`，但它不会自动修正非 24 FPS 视频的动作速度。

如果原视频不是 24 FPS，可先使用 FFmpeg 转换：

```bat
ffmpeg -i input.mp4 -vf "fps=24" -t 5.2 -an -c:v libx264 -pix_fmt yuv420p reference-24fps.mp4
```

### ③ 填写提示词

找到标题为“③ 填写提示词”的文本节点。保留以下角色约定：

- `<Picture 1>`：商品或服装身份、颜色、版型、纹理和细节。
- `<Video 1>`：人物动作、运镜、节奏和场景构图。

首次测试只修改商品描述和想要的画面，不要删除“不要复制 Video 1 原服装”的限制。

注意：上述内容是原设计约定，不是实跑结果。H3 的完整参考视频条件仍强烈保留了原视频服装，负向提示词没有解决条件冲突。

## 4. 第一次运行

首次保持默认值：

- 画幅：`9:16`
- 分辨率：约 `0.2 MP`
- 时长：`5 秒`
- Turbo LoRA：开启
- 采样：`4 步`
- 参考图尺寸：`match`

点击运行后，先确认模型加载、条件编码、采样、视频 VAE、音频 VAE 和保存节点依次完成。首次通过后再把分辨率提高到 `0.4 MP`，一次只改一个变量。

## 5. 模型下拉框变红怎么办

RunningHub 的模型库存会变化。如果模型名称变红，在节点的下拉框中选择平台当前提供的同系列模型。当前工作流使用：

```text
diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors
text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
vae/minimax_h3_video_vae_fp16.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors
loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
```

RunningHub 当前公开的 H3 参考视频工作流也使用 `MiniMaxH3ReferenceToVideo`、`VAEDecode` 和 `VAEDecodeAudio` 这条官方解码路线，可用于核对平台节点是否仍然在线：[RunningHub H3 Reference-to-Video 工作流](https://www.runninghub.ai/post/2084160024145948674)。

## 6. 与本地低显存版的区别

| 项目 | RunningHub 版 | 本地低显存版 |
| --- | --- | --- |
| 运行位置 | RunningHub GPU | 自己的电脑/服务器 |
| 项目私有节点 | 不需要 | 需要 `comfyui_adaptive_memory` |
| 模型分阶段主动卸载 | 不保留 | 保留 |
| H3 MLP 自适应分块 | 不保留 | 保留 |
| 视频/音频解码 | 官方 `VAEDecode` / `VAEDecodeAudio` | 项目低峰值解码节点 |
| 适合用途 | 云端导入、分享、发布 API | 8 GB 等有限显存机器 |

RunningHub 版的目标是平台兼容，不代表它还能在本地 8 GB 显存机器上运行。两份 JSON 应分别保存，不要相互覆盖。

## 7. 生成方式与验证边界

RunningHub 文件由下面的脚本从已经跑通的本地 0.2 MP 工作流确定性生成：

```bash
node scripts/derive_runninghub_h3_workflow.mjs
```

脚本会移除项目私有节点、重连官方节点、清除本机媒体文件名，并检查是否还有残留的六种节点。仓库能够验证 JSON 和本地 ComfyUI 节点结构；真正的 RunningHub 云端执行仍需导入后进行一次首跑确认。
