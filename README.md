# Stock Management System

Sistema web para substituir o gestor Excel/VBA de economato, movimentos, requisições, relatórios e utilizadores.

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
python -m app.seed
uvicorn app.main:app --reload
```

Aceda a `http://127.0.0.1:8000`.

## Utilizador inicial

- Utilizador: `superadmin`
- Senha: `Admin@12345`

Altere a senha após o primeiro acesso.

## Módulos

- Dashboard
- Economato / Produtos
- Movimentos
- Nova Requisição
- Requisições
- Relatórios
- Utilizadores
- Configurações
- Importação Excel/CSV
- Auditoria

## Regras principais

- Movimentos são a fonte da verdade do estoque.
- Produtos com movimentos não são eliminados fisicamente; são inativados.
- Saídas acima do estoque disponível são bloqueadas, exceto override SuperAdmin.
- Acertos exigem justificação.
- Requisições emitidas geram movimentos de Saída automaticamente.
- Utilizadores importados devem redefinir senha no primeiro login.
