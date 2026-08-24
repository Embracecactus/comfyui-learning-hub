#!/usr/bin/env bash
#
# deploy_comfyui_h3_dsw.sh
# -------------------------------------------------------------
# 阿里云 PAI DSW (JupyterLab Terminal) 一键部署 ComfyUI，
# 用于跑 MiniMax H3 demo。仅做「安装 + 启动 + 打开 Web UI」，
# H3 权重通过 ComfyUI 模板库 UI 一键下载（最稳，见末尾说明）。
#
# 用法：
#   bash deploy_comfyui_h3_dsw.sh
# 可选环境变量：
#   COMFY_DIR    安装目录（默认 /mnt/workspace/ComfyUI）
#   COMFY_PORT   端口（默认 8188）
#   DOWNLOAD_H3=1  额外用 huggingface-cli 预拉 H3 权重（默认关，因体积大且 UI 更稳）
#
# 关键前提（不满足会在运行时报错，脚本会提示）：
#   - ComfyUI 必须 >= 0.30.0（原生内置 H3 节点）
#   - int8_convrot 权重需 torch 带 cu130；否则在 UI 选 fp8_scaled 版
# -------------------------------------------------------------
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-/mnt/workspace/ComfyUI}"
COMFY_PORT="${COMFY_PORT:-8188}"
TORCH_CUDA_NEEDED="13.0"   # int8_convrot 需 cu130

echo "=================================================="
echo "[0/5] 硬件确认"
echo "=================================================="
nvidia-smi || echo "  [警告] nvidia-smi 不可用，确认实例已选 GPU 规格"
echo "----- 系统内存 -----"
free -h || true
echo "----- 磁盘 -----"
df -h "$COMFY_DIR" 2>/dev/null || true

echo
echo "=================================================="
echo "[1/5] 克隆 / 更新 ComfyUI"
echo "=================================================="
if [ -d "$COMFY_DIR/.git" ]; then
  echo "已存在，执行 git pull ..."
  git -C "$COMFY_DIR" pull --ff-only
else
  echo "克隆到 $COMFY_DIR ..."
  git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
fi

echo
echo "=================================================="
echo "[2/5] 安装依赖"
echo "=================================================="
cd "$COMFY_DIR"
pip install -r requirements.txt

echo
echo "=================================================="
echo "[3/5] 检查 torch CUDA 版本（int8_convrot 需 cu${TORCH_CUDA_NEEDED}）"
echo "=================================================="
CUDA_VER="$(python -c 'import torch; print(torch.version.cuda)' 2>/dev/null || echo unknown)"
echo "torch CUDA 版本: $CUDA_VER"
if [ "$CUDA_VER" != "$TORCH_CUDA_NEEDED" ]; then
  echo "  [提示] 当前非 cu${TORCH_CUDA_NEEDED}。请在 ComfyUI 模板下载 H3 权重时"
  echo "         选择 fp8_scaled 版本（而非 int8_convrot），否则量化算子不兼容。"
else
  echo "  [OK] cu${TORCH_CUDA_NEEDED} 满足，可使用 int8_convrot 权重。"
fi

echo
echo "=================================================="
echo "[4/5] 启动 ComfyUI（后台 nohup）"
echo "=================================================="
# 若已有一个在跑，先不重复启动
if pgrep -f "main.py --listen" >/dev/null 2>&1; then
  echo "检测到已有 ComfyUI 进程，跳过启动。"
else
  nohup python main.py --listen 0.0.0.0 --port "$COMFY_PORT" > comfy.log 2>&1 &
  echo "已后台启动，PID $!"
fi
echo "日志: $COMFY_DIR/comfy.log"
echo "稍等约 10-30s 后，在 DSW 终端输出 / 文件浏览器里点击:"
echo "    http://127.0.0.1:${COMFY_PORT}"
echo "即可经 DSW 内置代理在浏览器打开 Web UI。"

echo
echo "=================================================="
echo "[5/5] 接 MiniMax H3（在 Web UI 内完成，最稳）"
echo "=================================================="
echo "1) 确认 ComfyUI 版本 >= 0.30.0（菜单 Help > About，或 git pull 更新后重启）。"
echo "2) 左侧 模板库(Templates) -> 视频 -> MiniMax H3，选 T2V / I2V / R2V 工作流。"
echo "3) 弹窗提示下载模型 -> 确认，权重自动从 Comfy-Org/MiniMax-H3 拉取并放好。"
echo "   推荐组合: int8_convrot DiT + nvfp4_awq 文本编码器 + 2 个 VAE（+可选 Turbo LoRA）。"
echo "   (若 torch 非 cu130，选 fp8_scaled 版 DiT)"
echo "4) 跑最小片段验证: 预览分辨率(短边768) / 5s / 24fps / 开 turbo 8 步。"
echo "5) 记稳态耗时 T 秒，反推产出: 片段数 ≈ 216000 / T （60h = 216000 GPU 秒）。"

# ---- 可选：预拉权重（默认关闭）----
if [ "${DOWNLOAD_H3:-0}" = "1" ]; then
  echo
  echo "=================================================="
  echo "[可选] 预拉 H3 权重 (DOWNLOAD_H3=1)"
  echo "=================================================="
  pip install -q -U "huggingface_hub[cli]" 2>/dev/null || true
  HF_TARGET="${COMFY_DIR}/models/MiniMax-H3"
  mkdir -p "$HF_TARGET"
  # 优先 HF；如慢可改 H,F_ENDPOINT=https://hf-mirror.com 或用 modelscope
  huggingface-cli download Comfy-Org/MiniMax-H3 \
    --local-dir "$HF_TARGET" \
    --include "*pruned_int8_convrot*" "*nvfp4_awq*" "*.fp16*" "*.fp32*" \
    || echo "  [警告] HF 拉取失败，请直接在 Web UI 模板库下载（更稳）。"
  echo "权重目录: $HF_TARGET"
fi

echo
echo "完成。实例不用时请手动停止，避免持续计费；如开了 NAT+EIP/GA 也请删除。"
