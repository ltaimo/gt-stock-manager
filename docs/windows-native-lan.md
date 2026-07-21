# GTIMS em modo Windows nativo

Este modo e uma alternativa quando o computador-servidor nao tem Docker Desktop, nao tem `winget`, ou nao suporta Docker.

## Quando usar

Use apenas como fase temporaria ou piloto local. Para uso real definitivo, Docker/PostgreSQL continua recomendado.

O modo nativo usa:

- Python 3.
- Ambiente virtual `.venv-native`.
- SQLite em `server-data\native\stock_manager.db`, salvo configuracao diferente.
- Uvicorn exposto em `0.0.0.0`.

## 1. Instalar Python manualmente

No servidor, abrir:

```text
https://www.python.org/downloads/windows/
```

Instalar Python 3.12 ou 3.11.

Durante a instalacao, marcar:

```text
Add python.exe to PATH
```

Depois fechar e abrir novamente o PowerShell.

Confirmar:

```powershell
python --version
```

## 2. Configurar o GTIMS

Na pasta do sistema:

```powershell
Copy-Item .env.native.example .env.native
notepad .env.native
```

Alterar obrigatoriamente:

```text
SECRET_KEY=
RESET_STOCK_SECURITY_CODE=
INITIAL_SUPERADMIN_PASSWORD=
```

## 3. Abrir firewall

PowerShell como Administrador:

```powershell
New-NetFirewallRule -DisplayName "GTIMS Web 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private
```

## 4. Iniciar

Na pasta do sistema:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_lan_windows_native.ps1 -ServerIp 192.168.1.6
```

Ou, para tentar abrir firewall no mesmo comando:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_lan_windows_native.ps1 -ServerIp 192.168.1.6 -OpenFirewall
```

## 5. Aceder

No servidor:

```text
http://127.0.0.1:8000
```

Noutra maquina da rede:

```text
http://192.168.1.6:8000
```

## 6. Limites deste modo

- Nao e tao robusto quanto PostgreSQL para muitos utilizadores simultaneos.
- A janela PowerShell deve ficar aberta, a menos que seja configurado como servico.
- Fazer backup regular de `server-data\native`.

## 7. Backup rapido

```powershell
New-Item -ItemType Directory -Force backups
Compress-Archive -Path server-data\native -DestinationPath backups\gtims-native-backup.zip -Force
```
