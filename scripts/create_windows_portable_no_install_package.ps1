param(
    [string]$OutputDir = "outputs\packages",
    [string]$ServerIp = "192.168.1.6",
    [string]$PythonHome = "",
    [switch]$KeepStage
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim()
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$PackageName = "GTIMS_Portable_NoInstall_v$Version-$Stamp"
$ResolvedOutput = Join-Path $Root $OutputDir
$StageRoot = Join-Path $ResolvedOutput "_stage_$PackageName"
$ZipPath = Join-Path $ResolvedOutput "$PackageName.zip"

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

if (-not $PythonHome) {
    $VenvConfig = Join-Path $Root ".venv\pyvenv.cfg"
    if (Test-Path -LiteralPath $VenvConfig) {
        $homeLine = Get-Content -LiteralPath $VenvConfig | Where-Object { $_ -like "home = *" } | Select-Object -First 1
        if ($homeLine) {
            $PythonHome = $homeLine.Substring("home = ".Length).Trim()
        }
    }
}

if (-not $PythonHome -or -not (Test-Path -LiteralPath (Join-Path $PythonHome "python.exe"))) {
    throw "PythonHome invalido. Informe -PythonHome com uma instalacao Python 3.12/3.11 existente."
}

$SitePackages = Join-Path $Root ".venv\Lib\site-packages"
if (-not (Test-Path -LiteralPath $SitePackages)) {
    throw "Dependencias nao encontradas em $SitePackages. Recrie .venv e instale requirements.txt."
}

function Copy-Tree {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            if ($ExcludeDirs -contains $_.Name) {
                return
            }
            Copy-Tree -Source $_.FullName -Destination (Join-Path $Destination $_.Name) -ExcludeDirs $ExcludeDirs -ExcludeFiles $ExcludeFiles
            return
        }

        if ($ExcludeFiles -contains $_.Name) {
            return
        }

        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $_.Name) -Force
    }
}

New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null

if (Test-Path -LiteralPath $StageRoot) {
    $ResolvedStage = (Resolve-Path -LiteralPath $StageRoot).Path
    $ResolvedBase = (Resolve-Path -LiteralPath $ResolvedOutput).Path
    if (-not $ResolvedStage.StartsWith($ResolvedBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Stage path is outside the output directory: $ResolvedStage"
    }
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}

$ProjectStage = Join-Path $StageRoot "app_project"
$RuntimeStage = Join-Path $StageRoot "runtime\python"
$RuntimeSitePackages = Join-Path $RuntimeStage "Lib\site-packages"

New-Item -ItemType Directory -Force -Path $ProjectStage | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeStage | Out-Null

Copy-Tree -Source (Join-Path $Root "app") -Destination (Join-Path $ProjectStage "app") -ExcludeDirs @("__pycache__")
Copy-Tree -Source (Join-Path $Root "docs") -Destination (Join-Path $ProjectStage "docs") -ExcludeDirs @("__pycache__")
Copy-Item -LiteralPath (Join-Path $Root "requirements.txt") -Destination (Join-Path $ProjectStage "requirements.txt") -Force
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination (Join-Path $ProjectStage "README.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "CHANGELOG.md") -Destination (Join-Path $ProjectStage "CHANGELOG.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "VERSION") -Destination (Join-Path $ProjectStage "VERSION") -Force

Copy-Tree -Source $PythonHome -Destination $RuntimeStage -ExcludeDirs @("__pycache__") -ExcludeFiles @()
Copy-Tree -Source $SitePackages -Destination $RuntimeSitePackages -ExcludeDirs @("__pycache__", "pip", "pip-26.1.2.dist-info", "setuptools", "setuptools-*.dist-info") -ExcludeFiles @()

Copy-Item -LiteralPath (Join-Path $Root "scripts\run_portable_no_install.ps1") -Destination (Join-Path $StageRoot "run_portable_no_install.ps1") -Force
Copy-Item -LiteralPath (Join-Path $Root "scripts\sync_to_render_once.ps1") -Destination (Join-Path $StageRoot "sync_to_render_once.ps1") -Force
Copy-Item -LiteralPath (Join-Path $Root "scripts\pull_online_to_local_once.ps1") -Destination (Join-Path $StageRoot "pull_online_to_local_once.ps1") -Force

@"
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_portable_no_install.ps1" -ServerIp $ServerIp
pause
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "Iniciar_GTIMS_Portable.bat") -Encoding ASCII

@"
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_portable_no_install.ps1" -ServerIp $ServerIp -OpenFirewall
pause
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "Iniciar_GTIMS_Portable_Como_Admin_Abrir_Firewall.bat") -Encoding ASCII

@"
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_to_render_once.ps1"
pause
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "Sincronizar_Render_Agora.bat") -Encoding ASCII

@"
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0pull_online_to_local_once.ps1"
pause
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "Testar_Puxar_Dados_Online.bat") -Encoding ASCII

@"
@echo off
setlocal
cd /d "%~dp0"
echo ATENCAO: isto substitui a base local pelos dados online.
echo Use apenas no bootstrap inicial, antes de usar o local como principal.
pause
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0pull_online_to_local_once.ps1" -Apply
pause
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "IMPORTAR_DADOS_ONLINE_PARA_LOCAL_CUIDADO.bat") -Encoding ASCII

@"
APP_NAME=GT Integrated Management System
APP_SUBTITLE=Gestao de Terminais, SA
APP_SHORT_NAME=GTIMS
APP_VERSION=$Version
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

# Sincronizacao local principal -> Render mirror.
# No servidor local principal:
#   SYNC_MODE=primary
#   SYNC_AUTO_PUSH=true
#   SYNC_TARGET_URL=https://URL-DO-RENDER
#   SYNC_TOKEN=mesmo-token-configurado-no-render
# No Render mirror:
#   SYNC_MODE=mirror
#   SYNC_TOKEN=mesmo-token
#   MIRROR_READ_ONLY=true
SYNC_MODE=off
SYNC_AUTO_PUSH=false
SYNC_TARGET_URL=
SYNC_TOKEN=
SYNC_INTERVAL_SECONDS=300
MIRROR_READ_ONLY=true
"@ | Set-Content -LiteralPath (Join-Path $StageRoot ".env.portable.example") -Encoding UTF8

@"
GTIMS Portable - Sem instalacao
===============================

Como usar no servidor 192.168.1.6:

1. Extraia esta pasta para C:\GTIMS.
2. Abra a pasta C:\GTIMS.
3. De duplo clique em:

   Iniciar_GTIMS_Portable.bat

4. No primeiro arranque, a base local sera criada em:

   dados_locais\stock_manager.db

5. O acesso na rede sera:

   http://${ServerIp}:8000

Login inicial:

   utilizador: superadmin
   senha: Admin@12345GT

Depois do primeiro login, altere a senha do superadmin.

Firewall:

Se outros computadores nao conseguirem abrir http://${ServerIp}:8000,
execute como Administrador:

   Iniciar_GTIMS_Portable_Como_Admin_Abrir_Firewall.bat

Ou abra manualmente a porta:

   New-NetFirewallRule -DisplayName "GTIMS Portable Web 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private

Backup:

Copie regularmente a pasta:

   dados_locais

Notas:

- Nao precisa instalar Docker, Python, PostgreSQL ou winget.
- A janela deve ficar aberta enquanto o sistema estiver em uso.
- Este modo usa SQLite local. E adequado para piloto/local temporario.
- Para operacao definitiva com muitos utilizadores, migrar depois para PostgreSQL.
- Para usar os mesmos dados do Render/Supabase, edite .env.portable e coloque a mesma DATABASE_URL online.
- Nao use ao mesmo tempo duas bases diferentes para trabalho real, porque movimentos e aprovacoes podem divergir.

Modelo local principal + Render mirror:

1. Configurar no Render:
   SYNC_MODE=mirror
   MIRROR_READ_ONLY=true
   SYNC_TOKEN=um-token-forte

2. Configurar no local:
   SYNC_MODE=primary
   SYNC_AUTO_PUSH=true
   SYNC_TARGET_URL=https://URL-DO-RENDER
   SYNC_TOKEN=o-mesmo-token

3. Antes de usar o local como principal, importar dados online para local:
   Testar_Puxar_Dados_Online.bat
   IMPORTAR_DADOS_ONLINE_PARA_LOCAL_CUIDADO.bat

4. Depois usar o local como fonte principal.
"@ | Set-Content -LiteralPath (Join-Path $StageRoot "LEIA-ME_PORTABLE_SEM_INSTALACAO.txt") -Encoding UTF8

$TestEnv = @{
    PYTHONPATH = ""
}
& (Join-Path $RuntimeStage "python.exe") -c "import fastapi, uvicorn, sqlalchemy, jinja2, reportlab, openpyxl, psycopg; print('portable runtime ok')"
Push-Location $ProjectStage
try {
    & (Join-Path $RuntimeStage "python.exe") -m compileall -q app
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -Force
$Hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256

if (-not $KeepStage) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}

Write-Host "Pacote portable criado:" -ForegroundColor Green
Write-Host $ZipPath
Write-Host "SHA256: $($Hash.Hash)"
