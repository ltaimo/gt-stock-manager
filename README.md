# Stock Management System

Versão atual: **3.0.0**

Sistema web bilingue para gestão integrada GTIMS: economato, stock, movimentos, requisições SR, Procurement, reposição, HSE/HST, operações internas, relatórios, utilizadores e permissões.

## Stack

- FastAPI + Jinja
- SQLAlchemy ORM
- SQLite por defeito (`stock_manager.db`)
- Password hashing com PBKDF2-SHA256/passlib
- Exportação CSV/XLSX/PDF

## Setup

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:INITIAL_SUPERADMIN_PASSWORD="defina-uma-senha-forte"
python -m app.seed
uvicorn app.main:app --reload
```

Aceda a `http://127.0.0.1:8000`.

## Utilizador inicial

O primeiro `superadmin` usa a senha definida em `INITIAL_SUPERADMIN_PASSWORD`.
Use pelo menos 12 caracteres e altere a senha após o primeiro acesso.

## Módulos

- Dashboard
- Economato / Produtos
- Movimentos
- Nova Requisição
- Requisições
- Procurement / Non-Stock
- Reposição de stock
- HSE / HST
- Operações internas
- Relatórios
- Utilizadores
- Perfis e permissões
- Configurações
- Notificações e documentos
- Importação Excel/CSV
- Auditoria

## Regras principais

- Movimentos são a fonte da verdade do stock.
- Produtos com movimentos não são eliminados fisicamente; são inativados.
- Saídas acima do stock disponível são sempre bloqueadas.
- Acertos exigem justificação.
- Requisições emitidas geram movimentos de Saída automaticamente.
- Utilizadores importados devem redefinir senha no primeiro login.
- Valores persistidos permanecem canónicos; a tradução ocorre apenas na apresentação.
- Nomes de produtos e categorias podem ter uma apresentação opcional em inglês sem substituir o original.
- Em produção, `DATABASE_URL` é obrigatório para evitar arranque acidental com uma base local/vazia.
- O arranque de produção executa apenas migração de esquema; não executa `app.seed` contra dados existentes.

## Servidor local de rede

Para instalar o GTIMS num computador-servidor acessível dentro da rede interna,
use `docker-compose.lan.yml` e siga `docs/local-network-server.md`.

Para um modo temporario sem instalar Docker, Python ou PostgreSQL, gere o pacote
portable com `scripts/create_windows_portable_no_install_package.ps1` e siga
`docs/portable-no-install.md`.

## Manuais

- `docs/manual/GT-Stock-Manager-Manual-PT.docx` e respetivo PDF.
- `docs/manual/GT-Stock-Manager-User-Manual-EN.docx` e respetivo PDF.
