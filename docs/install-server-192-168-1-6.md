# Instalacao GTIMS no servidor local 192.168.1.6

Servidor definido:

```text
192.168.1.6
```

Endereco final esperado na rede:

```text
http://192.168.1.6:8000
```

## 1. Preparar o servidor

No computador `192.168.1.6`:

1. Confirmar que o computador tem IP fixo ou reserva DHCP para continuar sempre em `192.168.1.6`.
2. Confirmar que o computador nao entra em suspensao.
3. Criar a pasta:

```powershell
New-Item -ItemType Directory -Force C:\GTIMS
```

4. Abrir a porta `8000` no firewall:

```powershell
New-NetFirewallRule -DisplayName "GTIMS Web 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private
```

## Caminho preferido sem instalacao

Para nao instalar Docker, Python, PostgreSQL ou `winget`, use o pacote portable:

```text
GTIMS_Portable_NoInstall_v3.0.0-20260721-1116.zip
```

Depois de extrair em `C:\GTIMS`, iniciar com:

```text
Iniciar_GTIMS_Portable.bat
```

Mais detalhes:

```text
docs\portable-no-install.md
```

Antes de usar dados reais, confirmar a estrategia de dados:

```text
docs\data-strategy-local-online.md
```

Para o modelo local principal + Render mirror:

1. Importar primeiro os dados online para o local.
2. Testar localmente.
3. Colocar o Render em `SYNC_MODE=mirror`.
4. Colocar o local em `SYNC_MODE=primary`.
5. Usar o local como fonte principal.

## Se `docker` nao for reconhecido

Se aparecer:

```text
The term 'docker' is not recognized
```

isso significa que o Docker Desktop nao esta instalado, nao esta aberto, ou o PowerShell foi aberto antes da instalacao atualizar o `PATH`.

No computador `192.168.1.6`, instale Docker Desktop. Se `winget` estiver disponivel, use:

```powershell
winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
```

Depois:

1. Reiniciar o computador, ou terminar sessao e voltar a entrar.
2. Abrir Docker Desktop.
3. Aguardar ate o Docker ficar em execucao.
4. Abrir um novo PowerShell.
5. Confirmar:

```powershell
docker --version
docker compose version
```

Tambem pode correr a pre-verificacao:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_lan_server_prereqs.ps1
```

Se `winget` tambem nao for reconhecido, use uma destas opcoes:

1. Instalar Docker Desktop manualmente pelo browser:

```text
https://docs.docker.com/desktop/setup/install/windows-install/
```

Baixar `Docker Desktop Installer.exe`, executar o instalador e depois reiniciar/abrir Docker Desktop.

2. Se a maquina nao suportar Docker Desktop, usar o modo Windows nativo:

```text
docs\windows-native-lan.md
```

## 2. Copiar o pacote

Copiar o ZIP `GTIMS_LAN_Server_v3.0.0-20260721-0857.zip` para `C:\GTIMS`.

Extrair o ZIP dentro de `C:\GTIMS`.

## 3. Criar configuracao

Na pasta `C:\GTIMS`:

```powershell
Copy-Item .env.lan.example .env.lan
notepad .env.lan
```

Alterar obrigatoriamente:

```text
POSTGRES_PASSWORD=...
SECRET_KEY=...
RESET_STOCK_SECURITY_CODE=...
INITIAL_SUPERADMIN_PASSWORD=...
```

Nao usar senhas temporarias em producao real.

## 4. Subir o sistema

Na pasta `C:\GTIMS`:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build
```

Verificar estado:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan ps
```

Ver logs:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan logs -f web
```

## 5. Criar superadmin inicial

Executar apenas na primeira instalacao, com base vazia:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan exec web python -m app.seed
```

Depois entrar com:

```text
Utilizador: superadmin
Senha: valor definido em INITIAL_SUPERADMIN_PASSWORD
```

## 6. Testar acesso

No proprio servidor:

```text
http://127.0.0.1:8000
```

Noutra maquina da rede:

```text
http://192.168.1.6:8000
```

## 7. Comandos uteis

Parar:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan down
```

Atualizar:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build
```

Backup da base:

```powershell
New-Item -ItemType Directory -Force backups
docker compose -f docker-compose.lan.yml --env-file .env.lan exec -T db pg_dump -U stock_user stock_manager > backups\gtims-db.sql
```

Backup dos ficheiros:

```powershell
Compress-Archive -Path server-data\app -DestinationPath backups\gtims-files.zip -Force
```

## 8. Confirmacao antes de uso real

Testar:

- Login do superadmin.
- Criacao de utilizador.
- Produto e entrada de stock.
- Saida de stock sem saldo negativo.
- Requisicao SR.
- Aprovacao conforme perfil/matriz.
- Notificacao.
- Upload de documento.
- Relatorio PDF.
- Acesso por outro computador na rede.
