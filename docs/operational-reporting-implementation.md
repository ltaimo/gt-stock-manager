# Relatórios operacionais GTSA

## Análise e decisões

O sistema já guarda relatórios diários departamentais, operações internas, documentos financeiros originais, notificações, permissões e auditoria. A implementação aproveita estas fontes e os geradores institucionais de PDF e Word. Os relatórios oficiais passam a guardar o conteúdo e as fontes utilizados, juntamente com ambos os ficheiros. Uma correção cria outra versão.

Os modelos semanal e mensal têm tabelas de viaturas por regime, apreensões, incidentes, selos, leituras e gráficos. Existem referências a livros externos e datas inconsistentes nos modelos; não são importados como factos operacionais. O PDF diário fornecido tem três páginas sem texto extraível: um documento assim é preservado e marcado para revisão, sem inventar métricas. A leitura visual confirma que inclui também secções departamentais; essas secções não devem duplicar os dados já existentes na aplicação.

O modelo CCTV separa dias operacionais, gravação e anomalias. O plano de limpeza prevê grupos de câmaras em diferentes dias da semana; Bypass não tem dia assinalado. As frequências e datas são configuráveis e não se inferem inspeções executadas a partir de marcas ambíguas.

## Regras de dados

- As novas ocorrências e métricas têm campos próprios. Textos históricos continuam acessíveis e identificados como informação narrativa, sem contagem automática de incidentes a partir de frases.
- Semanal e mensal leem as fontes diárias, nunca os totais de relatórios semanais.
- Quantidades do período podem ser somadas; saldos usam a última observação; contadores usam leituras inicial/final, sem somar leituras acumuladas.
- Dados estruturados têm precedência sobre o documento externo. Valores divergentes são apresentados para revisão. Fontes ausentes ficam explícitas; submissão parcial depende da configuração e de justificação.
- Monitoria CCTV e inspeções têm registos separados. Estados e calendários datados permitem consultar períodos anteriores.
- Pendências mantêm origem, responsável, prazo e histórico de estados e aparecem nos períodos seguintes até ao encerramento.

## Validação e publicação

Executar a migração aditiva `python -m app.maintenance.migrate_operational_reports` depois de preparar o schema existente. Não ativar DDL no arranque de produção. Manter versão 4.0.0. Validar geração, revisão, submissão, preservação das versões, anexos, limites de período, duplicados, permissões e CCTV antes de publicar.

### Verificação local em 11/09/2026

- Suite completa: 191 testes e 17 subtestes aprovados. Os cinco avisos são de depreciação de bibliotecas e do mecanismo de arranque existente.
- Navegador Edge, com base de teste isolada: gravação automática, recuperação após perda de ligação, recuperação após logout/login, submissão e exportação PDF/Word aprovadas, sem erros JavaScript. Ecrã móvel de 390 px sem transbordamento horizontal.
- PDF e Word exportados foram renderizados e as três páginas de cada formato revistas visualmente, incluindo títulos, gráficos, fontes e paginação.
- Migração aditiva aplicada apenas à base SQLite local, com cópia de segurança prévia em `.runtime/before-reporting-20260911-141511.db`.
- Esta expansão ainda não foi publicada em produção. A migração de produção deve preceder a ativação do novo código.

### Limites explícitos

Documentos digitalizados sem texto são preservados e exigem revisão e complementação dos indicadores; não existe OCR automático nesta implementação. Os modelos fornecidos servem de referência e não foram importados como ocorrências ou inspeções reais. Os avisos de pendências vencidas são avaliados quando a fila de pendências é consultada, com controlo de duplicados por prazo; não existe tarefa agendada independente.

### Tabelas departamentais — setembro de 2026

O modelo Word da Segurança contém a tabela de presenças na parada conjunta, com número, nome do vigilante, empresa, hora, cargo/função e teste de álcool. O formulário conserva estas colunas e acrescenta viatura opcional, solicitada pelo utilizador. A manutenção passa a ter linhas próprias para equipa, equipamentos inspecionados, tarefas, emergências e utilidades. As células são observações literais; não são convertidas automaticamente em indicadores numéricos.

As tabelas usam armazenamento aditivo separado, com validação de colunas, tamanho e permissões. A gravação automática inclui as linhas e notas; a colagem de células mantém tabulações, células vazias e texto entre aspas com quebras de linha. Os relatórios oficiais guardam uma cópia das tabelas. A consolidação semanal e mensal lê as fontes diárias e conserva as tabelas com data e origem, sem as duplicar ou transformar em texto corrido.

Verificação: 195 testes e 17 subtestes aprovados; smoke no Chrome de colagem de duas linhas, recuperação após refresh, submissão e pré-visualização tabular. PDF e Word com 40 linhas renderizados para conferir cabeçalhos repetidos e paginação. As dez tabelas adicionais de produção foram criadas transacionalmente na Supabase e têm RLS ativado, sem políticas de acesso público.
