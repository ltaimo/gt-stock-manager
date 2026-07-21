# GTIMS Portable sem instalacao

Este modo permite correr o GTIMS num computador Windows sem instalar Docker, PostgreSQL, Python ou `winget`.

## Como funciona

O pacote inclui:

- A aplicacao GTIMS.
- Um runtime Python dentro de `runtime\python`.
- Todas as dependencias Python ja copiadas.
- SQLite local em `dados_locais\stock_manager.db`.
- Scripts de arranque por duplo clique.

## Quando usar

Use para piloto local, servidor temporario, demonstracao operacional ou fase antes da migracao para servidor principal.

Para operacao definitiva com muitos utilizadores simultaneos, PostgreSQL continua recomendado.

## Criar o pacote

No computador de desenvolvimento:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\create_windows_portable_no_install_package.ps1 -ServerIp 192.168.1.6
```

O ZIP sera criado em:

```text
outputs\packages
```

## Instalar no servidor

No computador `192.168.1.6`:

1. Criar ou usar a pasta `C:\GTIMS`.
2. Extrair o ZIP portable para `C:\GTIMS`.
3. Dar duplo clique em:

```text
Iniciar_GTIMS_Portable.bat
```

## Acesso

No proprio servidor:

```text
http://127.0.0.1:8000
```

Na rede:

```text
http://192.168.1.6:8000
```

## Firewall

Se outros computadores nao conseguirem abrir o sistema, executar como Administrador:

```text
Iniciar_GTIMS_Portable_Como_Admin_Abrir_Firewall.bat
```

Ou abrir manualmente:

```powershell
New-NetFirewallRule -DisplayName "GTIMS Portable Web 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private
```

## Base local

A base fica em:

```text
dados_locais\stock_manager.db
```

Por defeito, esta base nao sincroniza com o Render/Supabase.

Para usar os mesmos dados online, editar `.env.portable` e preencher:

```text
DATABASE_URL=postgresql+psycopg://...
```

Quando `DATABASE_URL` esta preenchida, o portable usa essa base externa e nao cria seed automatico.

Leia tambem:

```text
docs\data-strategy-local-online.md
```

## Local principal com Render mirror

No `.env.portable` do servidor local:

```text
SYNC_MODE=primary
SYNC_AUTO_PUSH=true
SYNC_TARGET_URL=https://URL-DO-RENDER
SYNC_TOKEN=mesmo-token-do-render
SYNC_INTERVAL_SECONDS=300
```

No Render:

```text
SYNC_MODE=mirror
MIRROR_READ_ONLY=true
SYNC_TOKEN=mesmo-token-do-local
```

Antes de ativar o local como principal, importar os dados atuais do online:

```text
Testar_Puxar_Dados_Online.bat
IMPORTAR_DADOS_ONLINE_PARA_LOCAL_CUIDADO.bat
```

Uploads, documentos e outputs ficam tambem dentro de:

```text
dados_locais
```

## Backup

Copiar regularmente:

```text
dados_locais
```

Ou gerar ZIP:

```powershell
Compress-Archive -Path dados_locais -DestinationPath backups\gtims-portable-backup.zip -Force
```
