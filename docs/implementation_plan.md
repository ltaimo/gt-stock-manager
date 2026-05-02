# Sistema de Gestão de Stock - Plano de Implementação

## 1. Arquitetura Proposta

- Aplicação web server-rendered com FastAPI, Jinja e SQLAlchemy.
- Camadas separadas: `routers`, `models`, `services`, `templates`, `static`.
- Base de dados relacional, SQLite em desenvolvimento e PostgreSQL recomendado para produção.
- Movimentos são a fonte da verdade do stock; produto mantém stock atual em cache operacional.

## 2. Stack Recomendada

- Backend: FastAPI
- ORM: SQLAlchemy
- UI: Jinja templates, CSS corporativo
- Base de dados: SQLite/PostgreSQL
- Exportação: OpenPyXL e ReportLab
- Segurança: sessões HTTP, PBKDF2-SHA256, permissões por perfil

## 3. Schema

- `roles`
- `departments`
- `users`
- `categories`
- `products`
- `stock_movements`
- `requisitions`
- `requisition_items`
- `audit_logs`
- `settings`
- `import_error_rows`

Próxima evolução recomendada:
- `requisition_status_history`
- `import_batches`
- `import_errors`

## 4. Matriz de Permissões

| Módulo | SuperAdmin | Admin | Editor | User |
| --- | --- | --- | --- | --- |
| Dashboard | Sim | Sim | Sim | Sim |
| Produtos | Tudo | Criar/Editar | Ver | Disponibilidade |
| Movimentos | Tudo + override | Criar/Ver | Criar/Ver | Não |
| Requisições | Tudo | Aprovar/Emitir | Processar | Próprias |
| Relatórios | Todos | Todos | Operacionais | Não |
| Utilizadores | Todos | Exceto SuperAdmin | Não | Não |
| Auditoria | Todos | Operacional | Não | Não |
| Configurações | Todos | Operacional | Não | Não |

## 5. Fluxos Principais

1. Login seguro com auditoria.
2. Produtos são criados ou importados.
3. Stock só muda através de movimentos.
4. Requisição nasce em rascunho, é submetida, aprovada/rejeitada e emitida.
5. Emissão cria movimento de saída e atualiza stock em transação.
6. Relatórios podem ser exportados para Excel/PDF.
7. Importação do Excel passa por preview antes de gravar.

## 6. UI Layout

- Login com logo/identidade GT.
- Sidebar com logo no topo.
- Topbar com utilizador e perfil.
- Conteúdo com cards brancos, cinza corporativo e acento dourado.
- Footer persistente: `Designed by Layton Taimo`.

## 7. Componentes

- Botões `.button`, `.secondary`, `.danger`
- Cards `.panel`, `.kpis`
- Tabelas com filtros
- Badges por estado
- Formulários com labels claros
- Empty states e relatórios exportáveis

## 8. Fases

1. Setup, autenticação, roles, layout, logo e footer.
2. Economato, categorias, departamentos.
3. Movimentos transacionais e histórico.
4. Requisições, aprovação, emissão e PDF.
5. Dashboard e relatórios.
6. Importação, auditoria, configurações e polimento final.
