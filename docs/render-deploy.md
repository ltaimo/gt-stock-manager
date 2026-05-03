# Deploy no Render Free

## Opção Recomendada Para Demo

Use o ficheiro `render.yaml` como Blueprint.

## Passos

1. Criar conta em Render.
2. Colocar este projeto num repositório GitHub.
3. No Render, escolher **New +** -> **Blueprint**.
4. Selecionar o repositório.
5. Confirmar o serviço `gt-stock-manager`.
6. Fazer deploy.

## Login de Demonstração

- `superadmin / Admin@12345`
- `admin / admin123`
- `gestor.stock / gestor123`
- `chefe.terminal / chefe123`

## Nota Sobre Render Free

Nesta configuração de demo, a base SQLite fica em `/tmp`. Em serviços free, os dados podem ser reiniciados quando o serviço é recriado. O arranque executa:

```bash
python -m app.seed
python -m app.maintenance.seed_demo_data
python -m app.maintenance.categorize_products
```

Assim a aplicação volta a ter dados de demonstração automaticamente.

Para produção real, usar PostgreSQL e armazenamento persistente.

## Variáveis Que Podem Ser Ajustadas no Render

- `SECRET_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
