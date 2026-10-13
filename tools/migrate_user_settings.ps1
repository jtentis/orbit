param(
    [Parameter(Mandatory)][string]$SourceDirectory,
    [Parameter(Mandatory)][string]$ReportPath,
    [switch]$InspectOnly
)
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $SourceDirectory).Path
$targetPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Orbit'
$allowedFiles = @('config.json', 'identity.dpapi', 'local-lamp.dpapi', 'smartthings-lamp.dpapi')
$report = @{ Target = $targetPath; Imported = @(); CredentialHashesMatch = $true }
try {
    if (-not $InspectOnly) {
        if ([System.IO.Path]::GetFullPath($sourcePath) -eq [System.IO.Path]::GetFullPath($targetPath)) {
            throw 'A origem e o destino são iguais.'
        }
        $sourceConfig = Join-Path $sourcePath 'config.json'
        $null = Get-Content -LiteralPath $sourceConfig -Raw | ConvertFrom-Json
        New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        $backupPath = Join-Path $targetPath ('before-import-' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
        New-Item -ItemType Directory -Path $backupPath | Out-Null
        foreach ($name in $allowedFiles) {
            $fromPath = Join-Path $sourcePath $name
            if (-not (Test-Path -LiteralPath $fromPath)) { continue }
            $toPath = Join-Path $targetPath $name
            if (Test-Path -LiteralPath $toPath) {
                Copy-Item -LiteralPath $toPath -Destination (Join-Path $backupPath $name)
            }
            Copy-Item -LiteralPath $fromPath -Destination $toPath -Force
            if ((Get-FileHash -LiteralPath $fromPath).Hash -ne (Get-FileHash -LiteralPath $toPath).Hash) {
                throw 'A cópia não corresponde ao arquivo original.'
            }
            $report.Imported += $name
        }
    }
    $nativeConfigPath = Join-Path $targetPath 'config.json'
    $nativeConfig = if (Test-Path -LiteralPath $nativeConfigPath) {
        Get-Content -LiteralPath $nativeConfigPath -Raw | ConvertFrom-Json
    } else { $null }
    $report.LampProvider = $nativeConfig.lamp.provider
    $report.LampHost = $nativeConfig.lamp.host
    $report.ProtectedKeyPresent = Test-Path -LiteralPath (Join-Path $targetPath 'local-lamp.dpapi')
    $logPath = Join-Path $targetPath 'orbit.log'
    if (Test-Path -LiteralPath $logPath) {
        try {
            $stream = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
            try {
                $report.StartupLog = @(($reader.ReadToEnd() -split '[\r\n]+') | Select-Object -Last 150 | Where-Object { $_ -match '\[startup\]|Conexão.*estabelecida' })
            } finally { $reader.Dispose(); $stream.Dispose() }
        } catch { $report.LogUnavailable = $true }
    }
    $report.Success = $true
} catch {
    $report.Success = $false
    $report.Error = $_.Exception.Message
    throw
} finally {
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReportPath -Encoding utf8
}
