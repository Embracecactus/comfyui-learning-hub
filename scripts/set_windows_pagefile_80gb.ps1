$ErrorActionPreference = "Stop"

$targetMb = 81920
$pagefilePath = "C:\pagefile.sys"

$systemDrive = Get-Volume -DriveLetter C
$requiredFreeBytes = ($targetMb + 30000) * 1MB
if ($systemDrive.SizeRemaining -lt $requiredFreeBytes) {
    throw "Not enough free disk space to create an 80 GiB pagefile and keep a 30 GB safety margin."
}

$computerSystem = Get-CimInstance Win32_ComputerSystem
Set-CimInstance -InputObject $computerSystem -Property @{ AutomaticManagedPagefile = $false } | Out-Null

$pagefile = Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq $pagefilePath }

if ($null -eq $pagefile) {
    New-CimInstance -ClassName Win32_PageFileSetting -Property @{
        Name = $pagefilePath
        InitialSize = $targetMb
        MaximumSize = $targetMb
    } | Out-Null
} else {
    Set-CimInstance -InputObject $pagefile -Property @{
        InitialSize = $targetMb
        MaximumSize = $targetMb
    } | Out-Null
}

Write-Host "Configured C:\pagefile.sys to 81920 MB. Reboot Windows before running MiniMax H3."
