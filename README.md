# Stock Management System

Versão atual: **2.1.1**

Sistema web bilingue para gestão de economato, movimentos, requisições SR, Procurement, reposição, relatórios e utilizadores.

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

## Manuais

- `docs/manual/GT-Stock-Manager-Manual-PT.docx` e respetivo PDF.
- `docs/manual/GT-Stock-Manager-User-Manual-EN.docx` e respetivo PDF.
