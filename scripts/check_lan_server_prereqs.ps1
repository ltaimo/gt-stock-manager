param(
    [string]$ServerIp = "192.168.1.6",
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Yellow
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "GTIMS - Pre-verificacao do servidor local" -ForegroundColor Cyan
Write-Host "Servidor esperado: http://${ServerIp}:$Port"

Write-Section "Docker"
if (-not (Test-Command "docker")) {
    Write-Host "Docker nao foi encontrado neste terminal." -ForegroundColor Red
    Write-Host ""
    Write-Host "Instale Docker Desktop no computador-servidor. Se winget estiver disponivel, use:"
    Write-Host ""
    Write-Host "winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements" -ForegroundColor Green
    Write-Host ""
    Write-Host "Depois da instalacao:"
    Write-Host "1. Reinicie o computador ou termine sessao e volte a entrar."
    Write-Host "2. Abra Docker Desktop."
    Write-Host "3. Aguarde ate aparecer que Docker esta a correr."
    Write-Host "4. Abra um novo PowerShell e teste: docker --version"
    exit 1
}

$DockerVersion = docker --version
Write-Host "Docker encontrado: $DockerVersion" -ForegroundColor Green

try {
    $ComposeVersion = docker compose version
    Write-Host "Docker Compose encontrado: $ComposeVersion" -ForegroundColor Green
} catch {
    Write-Host "Docker Compose nao respondeu corretamente." -ForegroundColor Red
    Write-Host "Atualize/reinstale Docker Desktop e volte a tentar."
    exit 1
}

Write-Section "Firewall"
try {
    $Rule = Get-NetFirewallRule -DisplayName "GTIMS Web $Port" -ErrorAction SilentlyContinue
    if ($Rule) {
        Write-Host "Regra de firewall encontrada: GTIMS Web $Port" -ForegroundColor Green
    } else {
        Write-Host "Regra de firewall ainda nao encontrada." -ForegroundColor Yellow
        Write-Host "Para criar, abra PowerShell como Administrador e execute:"
        Write-Host ""
        Write-Host "New-NetFirewallRule -DisplayName `"GTIMS Web $Port`" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private" -ForegroundColor Green
    }
} catch {
    Write-Host "Nao foi possivel verificar firewall neste terminal." -ForegroundColor Yellow
}

Write-Section "Rede"
Write-Host "Quando o sistema estiver ligado, teste noutro computador:"
Write-Host "http://${ServerIp}:$Port" -ForegroundColor Green

Write-Section "Proximo comando"
Write-Host "Se Docker estiver a correr e .env.lan ja estiver configurado, execute:"
Write-Host ""
Write-Host "docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build" -ForegroundColor Green
