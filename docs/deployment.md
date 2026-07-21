# Deploy Online

## Produção Recomendada

Use Docker com:

- Aplicação FastAPI
- PostgreSQL gerido ou PostgreSQL num servidor
- Volume persistente para `/data/uploads` e `/data/outputs`
- HTTPS no proxy/plataforma

## Demo no Render Free

Para apresentação rápida, use `render.yaml` e siga:

[Render Deploy](render-deploy.md)

## Servidor Local de Rede

Para uso interno num computador da empresa, use `docker-compose.lan.yml` e siga:

[GTIMS em servidor local de rede](local-network-server.md)

Para uma fase temporaria sem instalar Docker/Python/PostgreSQL no servidor, use:

[GTIMS Portable sem instalacao](portable-no-install.md)

## Variáveis Obrigatórias

Copie `.env.example` e configure:

- `ENVIRONMENT=production`
- `SECRET_KEY`
- `DATABASE_URL`
- `UPLOADS_DIR`
- `OUTPUTS_DIR`
- `DOCUMENTS_DIR`
- `EMAIL_OUTBOX_DIR`
- `SESSION_COOKIE_SECURE=true`

## E-mail

Para envio real de notificações:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

Sem SMTP, o sistema grava e-mails em `EMAIL_OUTBOX_DIR`.

## Comandos Locais com Docker

```powershell
docker build -t gt-stock-manager .
docker run --env-file .env -p 8000:8000 -v ${PWD}/data:/data gt-stock-manager
```

## Criar Dados Iniciais

Depois do primeiro deploy:

```bash
python -m app.seed
```

## Observações

- O sistema cria as tabelas automaticamente no arranque.
- Para produção real, PostgreSQL é melhor que SQLite.
- Faça backup regular da base de dados e da pasta `/data/uploads`.
