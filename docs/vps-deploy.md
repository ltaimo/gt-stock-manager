# Deploy em VPS com Docker

## 1. Preparar servidor

Instalar Docker e Docker Compose no servidor.

## 2. Enviar projeto

Copiar o projeto para o servidor, por exemplo:

```bash
scp -r stock-manager user@server:/opt/stock-manager
```

## 3. Ajustar variáveis

Editar `docker-compose.yml`:

- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `DATABASE_URL`
- `SESSION_COOKIE_SECURE=true` quando estiver com HTTPS

## 4. Subir aplicação

```bash
cd /opt/stock-manager
docker compose up -d --build
```

## 5. Criar seed inicial

```bash
docker compose exec web python -m app.seed
```

## 6. Aceder

```text
http://SERVER_IP:8000
```

Em produção final, coloque Nginx/Caddy/Traefik à frente para HTTPS e domínio.
