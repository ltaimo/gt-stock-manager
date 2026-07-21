param(
    [string]$OutputDir = "outputs\packages"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim()
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$PackageName = "GTIMS_LAN_Server_v$Version-$Stamp"
$ResolvedOutput = Join-Path $Root $OutputDir
$StageRoot = Join-Path $ResolvedOutput "_stage_$PackageName"
$ZipPath = Join-Path $ResolvedOutput "$PackageName.zip"

$ExcludedDirs = @(
    ".git",
    ".agents",
    ".codex",
    ".venv",
    ".pytest_cache",
    "outputs",
    "uploads",
    "tmp",
    "portable",
    "__pycache__"
)

$ExcludedFiles = @(
    ".env",
    ".env.lan",
    "stock_manager.db"
)

function Copy-CleanTree {
    param(
        [string]$Source,
        [string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            if ($ExcludedDirs -contains $_.Name) {
                return
            }
            Copy-CleanTree -Source $_.FullName -Destination (Join-Path $Destination $_.Name)
            return
        }

        if ($ExcludedFiles -contains $_.Name) {
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

Copy-CleanTree -Source $Root -Destination $StageRoot

$ReadmePath = Join-Path $StageRoot "README_INSTALACAO_REDE_LOCAL.txt"
@"
GTIMS - Pacote para servidor local de rede
=========================================

1. Copie esta pasta para o computador-servidor.
2. Instale Docker Desktop se ainda nao estiver instalado.
3. Se o comando docker nao for reconhecido, instale Docker Desktop manualmente
   pelo browser:

   https://docs.docker.com/desktop/setup/install/windows-install/

   Ou, se winget existir, instale com:

   winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements

   Depois reinicie o computador, abra Docker Desktop e teste:

   docker --version
   docker compose version

4. Opcionalmente, execute a pre-verificacao:

   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_lan_server_prereqs.ps1

5. Copie .env.lan.example para .env.lan.
6. Edite .env.lan e troque todas as senhas/segredos.
7. Execute:

   docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build

8. Na primeira instalacao, crie o superadmin:

   docker compose -f docker-compose.lan.yml --env-file .env.lan exec web python -m app.seed

9. Aceda no browser:

   http://IP_DO_SERVIDOR:8000

Guia completo:

   docs\local-network-server.md

Se Docker Desktop nao for possivel nesta maquina:

   docs\windows-native-lan.md
"@ | Set-Content -LiteralPath $ReadmePath -Encoding UTF8

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -Force
$Hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
Remove-Item -LiteralPath $StageRoot -Recurse -Force

Write-Host "Pacote criado:" -ForegroundColor Green
Write-Host $ZipPath
Write-Host "SHA256: $($Hash.Hash)"
