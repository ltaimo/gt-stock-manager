param(
    [string]$Root = "",
    [string]$TargetUrl = "",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"

if (-not $Root) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if ((Test-Path -LiteralPath (Join-Path $ScriptDir "app_project")) -or (Test-Path -LiteralPath (Join-Path $ScriptDir "app"))) {
        $Root = $ScriptDir
    } elseif ((Test-Path -LiteralPath (Join-Path $ScriptDir "..\app_project")) -or (Test-Path -LiteralPath (Join-Path $ScriptDir "..\app"))) {
        $Root = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
    } else {
        $Root = $ScriptDir
    }
}

$ProjectRoot = if (Test-Path -LiteralPath (Join-Path $Root "app_project")) { Join-Path $Root "app_project" } else { $Root }
$PythonExe = if (Test-Path -LiteralPath (Join-Path $Root "runtime\python\python.exe")) {
    Join-Path $Root "runtime\python\python.exe"
} elseif (Test-Path -LiteralPath (Join-Path $Root ".venv\Scripts\python.exe")) {
    Join-Path $Root ".venv\Scripts\python.exe"
} else {
    "python"
}

function Load-EnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

foreach ($envName in @(".env.portable", ".env.native", ".env.lan", ".env")) {
    Load-EnvFile -Path (Join-Path $Root $envName)
}

if ((Test-Path -LiteralPath (Join-Path $Root "app_project")) -and -not $env:DATABASE_URL) {
    $dbPath = Join-Path $Root "dados_locais\stock_manager.db"
    $env:DATABASE_URL = "sqlite:///$($dbPath.Replace('\','/'))"
    $env:ENVIRONMENT = "portable"
}

if ($TargetUrl) {
    $env:SYNC_TARGET_URL = $TargetUrl
}
if ($Token) {
    $env:SYNC_TOKEN = $Token
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m app.maintenance.push_remote_mirror
} finally {
    Pop-Location
}
