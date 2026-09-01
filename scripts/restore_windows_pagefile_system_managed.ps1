#requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$computerSystem = Get-CimInstance Win32_ComputerSystem
Set-CimInstance -InputObject $computerSystem -Property @{
    AutomaticManagedPagefile = $true
} | Out-Null

$updated = Get-CimInstance Win32_ComputerSystem
if (-not $updated.AutomaticManagedPagefile) {
    throw "Windows did not enable AutomaticManagedPagefile."
}

Write-Output "AutomaticManagedPagefile=True"
Write-Output "Restart Windows to replace the current fixed pagefile allocation."
