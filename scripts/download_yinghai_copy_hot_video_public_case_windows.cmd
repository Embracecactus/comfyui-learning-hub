@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "INPUT_ROOT=%~1"
if not defined INPUT_ROOT set "INPUT_ROOT=%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\input"
set "TARGET_DIR=%INPUT_ROOT%"

where curl.exe >nul 2>nul || (
  echo [ERROR] Windows curl.exe was not found.
  exit /b 1
)
where certutil.exe >nul 2>nul || (
  echo [ERROR] Windows certutil.exe was not found.
  exit /b 1
)

if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%" || exit /b 1

call :download ^
  "https://oss.yinghai.xin/public/video/0/e54dae53fc861e9fd9aa2d0067c7c790/1786628368222_79vb8q.mp4" ^
  "yinghai-copy-hot-video-v2-01-benchmark.mp4" ^
  "2359091" ^
  "8197dbd88e5bf93700ab35244f3f346f1fb41d1a41cd4a428cf57cc2896873be" || exit /b 1

call :download ^
  "https://oss.yinghai.xin/public/image/0/e54dae53fc861e9fd9aa2d0067c7c790/1786628405980_n58vrs.png" ^
  "yinghai-copy-hot-video-v2-02-product.png" ^
  "1233431" ^
  "450f7bad7c5a915e90d924655044ef0a09103f88df6d9eca7cc7ad5781614e00" || exit /b 1

call :download ^
  "https://oss.yinghai.xin/public/video/0/e54dae53fc861e9fd9aa2d0067c7c790/1786628333362_qz7rlp.mp4" ^
  "yinghai-copy-hot-video-v2-03-site-result.mp4" ^
  "16396862" ^
  "66c8066f1537991c30cb9c1a1c053b62d06f8da7f8a4ecf0730933a00e54a448" || exit /b 1

echo.
echo [OK] Public comparison files are ready in:
echo %TARGET_DIR%
echo Files intentionally stay in the input root for ComfyUI 0.33.x media discovery.
echo These files are third-party public case material. Do not redistribute them.
exit /b 0

:download
set "SOURCE_URL=%~1"
set "FILE_NAME=%~2"
set "EXPECTED_SIZE=%~3"
set "EXPECTED_SHA=%~4"
set "FINAL_PATH=%TARGET_DIR%\%FILE_NAME%"
set "PART_PATH=%FINAL_PATH%.download"

if exist "%FINAL_PATH%" call :verify "%FINAL_PATH%" "%EXPECTED_SIZE%" "%EXPECTED_SHA%" && (
  echo [SKIP] %FILE_NAME%
  exit /b 0
)

echo [DOWNLOAD] %FILE_NAME%
curl.exe -L --fail --retry 20 --retry-all-errors --retry-delay 5 -C - -o "%PART_PATH%" "%SOURCE_URL%"
if errorlevel 1 (
  echo [ERROR] Download failed. Run the same command again to resume.
  exit /b 1
)

call :verify "%PART_PATH%" "%EXPECTED_SIZE%" "%EXPECTED_SHA%" || exit /b 1
move /y "%PART_PATH%" "%FINAL_PATH%" >nul || exit /b 1
echo [OK] %FILE_NAME%
exit /b 0

:verify
set "VERIFY_PATH=%~1"
set "VERIFY_SIZE=%~2"
set "VERIFY_SHA=%~3"
for %%I in ("%VERIFY_PATH%") do set "ACTUAL_SIZE=%%~zI"
if not "!ACTUAL_SIZE!"=="%VERIFY_SIZE%" (
  echo [ERROR] Size mismatch for %VERIFY_PATH%: !ACTUAL_SIZE! bytes, expected %VERIFY_SIZE%.
  exit /b 1
)

certutil.exe -hashfile "%VERIFY_PATH%" SHA256 | findstr.exe /i /x /c:"%VERIFY_SHA%" >nul
if errorlevel 1 (
  echo [ERROR] SHA-256 mismatch for %VERIFY_PATH%.
  exit /b 1
)
exit /b 0
