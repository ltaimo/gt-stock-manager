# Changelog

## 3.0.0 - 2026-07-20

- Introduz GTIMS como identidade da aplicação.
- Adiciona módulos HSE/HST e Operações Internas ao sistema integrado.
- Melhora o dashboard, navegação, cartões de módulos, ícones, notificações e experiência móvel.
- Adiciona registos específicos para combustível, água e energia, incluindo compra, abastecimento, leituras e opções configuráveis.
- Reorganiza as configurações de operações internas em grupos práticos: fornecedores, combustíveis, viaturas/equipamentos, locais/contadores e métodos de pagamento.
- Reforça permissões e perfis para preservar acessos existentes durante upgrades.
- Repara perfis padrão antigos com permissões vazias sem apagar utilizadores, departamentos ou histórico.
- Garante hierarquia da matriz de aprovações: níveis superiores aprovam níveis inferiores; níveis inferiores não aprovam valores superiores.
- Protege produção exigindo `DATABASE_URL` quando `ENVIRONMENT=production`.
- Remove `app.seed` do arranque de produção para não alterar dados reais em cada deploy.
- Atualiza configuração de deploy para versão 3.0.0 e branding GTIMS.

## 2.1.1 - 2026-06-28

- Implementa internacionalização completa em Português e Inglês.
- Persiste a preferência de idioma por utilizador, incluindo após novo login.
- Centraliza traduções de páginas, validações, estados, notificações e auditoria.
- Localiza relatórios CSV, Excel e PDF, e-mails, WhatsApp, requisições e TdR.
- Adiciona nomes opcionais em inglês para produtos e categorias sem alterar dados originais.
- Corrige acentuação, terminologia, mensagens antigas e problemas de encoding.
- Adiciona testes bilingues de páginas, campos, persistência, exportações e responsividade.
- Entrega manuais completos PT/EN em DOCX e PDF com screenshots e branding GTSA.
- Remove a senha pública padrão de novas instalações do SuperAdmin.

## 2.1.0 - 2026-06-27

- Adiciona pedidos de reposição de stock integrados com Procurement.
- Separa produtos monitorizados de compras pontuais.
- Exclui produtos inativos e não monitorizados dos alertas e sugestões.
- Mantém todos os produtos no relatório geral com estado e controlo explícitos.
- Adiciona exportação Excel/PDF ao relatório de stock que requer atenção.
- Mostra a versão da aplicação no rodapé e na página Sobre.
