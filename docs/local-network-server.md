# GTIMS em servidor local de rede

Este roteiro coloca o GT Integrated Management System a correr num computador local da empresa, acessivel por browser dentro da rede interna.

## Decisao recomendada

Para uso real em equipa, usar:

- Docker Desktop no computador-servidor.
- PostgreSQL local em container.
- Aplicacao GTIMS em container.
- Dados persistentes em volumes Docker e `server-data/app`.
- Acesso interno por `http://IP_DO_SERVIDOR:8000`.

Evitar usar SQLite para varios utilizadores em simultaneo. SQLite e aceitavel para testes locais, mas PostgreSQL e mais seguro para operacao real.

## Render e servidor local

A aplicacao atual nao tem um front-end separado: o FastAPI tambem renderiza as paginas. Por isso existem tres cenarios possiveis:

1. Servidor local independente: a equipa usa `http://IP_DO_SERVIDOR:8000` na rede. Render fica como ambiente online separado.
2. Render e servidor local com a mesma base Supabase/PostgreSQL: os dois ambientes mostram os mesmos dados, mas o servidor local depende da internet para chegar a base.
3. Acesso online ao servidor local: usar VPN, proxy reverso ou tunel seguro para expor o servidor interno. E o caminho certo quando o objetivo e que o sistema local seja a fonte principal.

Nao e recomendado manter duas bases ativas com dados reais sem sincronizacao, porque requisicoes, movimentos e aprovacoes podem divergir.

Para a decisao completa sobre dados local/online, ver:

```text
docs\data-strategy-local-online.md
```

## 1. Preparar o computador-servidor

No computador que vai servir o sistema:

- Definir IP fixo ou reserva DHCP no router.
- Confirmar que o computador nao entra em suspensao.
- Instalar Docker Desktop.
- Abrir a porta `8000` no firewall do Windows para a rede privada.
- Criar uma pasta para o sistema, por exemplo:

```powershell
C:\GTIMS
```

Se o PowerShell disser que `docker` nao e reconhecido, instale Docker Desktop,
reinicie o computador, abra Docker Desktop e confirme com:

```powershell
docker --version
docker compose version
```

O pacote tambem inclui uma pre-verificacao:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_lan_server_prereqs.ps1
```

Se `winget` tambem nao existir ou Docker Desktop nao for suportado na maquina,
use temporariamente o modo Windows nativo descrito em:

```text
docs\windows-native-lan.md
```

## 2. Copiar o projeto

Copiar o pacote do projeto para `C:\GTIMS` e confirmar que existem estes ficheiros:

- `Dockerfile`
- `docker-compose.lan.yml`
- `.env.lan.example`
- `app\`
- `requirements.txt`

## 3. Criar configuracao local

Copiar o exemplo:

```powershell
Copy-Item .env.lan.example .env.lan
```

Editar `.env.lan` e trocar obrigatoriamente:

- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `RESET_STOCK_SECURITY_CODE`
- `INITIAL_SUPERADMIN_PASSWORD`

Usar senhas fortes. A senha `INITIAL_SUPERADMIN_PASSWORD` so e usada para criar o primeiro `superadmin` quando a base ainda esta vazia.

## 4. Subir a aplicacao

Na pasta do sistema:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build
```

Verificar os logs:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan logs -f web
```

## 5. Criar o primeiro superadmin

Executar apenas na primeira instalacao, com a base vazia:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan exec web python -m app.seed
```

Depois entrar com:

```text
utilizador: superadmin
senha: valor definido em INITIAL_SUPERADMIN_PASSWORD
```

## 6. Aceder pela rede

No proprio servidor:

```text
http://127.0.0.1:8000
```

Nos outros computadores da rede:

```text
http://IP_DO_SERVIDOR:8000
```

Exemplo:

```text
http://192.168.1.50:8000
```

## 7. Backup minimo

Criar pasta de backups:

```powershell
New-Item -ItemType Directory -Force backups
```

Backup da base:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan exec -T db pg_dump -U stock_user stock_manager > backups\gtims-db.sql
```

Backup dos documentos e outputs:

```powershell
Compress-Archive -Path server-data\app -DestinationPath backups\gtims-files.zip -Force
```

Guardar os backups fora do computador-servidor tambem, por exemplo num disco externo ou pasta de rede.

## 8. Atualizar versoes

Para atualizar:

```powershell
docker compose -f docker-compose.lan.yml --env-file .env.lan down
docker compose -f docker-compose.lan.yml --env-file .env.lan up -d --build
```

Antes de atualizar, fazer backup da base e dos ficheiros.

## 9. Checklist de aceitacao

- Login do `superadmin`.
- Criacao de utilizador.
- Criacao de produto.
- Entrada de stock.
- Saida de stock sem permitir saldo negativo.
- Requisicao SR e aprovacao.
- Movimento gerado pela requisicao.
- Notificacao para o perfil certo.
- Upload de documento.
- Relatorio PDF.
- Acesso a partir de outro computador da rede.

## 10. Informacao que preciso do servidor

Quando formos instalar, confirmar:

- IP do computador-servidor.
- Sistema operativo e versao.
- Se Docker Desktop ja esta instalado.
- Porta pretendida, por defeito `8000`.
- Se vamos usar base local PostgreSQL ou Supabase partilhado.
- Se Render deve continuar como ambiente separado ou apontar para a mesma base.
