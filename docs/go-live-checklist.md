# Go-Live Checklist

## Antes de publicar

- Definir plataforma/servidor.
- Criar `SECRET_KEY` forte.
- Definir domínio ou IP público.
- Definir se a base será PostgreSQL.
- Definir política de backups.
- Configurar SMTP para e-mails reais.
- Confirmar quem será SuperAdmin inicial.
- Alterar senhas temporárias.

## Depois de publicar

- Aceder ao domínio/IP.
- Entrar como SuperAdmin.
- Confirmar logo e layout.
- Confirmar criação de requisição.
- Confirmar notificação interna.
- Confirmar e-mail ou outbox.
- Confirmar entrada de stock com documento.
- Confirmar relatório PDF.
- Confirmar backup.

## Segurança

- Usar HTTPS.
- Nunca deixar `SECRET_KEY=change-me-in-production`.
- Não expor PostgreSQL publicamente.
- Fazer backup da base e `/data/uploads`.
- Usar senhas fortes para utilizadores administrativos.
