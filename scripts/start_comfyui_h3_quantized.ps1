param(
    [string]$InstanceName = "",
    [string]$ExtraModelsConfig = "",
    [ValidateSet("nvfp4", "int8")]
    [string]$ModelProfile = "nvfp4",
    [ValidateSet("Auto", "RamAssisted", "DiskStreaming")]
    [string]$IoMode = "Auto",
    [ValidateSet("Stable", "SingleStream")]
    [string]$AsyncMode = "Stable",
    [double]$ReserveVramGiB = 1.0,
    [double]$DynamicVramHeadroomGiB = 0.5,
    [switch]$KeepExisting
)

$ErrorActionPreference = "Stop"

$installsRoot = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Installs"
if ([string]::IsNullOrWhiteSpace($InstanceName)) {
    $instances = @(Get-ChildItem -Path $installsRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName "ComfyUI\.venv\Scripts\python.exe") })
    if ($instances.Count -ne 1) {
        throw "Could not select one Desktop instance automatically. Pass -InstanceName with the directory name."
    }
    $InstanceName = $instances[0].Name
}

$installRoot = Join-Path $installsRoot $InstanceName
$comfyRoot = Join-Path $installRoot "ComfyUI"
$python = Join-Path $comfyRoot ".venv\Scripts\python.exe"
$sharedRoot = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Shared"
$stderrLog = Join-Path $comfyRoot "user\comfyui-h3-quantized.stderr.log"
$stdoutLog = Join-Path $comfyRoot "user\comfyui-h3-quantized.stdout.log"

foreach ($requiredPath in @($comfyRoot, $python, $sharedRoot)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Required ComfyUI path does not exist: $requiredPath"
    }
}

if ([string]::IsNullOrWhiteSpace($ExtraModelsConfig)) {
    $modelPathDirectory = Join-Path $env:APPDATA "Comfy Desktop\instance-model-paths"
    $modelPathFiles = @(Get-ChildItem -Path $modelPathDirectory -Filter "*.yaml" -File -ErrorAction SilentlyContinue)
    $sharedModels = Join-Path $sharedRoot "models"
    $sharedModelsForward = $sharedModels.Replace("\", "/")
    $matchingFiles = @($modelPathFiles | Where-Object {
        $contents = Get-Content -Path $_.FullName -Raw
        $contents.Contains($sharedModels) -or $contents.Contains($sharedModelsForward)
    })
    if ($matchingFiles.Count -ne 1) {
        throw "Could not select one Desktop model-path YAML. Pass -ExtraModelsConfig explicitly."
    }
    $ExtraModelsConfig = $matchingFiles[0].FullName
}

$physicalRamGiB = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
$availableRamGiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB / 1GB
$largestStageGiB = if ($ModelProfile -eq "nvfp4") { 19.53 } else { 25.28 }
$selectedIoMode = $IoMode
if ($IoMode -eq "Auto") {
    $selectedIoMode = if (
        $physicalRamGiB -ge ($largestStageGiB + 8.0) -and
        $availableRamGiB -ge ($largestStageGiB + 4.0)
    ) {
        "RamAssisted"
    }
    else {
        "DiskStreaming"
    }
}

$escapedRoot = [Regex]::Escape($comfyRoot)
function Get-ComfyServerProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match $escapedRoot -and $_.CommandLine -match "main\.py" } |
        Sort-Object WorkingSetSize -Descending |
        Select-Object -First 1
}

$existingProcess = Get-ComfyServerProcess
if (-not $KeepExisting -and $null -ne $existingProcess) {
    Write-Host "Stopping existing ComfyUI process $($existingProcess.ProcessId)"
    Stop-Process -Id $existingProcess.ProcessId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if ($KeepExisting -and $null -ne $existingProcess) {
    Write-Host "Keeping existing process $($existingProcess.ProcessId); no launch settings were changed."
    exit 0
}

$listener = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $listener) {
    throw "Port 8188 is already used by PID $($listener.OwningProcess)."
}

$arguments = @(
    "-s",
    "main.py",
    "--enable-manager",
    "--enable-manager-legacy-ui",
    "--extra-model-paths-config",
    "`"$ExtraModelsConfig`"",
    "--input-directory",
    "`"$(Join-Path $sharedRoot 'input')`"",
    "--output-directory",
    "`"$(Join-Path $sharedRoot 'output')`"",
    "--enable-dynamic-vram",
    "--disable-smart-memory",
    "--reserve-vram",
    $ReserveVramGiB.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--vram-headroom",
    $DynamicVramHeadroomGiB.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--disable-pinned-memory",
    "--preview-method",
    "none"
)

if ($selectedIoMode -eq "DiskStreaming") {
    $arguments += "--fast-disk"
}
if ($AsyncMode -eq "Stable") {
    $arguments += "--disable-async-offload"
}
else {
    $arguments += @("--async-offload", "1")
}

Remove-Item $stderrLog, $stdoutLog -Force -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $comfyRoot `
    -RedirectStandardError $stderrLog -RedirectStandardOutput $stdoutLog -PassThru

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $stats = Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 2
        $argv = @($stats.system.argv)
        if ($argv -notcontains "--enable-dynamic-vram") {
            throw "The responding server does not use DynamicVRAM."
        }
        if ($selectedIoMode -eq "DiskStreaming" -and $argv -notcontains "--fast-disk") {
            throw "DiskStreaming was selected but --fast-disk is missing."
        }
        if ($selectedIoMode -eq "RamAssisted" -and $argv -contains "--fast-disk") {
            throw "RamAssisted was selected but --fast-disk is still active."
        }
        Write-Host "ComfyUI H3 quantized profile is ready: http://127.0.0.1:8188"
        Write-Host ("Instance={0} ModelProfile={1} RAM={2:N1}GiB Available={3:N1}GiB IoMode={4} AsyncMode={5}" -f `
            $InstanceName, $ModelProfile, $physicalRamGiB, $availableRamGiB, $selectedIoMode, $AsyncMode)
        Write-Host "stderr: $stderrLog"
        Write-Host "stdout: $stdoutLog"
        exit 0
    }
    catch {
        if ($attempt -eq 59) {
            throw "ComfyUI did not become ready within 120 seconds. See $stderrLog"
        }
    }
}
