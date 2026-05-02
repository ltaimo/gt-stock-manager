# Arquitetura e Regras

## Camadas

- `app/routers`: controladores HTTP e páginas.
- `app/models`: schema relacional normalizado.
- `app/services`: regras de negócio, auditoria, importação, exportação e estoque.
- `app/templates`: interface portuguesa server-rendered.
- `app/static`: CSS/JS.

## Modelo de estoque

`stock_movements` é a fonte da verdade. `products.current_stock`, `total_entries` e `total_exits` são cache operacional atualizado por transação.

Fórmula:

`stock = entradas + devoluções + acertos positivos - saídas - acertos negativos`

## Estados de alerta

- `Estoque OK`: estoque atual acima do mínimo.
- `Estoque Crítico`: estoque atual menor ou igual ao mínimo.
- `Erro: Stock Negativo`: estoque abaixo de zero.

## Imutabilidade

Movimentos lançados não são editados. Qualquer correção deve ser um novo movimento de `ACERTO` com justificação.

## Permissões

| Módulo | SuperAdmin | Admin | Editor | User |
| --- | --- | --- | --- | --- |
| Dashboard | Sim | Sim | Sim | Sim |
| Produtos | CRUD | CRUD | Ver | Ver |
| Movimentos | Criar/Ver/Override | Criar/Ver | Criar/Ver | Não |
| Requisições | Tudo | Tudo | Rever/Emitir | Próprias |
| Relatórios | Sim | Sim | Sim | Não |
| Utilizadores | Tudo | Sem SuperAdmin | Não | Não |
| Importação | Sim | Sim | Não | Não |
| Configurações | Sim | Sim | Não | Não |

## Migração Excel

A importação aceita `.xls`, `.xlsx` e `.csv`. Senhas antigas não são importadas em texto claro; todos os utilizadores importados recebem senha temporária e reset obrigatório.
