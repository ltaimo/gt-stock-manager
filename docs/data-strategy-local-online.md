# Estrategia de dados: local e online

## Regra principal

Para uso real, o GTIMS deve ter uma unica fonte da verdade.

Isto significa que requisicoes, movimentos, aprovacoes, utilizadores, perfis, auditoria e stock devem viver numa unica base de dados ativa.

## O pacote portable puxa os dados online automaticamente?

Nao.

Por defeito, o pacote portable cria uma base local SQLite em:

```text
dados_locais\stock_manager.db
```

Essa base e independente da base usada pelo Render/Supabase. Se a equipa usar o sistema online e o portable local ao mesmo tempo com bases diferentes, os dados vao divergir.

## O que acontece se usarmos duas bases diferentes?

Pode acontecer:

- Um utilizador criado online nao existir no local.
- Uma requisicao aprovada online nao aparecer no local.
- Um movimento de saida feito localmente nao baixar o stock online.
- A auditoria ficar dividida.
- Relatorios mostrarem valores diferentes.
- O mesmo produto ter saldos diferentes.

Por isso, duas bases diferentes so devem ser usadas para testes isolados.

## Opcoes possiveis

### Opcao A: Local isolado

O servidor local usa SQLite em `dados_locais`.

Bom para:

- Testes.
- Piloto sem internet.
- Demonstracao.
- Uso temporario antes da migracao final.

Limite:

- Nao sincroniza com o online.
- Nao deve ser usado em paralelo com Render para dados reais.

### Opcao B: Local e Render com a mesma base online

O servidor local e Render apontam para a mesma `DATABASE_URL`, por exemplo Supabase/PostgreSQL.

Bom para:

- Mesmos utilizadores.
- Mesmas requisicoes.
- Mesmo stock.
- Mesma auditoria.
- Acesso local pela rede e acesso online pelo Render.

Limite:

- O servidor local precisa de internet para falar com a base online.
- Os ficheiros enviados/uploaded precisam de uma estrategia propria, porque podem estar no filesystem do Render ou do servidor local.

### Opcao C: Servidor local como principal

O servidor local fica como fonte principal, idealmente com PostgreSQL local.

Bom para:

- Operacao interna controlada.
- Dados dentro da rede.
- Menor dependencia do Render.

Para acesso externo:

- VPN.
- Dominio interno.
- Reverse proxy.
- Tunel seguro.

Limite:

- Exige configuracao de infraestrutura.

## Como ligar o portable a base online

No pacote portable, editar:

```text
.env.portable
```

Adicionar a mesma `DATABASE_URL` usada no Render/Supabase:

```text
DATABASE_URL=postgresql+psycopg://...
```

Quando `DATABASE_URL` esta preenchida, o portable nao cria seed automatico. Isto evita alterar uma base online existente.

## Ficheiros e documentos

A base de dados guarda os registos. Mas alguns documentos enviados ficam em pastas de ficheiros.

No Render:

```text
UPLOADS_DIR
OUTPUTS_DIR
DOCUMENTS_DIR
```

No portable:

```text
dados_locais\uploads
dados_locais\outputs
dados_locais\uploads\stock_documents
```

Se a mesma base online for usada por local e Render, e houver documentos antigos com caminho de ficheiro do Render, o servidor local pode ver o registo mas nao conseguir descarregar o ficheiro se o ficheiro nao existir localmente.

Para resolver definitivamente, e melhor mover documentos para armazenamento partilhado, por exemplo:

- Supabase Storage.
- Google Drive/SharePoint com integracao.
- Pasta de rede interna.
- Object storage S3 compativel.

## Modelo aprovado: local principal e Render mirror

Neste modelo:

- O servidor `192.168.1.6` e a fonte principal.
- Os utilizadores fazem operacoes reais no servidor local.
- O Render fica como espelho online.
- Quando o servidor local tiver internet, envia atualizacoes para o Render.
- O Render deve ficar em modo so leitura para evitar conflitos.

## Variaveis no Render

No Render:

```text
SYNC_MODE=mirror
MIRROR_READ_ONLY=true
SYNC_TOKEN=um-token-forte-igual-ao-local
```

O `DATABASE_URL` do Render continua a apontar para a base online/Supabase que sera o espelho.

## Variaveis no servidor local

No servidor local:

```text
SYNC_MODE=primary
SYNC_AUTO_PUSH=true
SYNC_TARGET_URL=https://URL-DO-RENDER
SYNC_TOKEN=mesmo-token-do-render
SYNC_INTERVAL_SECONDS=300
```

Com isto, o local tenta atualizar o Render automaticamente de 5 em 5 minutos.

Tambem pode sincronizar manualmente:

```text
Sincronizar_Render_Agora.bat
```

## Bootstrap antes da virada

Como ja existem dados reais online, o local nao pode comecar vazio.

Fluxo correto:

1. Publicar no Render a versao com endpoints de sincronizacao.
2. Configurar `SYNC_TOKEN` no Render.
3. No servidor local, configurar `SYNC_TARGET_URL` e `SYNC_TOKEN`.
4. Testar leitura do snapshot online:

```text
Testar_Puxar_Dados_Online.bat
```

5. Importar os dados online para o local:

```text
IMPORTAR_DADOS_ONLINE_PARA_LOCAL_CUIDADO.bat
```

6. Validar localmente utilizadores, produtos, requisicoes, movimentos, documentos e relatorios.
7. Colocar Render em:

```text
SYNC_MODE=mirror
MIRROR_READ_ONLY=true
```

8. Colocar local em:

```text
SYNC_MODE=primary
SYNC_AUTO_PUSH=true
```

9. A partir deste momento, o local e a fonte principal.

## O que o mirror nao resolve sozinho

O sync de dados replica tabelas da base. Documentos enviados/uploaded precisam de verificacao separada, porque os ficheiros fisicos podem estar numa pasta local ou no Render.

Antes de entrega final, validar:

- Download de documentos antigos.
- Upload de novos documentos no local.
- Relatorios PDF gerados no local.
- Se documentos devem aparecer tambem no Render.

Para uma solucao definitiva de documentos online/local, usar armazenamento partilhado: Supabase Storage, pasta de rede, SharePoint/Google Drive ou object storage.

## Recomendacao para a fase atual

Como ja existem dados reais online, a recomendacao e:

1. Nao usar o portable SQLite para trabalho real em paralelo com Render.
2. Fazer backup/export dos dados online antes de qualquer mudanca.
3. Importar os dados online para o servidor local antes da virada.
4. Transformar Render em mirror so leitura.
5. Ativar envio automatico do local para Render.
6. Definir estrategia de documentos antes de abandonar o Render como ambiente principal.
