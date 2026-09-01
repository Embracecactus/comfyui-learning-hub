@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Download the official Comfy-Org MiniMax H3 Ref2VA quantized model set.
rem Usage:
rem   download_minimax_h3_quantized_windows.cmd [MODEL_ROOT] [nvfp4|int8]

set "MODEL_ROOT=%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models"
if not "%~1"=="" set "MODEL_ROOT=%~1"

set "TEXT_PROFILE=nvfp4"
if not "%~2"=="" set "TEXT_PROFILE=%~2"

if not defined H3_MAX_DOWNLOAD_ATTEMPTS set "H3_MAX_DOWNLOAD_ATTEMPTS=100"

if /I "%TEXT_PROFILE%"=="nvfp4" goto :profile_ready
if /I "%TEXT_PROFILE%"=="int8" goto :profile_ready
echo [FAIL] Unknown text encoder profile: %TEXT_PROFILE%
echo        Choose nvfp4 for NVIDIA SM 10+ or int8 for the broader NVIDIA compatibility path.
exit /b 2

:profile_ready
if defined HF_ENDPOINT (
  set "HF_BASE=%HF_ENDPOINT%"
) else (
  set "HF_BASE=https://hf-mirror.com"
)

echo Model root: %MODEL_ROOT%
echo Text encoder profile: %TEXT_PROFILE%
echo Download endpoint: %HF_BASE%
echo Maximum reconnect attempts per file: %H3_MAX_DOWNLOAD_ATTEMPTS%
if /I "%TEXT_PROFILE%"=="nvfp4" (
  echo Complete model set: about 41.38 GiB.
) else (
  echo Complete model set: about 52.04 GiB.
)
if defined H3_VERIFY_ONLY echo Verify-only mode: URLs will be checked without downloading models.
echo.

for %%D in (diffusion_models text_encoders vae loras) do (
  if not exist "%MODEL_ROOT%\%%D" mkdir "%MODEL_ROOT%\%%D"
)

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors" "%MODEL_ROOT%\diffusion_models\minimax_h3_ref2va_pruned_int8_convrot.safetensors" 20970379616
if errorlevel 1 exit /b 1

if /I "%TEXT_PROFILE%"=="nvfp4" (
  call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" "%MODEL_ROOT%\text_encoders\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" 15687142551
) else (
  call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors" "%MODEL_ROOT%\text_encoders\qwen3vl_32b_minimax_h3_int8_convrot.safetensors" 27141342152
)
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors" "%MODEL_ROOT%\vae\minimax_h3_video_vae_fp16.safetensors" 5207808496
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors" "%MODEL_ROOT%\vae\minimax_h3_audio_vae_fp32.safetensors" 605254808
if errorlevel 1 exit /b 1

call :download "%HF_BASE%/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" "%MODEL_ROOT%\loras\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" 1956193000
if errorlevel 1 exit /b 1

echo.
if defined H3_VERIFY_ONLY (
  echo All download URLs passed the HEAD check. No model files were downloaded.
  exit /b 0
)
echo All quantized MiniMax H3 files are ready.
echo Restart ComfyUI before importing the matching workflow.
exit /b 0

:download
set "DOWNLOAD_URL=%~1"
set "FINAL_FILE=%~2"
set "EXPECTED_SIZE=%~3"
if defined H3_VERIFY_ONLY (
  echo [HEAD] %DOWNLOAD_URL%
  curl.exe -L --fail --retry 3 -I "%DOWNLOAD_URL%" >nul
  exit /b %ERRORLEVEL%
)

if exist "%FINAL_FILE%" (
  for %%S in ("%FINAL_FILE%") do set "ACTUAL_SIZE=%%~zS"
  if "!ACTUAL_SIZE!"=="!EXPECTED_SIZE!" (
    echo [SKIP] %FINAL_FILE% ^(!ACTUAL_SIZE! bytes verified^)
    exit /b 0
  )
  echo [FAIL] Existing file has !ACTUAL_SIZE! bytes; expected !EXPECTED_SIZE!.
  echo        Delete or rename the bad final file, then run this script again.
  exit /b 1
)

set "LOCK_DIR=%FINAL_FILE%.download.lock"
2>nul mkdir "!LOCK_DIR!"
if errorlevel 1 (
  echo [FAIL] Another downloader already owns !LOCK_DIR!
  echo        Do not run two writers for the same model. If no curl.exe is active,
  echo        remove this stale lock directory and retry.
  exit /b 1
)

echo [GET ] %FINAL_FILE%
set /a DOWNLOAD_ATTEMPT=0

:download_retry
set /a DOWNLOAD_ATTEMPT+=1
rem Do not combine curl's internal --retry with -C -. Some CDN disconnects make
rem one curl process reuse its original Range offset and append duplicate bytes.
rem A fresh curl process re-reads the current .download size on every attempt.
curl.exe -L --fail --connect-timeout 30 --speed-limit 262144 --speed-time 45 -C - -o "%FINAL_FILE%.download" "%DOWNLOAD_URL%"
set "CURL_EXIT=!ERRORLEVEL!"
rem A killed Windows process can report a negative code. `if not errorlevel 1`
rem treats that as success, so accept only the exact curl success code.
if "!CURL_EXIT!"=="0" goto :download_complete
if !DOWNLOAD_ATTEMPT! GEQ !H3_MAX_DOWNLOAD_ATTEMPTS! (
  echo [FAIL] Keep the .download file and run this script again to resume.
  rmdir "!LOCK_DIR!" >nul 2>&1
  exit /b 1
)
echo [RETRY !DOWNLOAD_ATTEMPT!/!H3_MAX_DOWNLOAD_ATTEMPTS!] curl exit !CURL_EXIT!; re-reading the partial file size in 5 seconds...
rem `timeout` exits immediately when this batch is launched through redirected
rem WSL stdin. Localhost ping provides the intended delay in both CMD and WSL.
ping.exe -n 6 127.0.0.1 >nul
goto :download_retry

:download_complete

for %%S in ("%FINAL_FILE%.download") do set "ACTUAL_SIZE=%%~zS"
if not "!ACTUAL_SIZE!"=="!EXPECTED_SIZE!" (
  echo [FAIL] Download has !ACTUAL_SIZE! bytes; expected !EXPECTED_SIZE!.
  echo        The .download file was kept. Check the URL or upstream revision before retrying.
  rmdir "!LOCK_DIR!" >nul 2>&1
  exit /b 1
)

move /Y "%FINAL_FILE%.download" "%FINAL_FILE%" >nul
rmdir "!LOCK_DIR!" >nul 2>&1
echo [DONE] %FINAL_FILE% ^(!ACTUAL_SIZE! bytes verified^)
exit /b 0
