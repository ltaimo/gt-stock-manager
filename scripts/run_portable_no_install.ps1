param(
    [string]$ServerIp = "192.168.1.6",
    [int]$Port = 0,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Join-Path $Root "app_project"
$PythonExe = Join-Path $Root "runtime\python\python.exe"
$DataRoot = Join-Path $Root "dados_locais"
$EnvFile = Join-Path $Root ".env.portable"
$EnvExample = Join-Path $Root ".env.portable.example"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Yellow
}

function New-RandomToken {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($buffer)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($buffer)
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

Write-Host "GTIMS Portable - sem instalacao" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Runtime Python nao encontrado em $PythonExe"
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (Test-Path -LiteralPath $EnvExample) {
        Copy-Item -LiteralPath $EnvExample -Destination $EnvFile -Force
    } else {
        @"
APP_NAME=GT Integrated Management System
APP_SUBTITLE=Gestao de Terminais, SA
APP_SHORT_NAME=GTIMS
APP_VERSION=3.0.0
GTIMS_PORT=8000
SECRET_KEY=$(New-RandomToken)
RESET_STOCK_SECURITY_CODE=$(New-RandomToken -Bytes 12)
INITIAL_SUPERADMIN_PASSWORD=Admin@12345GT
DEFAULT_LANGUAGE=pt
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=stock@gtsa.local
WHATSAPP_WEBHOOK_URL=
WHATSAPP_SENDER=+258844231830

# Deixe vazio para usar a base SQLite local em dados_locais.
# Para usar os mesmos dados do Render/Supabase, coloque aqui a mesma DATABASE_URL online.
DATABASE_URL=
"@ | Set-Content -LiteralPath $EnvFile -Encoding UTF8
    }
    Write-Host "Ficheiro .env.portable criado. Pode editar senhas e chaves em:" -ForegroundColor Yellow
    Write-Host $EnvFile
}

Load-EnvFile -Path $EnvFile

if ($Port -le 0) {
    $Port = if ($env:GTIMS_PORT) { [int]$env:GTIMS_PORT } else { 8000 }
}

if ($OpenFirewall) {
    Write-Section "Firewall"
    if (Is-Administrator) {
        $ruleName = "GTIMS Portable Web $Port"
        $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if (-not $existingRule) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private | Out-Null
            Write-Host "Regra de firewall criada: $ruleName" -ForegroundColor Green
        } else {
            Write-Host "Regra de firewall ja existe: $ruleName" -ForegroundColor Green
        }
    } else {
        Write-Host "Para abrir firewall automaticamente, execute como Administrador." -ForegroundColor Yellow
    }
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "uploads") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "outputs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "uploads\stock_documents") | Out-Null

$DbPath = Join-Path $DataRoot "stock_manager.db"
$ConfiguredDatabaseUrl = $env:DATABASE_URL
$UsingExternalDatabase = -not [string]::IsNullOrWhiteSpace($ConfiguredDatabaseUrl)
$env:ENVIRONMENT = "portable"
$env:SESSION_COOKIE_SECURE = "false"
if ($UsingExternalDatabase) {
    $env:DATABASE_URL = $ConfiguredDatabaseUrl.Trim()
} else {
    $env:DATABASE_URL = "sqlite:///$($DbPath.Replace('\','/'))"
}
$env:UPLOADS_DIR = (Join-Path $DataRoot "uploads")
$env:OUTPUTS_DIR = (Join-Path $DataRoot "outputs")
$env:DOCUMENTS_DIR = (Join-Path $DataRoot "uploads\stock_documents")
$env:EMAIL_OUTBOX_DIR = (Join-Path $DataRoot "outputs\email_outbox")
$env:WHATSAPP_OUTBOX_DIR = (Join-Path $DataRoot "outputs\whatsapp_outbox")
$env:LOGO_PATH = (Join-Path $ProjectRoot "app\static\img\logo-gt.png")

$needsSeed = (-not $UsingExternalDatabase) -and (-not (Test-Path -LiteralPath $DbPath))
Push-Location $ProjectRoot
try {
    if ($UsingExternalDatabase) {
        Write-Section "Base de dados"
        Write-Host "A usar DATABASE_URL configurada no .env.portable." -ForegroundColor Green
        Write-Host "O sistema local e o online podem ver os mesmos registos se ambos apontarem para essa mesma base."
        Write-Host "Nao sera criado seed automatico para evitar alterar uma base online existente."
    }

    if ($needsSeed) {
        if (-not $env:INITIAL_SUPERADMIN_PASSWORD -or $env:INITIAL_SUPERADMIN_PASSWORD.Length -lt 12) {
            throw "INITIAL_SUPERADMIN_PASSWORD precisa ter pelo menos 12 caracteres no .env.portable."
        }
        Write-Section "Criar base inicial"
        & $PythonExe -m app.seed
    }

    Write-Section "Migrar esquema"
    & $PythonExe -m app.maintenance.migrate_schema

    Write-Section "Iniciar GTIMS"
    Write-Host "Neste computador: http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host "Na rede local:    http://${ServerIp}:$Port" -ForegroundColor Green
    Write-Host ""
    Write-Host "Login inicial, se a base foi criada agora:"
    Write-Host "  utilizador: superadmin"
    Write-Host "  senha: valor em INITIAL_SUPERADMIN_PASSWORD no .env.portable"
    Write-Host ""
    Write-Host "Para parar o sistema, pressione CTRL+C ou feche esta janela."

    Start-Process "http://127.0.0.1:$Port"
    & $PythonExe -m uvicorn app.main:app --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
}
