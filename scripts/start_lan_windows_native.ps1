param(
    [string]$ServerIp = "192.168.1.6",
    [int]$Port = 0,
    [switch]$CheckOnly,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$EnvFile = Join-Path $Root ".env.native"
$EnvExample = Join-Path $Root ".env.native.example"
$Venv = Join-Path $Root ".venv-native"
$PythonExe = Join-Path $Venv "Scripts\python.exe"
$DataRoot = Join-Path $Root "server-data\native"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Yellow
}

function Find-Python {
    $candidates = @(
        "py -3.12",
        "py -3.11",
        "py -3",
        "python"
    )
    foreach ($candidate in $candidates) {
        try {
            $version = Invoke-Expression "$candidate --version 2>&1"
            if ($LASTEXITCODE -eq 0 -and $version -match "Python 3") {
                return $candidate
            }
        } catch {
        }
    }
    return $null
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
        if ($parts.Count -ne 2) {
            return
        }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

function Is-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host "GTIMS - arranque nativo Windows para rede local" -ForegroundColor Cyan
Write-Host "Endereco esperado: http://${ServerIp}:8000"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (Test-Path -LiteralPath $EnvExample) {
        Copy-Item -LiteralPath $EnvExample -Destination $EnvFile -Force
    }
    Write-Host ""
    Write-Host "Criei .env.native. Edite esse ficheiro antes de continuar:" -ForegroundColor Yellow
    Write-Host $EnvFile
    Write-Host ""
    Write-Host "Depois volte a executar este script."
    exit 1
}

Load-EnvFile -Path $EnvFile

if ($Port -le 0) {
    $Port = if ($env:GTIMS_PORT) { [int]$env:GTIMS_PORT } else { 8000 }
}

Write-Section "Python"
$PythonCommand = Find-Python
if (-not $PythonCommand) {
    Write-Host "Python 3 nao foi encontrado." -ForegroundColor Red
    Write-Host "Instale Python 3.12 manualmente em https://www.python.org/downloads/windows/"
    Write-Host "Durante a instalacao, marque Add python.exe to PATH."
    exit 1
}
Write-Host "Python encontrado: $PythonCommand" -ForegroundColor Green

if ($CheckOnly) {
    Write-Section "Check only"
    Write-Host "Pre-verificacao concluida. O script nao iniciou o sistema por causa de -CheckOnly."
    exit 0
}

if ($OpenFirewall) {
    Write-Section "Firewall"
    if (Is-Administrator) {
        $ruleName = "GTIMS Web $Port"
        $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if (-not $existingRule) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private | Out-Null
            Write-Host "Regra de firewall criada: $ruleName" -ForegroundColor Green
        } else {
            Write-Host "Regra de firewall ja existe: $ruleName" -ForegroundColor Green
        }
    } else {
        Write-Host "Para abrir firewall automaticamente, execute PowerShell como Administrador." -ForegroundColor Yellow
    }
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "uploads") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "outputs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "uploads\stock_documents") | Out-Null

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Section "Criar ambiente Python"
    Invoke-Expression "$PythonCommand -m venv `"$Venv`""
}

Write-Section "Instalar dependencias"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $Root "requirements.txt")

$DbPath = Join-Path $DataRoot "stock_manager.db"
$ConfiguredDatabaseUrl = $env:DATABASE_URL
$UsingExternalDatabase = -not [string]::IsNullOrWhiteSpace($ConfiguredDatabaseUrl)
if ($UsingExternalDatabase) {
    $env:DATABASE_URL = $ConfiguredDatabaseUrl.Trim()
} else {
    $env:DATABASE_URL = "sqlite:///$($DbPath.Replace('\','/'))"
}
$env:ENVIRONMENT = "lan_native"
$env:SESSION_COOKIE_SECURE = "false"
$env:UPLOADS_DIR = (Join-Path $DataRoot "uploads")
$env:OUTPUTS_DIR = (Join-Path $DataRoot "outputs")
$env:DOCUMENTS_DIR = (Join-Path $DataRoot "uploads\stock_documents")
$env:EMAIL_OUTBOX_DIR = (Join-Path $DataRoot "outputs\email_outbox")
$env:WHATSAPP_OUTBOX_DIR = (Join-Path $DataRoot "outputs\whatsapp_outbox")
$env:LOGO_PATH = (Join-Path $Root "app\static\img\logo-gt.png")

$needsSeed = (-not $UsingExternalDatabase) -and (-not (Test-Path -LiteralPath $DbPath))
if ($needsSeed) {
    if (-not $env:INITIAL_SUPERADMIN_PASSWORD -or $env:INITIAL_SUPERADMIN_PASSWORD.Length -lt 12) {
        Write-Host "INITIAL_SUPERADMIN_PASSWORD precisa ter pelo menos 12 caracteres no .env.native." -ForegroundColor Red
        exit 1
    }
    Write-Section "Criar base inicial"
    Push-Location $Root
    try {
        & $PythonExe -m app.seed
    } finally {
        Pop-Location
    }
}

if ($UsingExternalDatabase) {
    Write-Section "Base de dados"
    Write-Host "A usar DATABASE_URL configurada no .env.native." -ForegroundColor Green
    Write-Host "Nao sera criado seed automatico para evitar alterar uma base online existente."
}

Write-Section "Migrar esquema"
Push-Location $Root
try {
    & $PythonExe -m app.maintenance.migrate_schema
} finally {
    Pop-Location
}

Write-Section "Iniciar GTIMS"
Write-Host "Servidor local: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Rede interna:   http://${ServerIp}:$Port" -ForegroundColor Green
Write-Host "Para parar, pressione CTRL+C."

Push-Location $Root
try {
    & $PythonExe -m uvicorn app.main:app --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
}
