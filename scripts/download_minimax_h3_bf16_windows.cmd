@echo off
setlocal EnableExtensions

rem MiniMax H3 Ref2VA BF16 streaming profile for ComfyUI Desktop on Windows.
rem No INT8, FP8, NVFP4, NF4, or GGUF model weights are downloaded.

set "MODEL_ROOT=C:\Users\lijian\AppData\Local\Comfy-Desktop\ComfyUI-Shared\models"
if not "%~1"=="" set "MODEL_ROOT=%~1"

if defined HF_ENDPOINT (
  set "HF_BASE=%HF_ENDPOINT%"
) else (
  set "HF_BASE=https://hf-mirror.com"
)

echo Model root: %MODEL_ROOT%
echo Download endpoint: %HF_BASE%
echo Required free space: at least 105 GB for model files.
if defined H3_VERIFY_ONLY echo Verify-only mode: URLs will be checked without downloading models.
echo.

for %%D in (diffusion_models text_encoders vae loras) do (
  if not exist "%MODEL_ROOT%\%%D" mkdir "%MODEL_ROOT%\%%D"
)

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors" "%MODEL_ROOT%\diffusion_models\minimax_h3_ref2va_pruned_bf16.safetensors"
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors" "%MODEL_ROOT%\text_encoders\qwen3vl_32b_minimax_h3_bf16.safetensors"
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors" "%MODEL_ROOT%\vae\minimax_h3_video_vae_fp16.safetensors"
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors" "%MODEL_ROOT%\vae\minimax_h3_audio_vae_fp32.safetensors"
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" "%MODEL_ROOT%\loras\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
if errorlevel 1 exit /b 1

echo.
if defined H3_VERIFY_ONLY (
  echo All download URLs passed the HEAD check. No model files were downloaded.
  exit /b 0
)
echo All BF16/FP model files are ready.
echo Restart ComfyUI Desktop before importing the workflow.
exit /b 0

:download
set "DOWNLOAD_URL=%~1"
set "FINAL_FILE=%~2"
if defined H3_VERIFY_ONLY (
  echo [HEAD] %DOWNLOAD_URL%
  curl.exe -L --fail --retry 3 -I "%DOWNLOAD_URL%" >nul
  exit /b %ERRORLEVEL%
)

if exist "%FINAL_FILE%" (
  echo [SKIP] %FINAL_FILE%
  exit /b 0
)

echo [GET ] %FINAL_FILE%
curl.exe -L --fail --retry 20 --retry-all-errors --retry-delay 5 -C - -o "%FINAL_FILE%.download" "%DOWNLOAD_URL%"
if errorlevel 1 (
  echo [FAIL] Keep the .download file and run this script again to resume.
  exit /b 1
)

move /Y "%FINAL_FILE%.download" "%FINAL_FILE%" >nul
echo [DONE] %FINAL_FILE%
exit /b 0
