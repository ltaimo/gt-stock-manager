# Mini manual — relatórios departamentais

O guia está disponível na aplicação, em **Relatórios departamentais → Como fazer · guia rápido**.

| Ação | Caminho e resultado |
| --- | --- |
| Criar diário | Escolher o departamento → Criar relatório diário → preencher → Submeter relatório. |
| Retomar | Diários → Continuar rascunho. A gravação é automática enquanto preenche. |
| Consolidar | Consolidar relatório → departamento e semana/mês → datas automáticas ou Personalizado, De e Até → Gerar e rever → Submeter relatório. |
| Reutilizar | Criar cópia → confirmar a data e atualizar o conteúdo. A cópia é um rascunho; o anterior permanece preservado. |
| Repetir um período | Gerar novamente cria V2, V3…; não bloqueia por existir outra versão. |
| Exportar | Abrir o relatório → Pré-visualizar PDF, Descarregar PDF ou Word. |
| Ler PDF digitalizado | Documentos do Gestor → carregar PDF → aguardar OCR → conferir texto e valores → Validar documento como fonte. |
| Apagar/restaurar | Apagar relatório → motivo; para recuperar, Eliminados → Restaurar. Exige permissão. |
| Configurar campos | Configuração → formulário do departamento → editar tabelas, colunas e opções → Guardar configuração. Exige permissão. |

As configurações aplicam-se a novos relatórios. Relatórios e rascunhos anteriores mantêm a estrutura original. Cada utilizador consulta os seus relatórios, salvo autorização para consultar todos.

**Gerar** consulta os dados atuais do período. **Criar cópia** reutiliza o conteúdo da versão selecionada. Confirmar sempre datas, responsáveis e valores antes da submissão. Nos documentos do Gestor repetidos, só a revisão validada mais recente do mesmo documento e data alimenta novas consolidações.

## Atualização do mini manual

### Dashboard do relatório

Ao gerar um relatório semanal ou mensal, o dashboard aparece automaticamente no início da pré-visualização. PDF e Word novos incluem os mesmos gráficos. Não existe um botão separado para os gerar. Os gráficos variam conforme os indicadores, tabelas, pendências e dados CCTV disponíveis.

Para alimentar valores como entradas/saídas, combustível ou selos utilizados, registe os indicadores estruturados no diário, indicando a dimensão (regime, equipamento ou portão). Números de matrícula, selos e leituras acumuladas não são somados como quantidades. Nos documentos oficiais antigos, use **Criar cópia** e reveja a nova versão para obter o dashboard nas exportações.

### Monitoria CCTV

Abra **Relatórios departamentais → Monitoria operacional CCTV**. Use **Registar nova câmara** para acrescentar equipamentos. Abra uma câmara → **Editar câmara** para alterar código/nome, área, modelo, NVR e localização. A data de retirada remove-a das listas ativas sem apagar o histórico; **Incluir câmaras retiradas** permite encontrá-la.

Em **Programar inspeção e limpeza recorrente**, escolha a próxima data e o intervalo em dias. Em **Inspeção e limpeza**, registe o resultado de cada trabalho. O plano inicial contempla as 102 câmaras dos documentos, com frequência semanal e 14 a 15 câmaras por dia, cumprindo o mínimo de 10 limpezas diárias solicitado.

Nos perfis, **Consultar monitoria CCTV**, **Registar novas câmaras CCTV** e **Editar câmaras, monitoria e programação CCTV** são acessos separados. **Administrar CCTV (todas as ações)** concede o controlo completo; para acesso limitado, selecione apenas as opções específicas.

Em **Perfis de acesso**, atribua separadamente **Gerar e submeter relatórios consolidados** e **Carregar e rever relatórios do Gestor**. Pode marcar uma, ambas ou nenhuma. A primeira não autoriza carregar, editar, executar OCR ou validar documentos do Gestor. As permissões já guardadas nos perfis não recebem automaticamente a nova opção; o administrador escolhe quem deve recebê-la.

Nas datas automáticas, uma data de referência preenche **De** e **Até** para a semana ou o mês. Para escolher outro intervalo, selecione **Personalizado** e preencha as duas datas, inclusive. O intervalo escolhido aparece no relatório e nas exportações.

O relógio junto às notificações apresenta a hora local do computador, incluindo segundos. Atualiza a cada segundo e ao regressar à janela; usa o fuso horário configurado no dispositivo.

Cada entrega que introduza ou altere uma ação deve atualizar este resumo e o guia dentro da aplicação (`app/templates/operational_reports/guide.html`), indicando: botão de entrada, passos essenciais, permissão necessária e resultado esperado. O mini manual acompanha o sistema enquanto o manual completo é preparado.
