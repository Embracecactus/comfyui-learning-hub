param(
    [string]$InstanceName = "ComfyUI-RTX5060",
    [string]$ExtraModelsConfig = "",
    [double]$ReserveVramGiB = 1.0,
    [double]$DynamicVramHeadroomGiB = 0.5,
    [switch]$KeepExisting
)

$ErrorActionPreference = "Stop"

$installRoot = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Installs\$InstanceName"
$comfyRoot = Join-Path $installRoot "ComfyUI"
$python = Join-Path $comfyRoot ".venv\Scripts\python.exe"
$sharedRoot = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Shared"
$stderrLog = Join-Path $comfyRoot "user\comfyui-h3-dynamic.stderr.log"
$stdoutLog = Join-Path $comfyRoot "user\comfyui-h3-dynamic.stdout.log"

foreach ($requiredPath in @($comfyRoot, $python, $sharedRoot)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Required ComfyUI path does not exist: $requiredPath"
    }
}

if ([string]::IsNullOrWhiteSpace($ExtraModelsConfig)) {
    $modelPathDirectory = Join-Path $env:APPDATA "Comfy Desktop\instance-model-paths"
    $modelPathFiles = @(Get-ChildItem -Path $modelPathDirectory -Filter "*.yaml" -File -ErrorAction SilentlyContinue)
    if ($modelPathFiles.Count -eq 1) {
        $ExtraModelsConfig = $modelPathFiles[0].FullName
    }
    else {
        $sharedModels = Join-Path $sharedRoot "models"
        $sharedModelsForward = $sharedModels.Replace("\", "/")
        $matchingFiles = @($modelPathFiles | Where-Object {
            $contents = Get-Content -Path $_.FullName -Raw
            $contents.Contains($sharedModels) -or $contents.Contains($sharedModelsForward)
        })
        if ($matchingFiles.Count -eq 1) {
            $ExtraModelsConfig = $matchingFiles[0].FullName
        }
        else {
            throw "Could not uniquely find the Desktop model-path YAML. Pass -ExtraModelsConfig with its full path."
        }
    }
}

if (-not (Test-Path $ExtraModelsConfig)) {
    throw "Desktop model-path YAML does not exist: $ExtraModelsConfig"
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

if (-not $KeepExisting -or $null -eq $existingProcess) {
    $listener = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        throw "Port 8188 is already used by PID $($listener.OwningProcess): $($owner.CommandLine)"
    }
}

if ($KeepExisting -and $null -ne $existingProcess) {
    Write-Host "Keeping existing ComfyUI process $($existingProcess.ProcessId)"
    $process = $null
}
else {
    # Important for a BF16 Qwen3-VL-32B encoder on 32 GB RAM:
    # - DynamicVRAM + fast-disk keeps safetensors as disk-backed TensorFileSlice objects.
    # - Do not add --novram, --disable-dynamic-vram, or --disable-mmap here. Those
    #   flags bypass the disk-backed loader and make the 48 GiB encoder eager-load.
    # - Keep the VAE on DynamicVRAM. --cpu-vae selects FP32 inputs on CPU while
    #   the file-backed H3 video VAE remains FP16, which causes a dtype mismatch.
    # - Async offload and pinned memory stay disabled because Windows/Blackwell H3
    #   VAE runs have a confirmed native-crash path when either host path is active.
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
        "--fast-disk",
        "--disable-smart-memory",
        "--reserve-vram",
        $ReserveVramGiB.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--vram-headroom",
        $DynamicVramHeadroomGiB.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--disable-async-offload",
        "--disable-pinned-memory",
        "--preview-method",
        "none"
    )

    Remove-Item $stderrLog, $stdoutLog -Force -ErrorAction SilentlyContinue
    $startParameters = @{
        FilePath = $python
        ArgumentList = $arguments
        WorkingDirectory = $comfyRoot
        RedirectStandardError = $stderrLog
        RedirectStandardOutput = $stdoutLog
        PassThru = $true
    }
    $process = Start-Process @startParameters
}

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $serverProcess = Get-ComfyServerProcess
        if ($null -eq $serverProcess) {
            throw "The expected ComfyUI main.py process is not running."
        }
        if ($serverProcess.CommandLine -notmatch "--enable-dynamic-vram" -or $serverProcess.CommandLine -notmatch "--fast-disk") {
            throw "The ComfyUI process exists, but its command line does not use the H3 DynamicVRAM profile."
        }
        $stats = Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 2
        $argv = @($stats.system.argv)
        if ($argv -notcontains "--enable-dynamic-vram" -or $argv -notcontains "--fast-disk") {
            throw "ComfyUI responded, but the DynamicVRAM fast-disk profile is not active."
        }
        # Desktop's venv launcher can hand off to standalone-env and exit. Find
        # the actual main.py child instead of treating the launcher exit as a
        # failed startup.
        $serverPid = $serverProcess.ProcessId
        Write-Host "ComfyUI H3 profile is ready. PID=$serverPid URL=http://127.0.0.1:8188"
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
