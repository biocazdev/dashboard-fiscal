# Dashboard Fiscal Protheus (Python + Streamlit)

Dashboard fiscal para consulta de indicadores do ERP TOTVS Protheus,
conectando-se diretamente ao banco **SQL Server** do ambiente.

> **Documentação completa:** veja [DOCUMENTACAO.md](DOCUMENTACAO.md).

## Funcionalidades (primeira entrega)

- Conexão SQL Server via `.env` (somente leitura).
- Filtros por empresa, filial (múltipla escolha - visão consolidada de várias
  filiais ao mesmo tempo), período (data de emissão), **fornecedor** e **cliente**.
- Botão **Atualizar** (limpa o cache para buscar dados novos).
- Cards: NF entrada/saída (qtd e valor), ICMS entrada/saída, saldo de ICMS,
  IBS/CBS entrada/saída (reforma tributária, via F2D), **PIS/COFINS
  entrada/saída** (campos nativos de SD1/SD2) e ticket médio.
- Campos IBS/CBS e PIS/COFINS configuráveis via `.env` (campos
  vazios/inexistentes exibem R$ 0,00).
- **Quebra por CFOP** (natureza das operações) em entrada e saída, com
  quantidade de notas/itens e valor total. Campo de CFOP configurável via
  `.env` (`CAMPO_CFOP_ENTRADA/SAIDA`).
- **Filtro opcional de notas canceladas** (`STATUS_CANCELADO_ENTRADA/SAIDA`),
  desligado por padrão até confirmar o valor real nesta instalação - o
  checklist de qualidade mostra a distribuição de `F1_STATUS`/`F2_STATUS`
  para ajudar a identificar.
- **Evolução mensal (comparativo)**: gráfico de barras + linha na Visão
  Geral, com seletor de 6/12/24 meses e escolha de métricas (faturamento,
  entradas, ICMS, IBS/CBS, PIS/COFINS, % conciliado). Mostra a variação
  em relação ao mês anterior e ao mesmo mês do ano passado (quando o
  período cobre 13+ meses).
- **Alertas visuais (semáforo)**: ícone de aviso recolhido no topo da tela
  (🔴/🟡 + quantidade) quando o % de conciliação cai abaixo do limite, há
  pendências muito antigas, o Saldo de ICMS sai do padrão, ou o checklist
  de qualidade encontra notas duplicadas/inválidas - clique para expandir
  e ver os detalhes de cada alerta. Limites configuráveis no `.env`
  (`ALERTA_PCT_CONCILIACAO_MIN`, `ALERTA_IDADE_PENDENCIA_DIAS`,
  `ALERTA_SALDO_ICMS_CREDITO/MAX`).
- Botão **Gerar relatório em PDF** com o conteúdo de **todas as abas** em um
  único documento pronto para impressão/visualização (blocos de Movimentação
  e Tributos, Conciliação Fiscal x Contábil, detalhamento das notas e
  Retenções) - independente de qual aba está aberta no momento do clique.
- **Conciliação Fiscal x Contábil (CT2)**: aba própria com barra de progresso,
  cartões de status (inclui **idade da pendência** e **prazo médio de
  contabilização**), lista de documentos filtrável/buscável com export em
  **CSV/Excel**, drill-down por documento (com **anotação local** por
  documento), análise por período e **checklist de qualidade dos dados**
  (notas duplicadas, valor inválido, lotes CT2 com saldo diferente de zero).
  A chave de vínculo é configurável via `.env` (validar após o GO LIVE - ver
  DOCUMENTACAO.md, seção 12, para os detalhes técnicos).
- **Anotações locais por documento**: observações do contador (ex.:
  "aguardando NF do fornecedor") ficam salvas em um SQLite local
  (`anotacoes.db`), já que o Protheus é acessado somente leitura.
- **Retenções (IR/PIS/COFINS/CSLL)**: aba própria com os títulos de contas
  a pagar (SE2) que têm retenção sobre pagamentos a fornecedores PJ -
  equivalente ao relatório Reinf R-4020. Tabela filtrável (por fornecedor)
  com export **CSV/Excel** e cartões de total por tributo. Campo de CNPJ e
  mapeamento manual do "Cod. R" configuráveis via `.env`
  (`CAMPO_CNPJ_FORNECEDOR`, `RETENCAO_NATUREZA_CODRET`).
- **Retenções x Financeiro**: aba de validação que confere, para cada título
  com retenção, se cada tributo (IR/PIS/COFINS/CSLL) já foi gerado como um
  título "irmão" de taxa na própria SE2010 (mesmo FILIAL+PREFIXO+NÚMERO do
  título original, `E2_TIPO='TX'`) e se já foi baixado - descoberta
  confirmada ao vivo com o cliente em 25/08/2026 (o Protheus não baixa a
  retenção como movimento em SEF010; ele gera um segundo título com baixa
  própria e independente da baixa do título original). Status 🟢 OK /
  🔵 Aguardando baixa (gerado, valor batendo, falta só pagar - não é
  problema) / 🟡 Divergente / 🔴 Não gerado, com filtro e export
  **CSV/Excel**.
- Tratamento de erros amigável, log técnico e cache de 5 minutos.
- Código modularizado, pronto para novos indicadores.

## Requisitos

- Python 3.11 ou superior.
- Driver ODBC do SQL Server instalado no ambiente (ex.: "ODBC Driver 18 for SQL Server").
- Usuário do SQL Server com permissão **somente de leitura**.

## Instalação

```bash
cd Fiscal
pip install -r requirements.txt
copy .env.example .env
```

Edite o `.env` com os dados reais da conexão.

## Execução

```bash
streamlit run app.py
```

## Estrutura do projeto

```
Fiscal/
|
|-- app.py                    # Interface Streamlit (filtros, abas, cards, mensagens)
|-- config/
|   |-- settings.py           # Configurações via .env
|-- database/
|   |-- connection.py         # Conexão SQL Server (única responsável)
|   |-- queries.py            # Consultas SQL parametrizadas (fiscal)
|   |-- conciliacao_queries.py# Consultas SQL da conciliação (CT2)
|   |-- anotacoes_db.py       # Armazenamento local (SQLite) das anotações por documento
|-- services/
|   |-- fiscal_service.py     # Executa consultas, transforma dados e calcula KPIs
|   |-- conciliacao_service.py# Motor de conciliação Fiscal x Contábil (CT2)
|   |-- qualidade_service.py  # Checklist de qualidade dos dados
|   |-- alertas_service.py    # Alertas visuais (semáforo) a partir dos dados já calculados
|   |-- anotacoes_service.py  # Anotações locais por documento
|   |-- pdf_service.py        # Gera o relatório em PDF (reportlab)
|   |-- retencao_service.py   # Retenções IR/PIS/COFINS/CSLL (SE2 - contas a pagar)
|-- utils/
|   |-- formatters.py         # Formatação de moeda, quantidade e data
|   |-- logger.py             # Configuração de logging (logs/dashboard.log)
|-- .env.example              # Modelo de configuração (copiar para .env)
|-- .gitignore
|-- requirements.txt
|-- iniciar_dashboard_fiscal.bat
|-- README.md
```

## Configuração (`.env`)

```dotenv
DB_SERVER=SERVIDOR_SQL
DB_DATABASE=PROTHEUS
DB_USER=usuario_dashboard
DB_PASSWORD=troque_esta_senha
DB_DRIVER=ODBC Driver 18 for SQL Server

# Tabelas físicas do Protheus (configuráveis)
TABELA_NF_ENTRADA=SF1010
TABELA_NF_SAIDA=SF2010
TABELA_EMPRESAS=SM0010
TABELA_CLIENTES=SA1010
TABELA_FORNECEDORES=SA2010

# Conciliação Fiscal x Contábil (CT2)
TABELA_CT2=CT2010
CT2_ORIGEM_ENTRADA=
CT2_ORIGEM_SAIDA=
CT2_FILTRO_DC=
CT2_EXIGIR_PARCEIRO=true
CT2_DOC_VIA_KEY=false
CT2_ROTINA_ENTRADA=
CT2_ROTINA_SAIDA=
TOLERANCIA_CONCILIACAO=0.05
CT2_ORIGEM_ROTULOS=

# CFOP e cancelamento (apuração fiscal)
CAMPO_CFOP_ENTRADA=D1_CF
CAMPO_CFOP_SAIDA=D2_CF
STATUS_CANCELADO_ENTRADA=
STATUS_CANCELADO_SAIDA=

# Alertas visuais (semáforo)
ALERTA_PCT_CONCILIACAO_MIN=0.80
ALERTA_IDADE_PENDENCIA_DIAS=30
ALERTA_SALDO_ICMS_CREDITO=true
ALERTA_SALDO_ICMS_MAX=

# Retenções (IR/PIS/COFINS/CSLL) - aba "Retenções" (Reinf R-4020)
TABELA_CP=SE2010
CAMPO_CNPJ_FORNECEDOR=A2_CGC
RETENCAO_NATUREZA_CODRET=

# Validação Retenções x Financeiro - aba "Retenções x Financeiro"
# Não usa mais SEF010 (o vínculo agora é dentro da própria SE2010, ver
# seção 12 da documentação) - TABELA_FINANCEIRO mantida só por
# compatibilidade com .env já configurado, não é mais lida pelo código.
TABELA_FINANCEIRO=SEF010

# Anotações locais por documento (não é enviado ao Protheus)
ANOTACOES_DB=anotacoes.db
```

O `.env` **não** deve ser versionado. As tabelas físicas podem variar de
instalação para instalação (ex.: `SF1010`, `SF2010`, `SFT010`).

## Tabelas e campos utilizados

| Tabela | Descrição | Campos usados |
|---|---|---|
| SF1 (`TABELA_NF_ENTRADA`) | Cabeçalho de notas de entrada | `F1_FILIAL`, `F1_EMISSAO`, `F1_VALBRUT`, `F1_VALICM` |
| SF2 (`TABELA_NF_SAIDA`) | Cabeçalho de notas de saída | `F2_FILIAL`, `F2_EMISSAO`, `F2_VALBRUT`, `F2_VALICM` |
| SD1 (`TABELA_ITEM_ENTRADA`) | Itens de nota de entrada (IBS/CBS, PIS/COFINS, CFOP) | `D1_IDTRIB`, `D1_DOC`, `D1_SERIE`, `D1_EMISSAO`, `D1_BASEPIS`, `D1_VALPIS`, `D1_BASECOF`, `D1_VALCOF`, `D1_CF` (CFOP, configurável) |
| SD2 (`TABELA_ITEM_SAIDA`) | Itens de nota de saída (IBS/CBS, PIS/COFINS, CFOP) | `D2_IDTRIB`, `D2_DOC`, `D2_SERIE`, `D2_EMISSAO`, `D2_BASEPIS`, `D2_VALPIS`, `D2_BASECOF`, `D2_VALCOF`, `D2_CF` (CFOP, configurável) |
| F2D (`TABELA_F2D`) | Tributos genéricos calculados (IBS/CBS) | `F2D_TRIB`, `F2D_BASE`, `F2D_ALIQ`, `F2D_VALOR`, `F2D_IDREL` |
| SM0 (`TABELA_EMPRESAS`) | Empresas e filiais | `M0_CODIGO`, `M0_CODFIL`, `M0_FANTASIA`, `M0_NOME` |
| SA1 (`TABELA_CLIENTES`) | Clientes (descrição) | `A1_COD`, `A1_LOJA`, `A1_NOME` |
| SA2 (`TABELA_FORNECEDORES`) | Fornecedores (descrição) | `A2_COD`, `A2_LOJA`, `A2_NOME` |
| CT2 (`TABELA_CT2`) | Lançamentos contábeis (conciliação) | `CT2_FILIAL`, `CT2_DOC`, `CT2_ORIGEM`, `CT2_DATA`, `CT2_LOTE`, `CT2_DC`, `CT2_VALOR`, `CT2_CODPAR`, `CT2_CODCLI`, `CT2_CODFOR` |
| SE2 (`TABELA_CP`) | Contas a pagar (retenções IR/PIS/COFINS/CSLL) | `E2_FILIAL`, `E2_PREFIXO`, `E2_NUM`, `E2_PARCELA`, `E2_FORNECE`, `E2_NOMFOR`, `E2_NATUREZ`, `E2_EMISSAO`, `E2_VENCTO`, `E2_BASEIRF`, `E2_IRRF`, `E2_BASEPIS`, `E2_PIS`, `E2_BASECOF`, `E2_COFINS`, `E2_BASECSL`, `E2_CSLL` |

> **Conciliação Fiscal x Contábil (CT2):** a aba compara os documentos fiscais
> (SF1/SF2) com os lançamentos contábeis (CT2) aplicando a regra em níveis:
> vínculo exato -> **Conciliado**; documento encontrado com valor diferente ->
> **Divergente**; documento fiscal sem lançamento -> **Não contabilizado**;
> lançamento sem documento fiscal -> **Sem origem fiscal**. O lado contábil é
> agregado por documento. **Nesta instalação (Biocaz), `CT2_DOC` não é o
> número da nota** (é uma numeração interna do lançamento) - o vínculo usa o
> número real embutido no campo `CT2_KEY` (`CT2_DOC_VIA_KEY=true`), validado
> em 14/08/2026 com 5 lançamentos reais de saída (`CT2_ROTINA=MATA460`). O
> vínculo por parceiro está desligado (`CT2_EXIGIR_PARCEIRO=false`) porque
> `CT2_CODPAR`/`CODCLI`/`CODFOR` ficam em branco aqui. Ver DOCUMENTACAO.md,
> seção 12, para os detalhes e o que falta validar (entrada ainda não tem
> lançamento real conferido). Como a base está em implantação, revalide tudo
> após o GO LIVE. Nesta instalação **não
> existem** `LCT100`/`LCT200`.

> **Fornecedores e clientes:** o detalhamento exibe o parceiro no formato
> "código - nome". Fornecedores (entradas) são lidos de SA2 e clientes
> (saídas) de SA1. A filial do cadastro corresponde aos 4 primeiros dígitos
> da filial da nota (ex.: `010101` -> `0101`). Se o cadastro não existir,
> o app exibe apenas o código. O filtro de fornecedor usa `F1_FORNECE` e
> afeta as entradas (cards, IBS/CBS de entrada, detalhamento e conciliação);
> o filtro de cliente usa `F2_CLIENTE` e afeta as saídas (faturamento, IBS/CBS
> de saída, detalhamento e conciliação). Assim, o cartão **Faturamento** só
> responde a filial/período/cliente, nunca ao fornecedor.

> **IBS/CBS:** calculados pelo Configurador de Tributos e gravados em F2D,
> vinculados ao item da nota por `F2D_IDREL = D1_IDTRIB/D2_IDTRIB`. IBS e CBS
> são diferenciados pelo código do tributo (`F2D_TRIB`) — configuráveis no `.env`
> (`COD_TRIB_IBS_ENTRADA/SAIDA`, `COD_TRIB_CBS_ENTRADA/SAIDA`).

> **Conciliação em implantação:** na base de homologação a CT2 está praticamente
> vazia (lançamentos de teste com `CT2_ORIGEM` em branco), por isso a aba mostra
> quase tudo como "Não contabilizado". Após o GO LIVE, aponte o `.env` para o
> ambiente de produção e valide a chave de vínculo e o filtro `CT2_DC`.

> **Importante:** valide os campos no dicionário de dados (SX3) da instalação
> antes de implantar. Campos ainda não confirmados estão marcados como `TODO`
> no código e devem ser ajustados conforme a instalação.

> **Filiais:** a lista de empresas/filiais é carregada do SM0 (`TABELA_EMPRESAS`).
> Quando o SM0 não existe ou não é acessível na instalação, o dashboard usa como
> fallback as filiais encontradas diretamente nas notas (SF1/SF2). Em instalações
> TCloud, o código da filial pode ter 6 dígitos (ex.: `010101`).

Todas as consultas ignoram registros deletados logicamente (`D_E_L_E_T_ = ''`)
e os filtros são enviados via parâmetros (sem concatenação).

## Indicadores calculados

| Indicador | Fórmula |
|---|---|
| Saldo de ICMS | `ICMS_SAIDA - ICMS_ENTRADA` |
| Ticket médio | `VALOR_NF_SAIDA / QTD_NF_SAIDA` (evita divisão por zero) |

> Os indicadores desta versão são **gerenciais**. Cancelamento de notas **não**
> é tratado por `D_E_L_E_T_`; para apuração oficial utilize futuramente a
> escrituração da SFT (ver roadmap).
>
> **CFOP:** não existe `D1_CFOP`/`D2_CFOP` nesta instalação - o campo real é
> `D1_CF`/`D2_CF` (configurável via `CAMPO_CFOP_ENTRADA/SAIDA`), validado com
> valores reais em 21/08/2026.
>
> **PIS/COFINS:** campos nativos de SD1/SD2 (não passam pelo F2D). COFINS
> truncado para "COF" nesta instalação (`D1/D2_BASECOF`, `VALCOF`, `ALQCOF`).
>
> **Notas canceladas:** `F1_STATUS`/`F2_STATUS` existem, mas o valor de
> "cancelada" ainda não foi confirmado (sem exemplo real na base). O filtro
> `STATUS_CANCELADO_ENTRADA/SAIDA` fica desligado até você configurar.
>
> **Retenções (SE2):** valor retido = `E2_IRRF`/`E2_PIS`/`E2_COFINS`/`E2_CSLL`
> - validado recalculando as alíquotas padrão (1,5% IR, 0,65% PIS, 3% COFINS,
> 1% CSLL) contra 2 títulos reais em 25/08/2026. **Não** usa
> `E2_VRETIRF`/`E2_VRETPIS`/`E2_VRETCOF`/`E2_VRETCSL` (ficaram zerados em
> todos os títulos testados). O "Cod. R" (natureza de rendimento do Reinf)
> não existe em nenhuma tabela do banco - fica em branco até configurar
> `RETENCAO_NATUREZA_CODRET`. `CAMPO_CNPJ_FORNECEDOR` (`A2_CGC`) ainda não
> foi validado nesta instalação.
>
> **Retenções x Financeiro:** REDESENHADA DUAS VEZES em 25/08/2026 após
> dois testes ao vivo do cliente - não usa mais SEF010. O Protheus grava
> cada retenção como OUTRO TÍTULO na própria SE2010, por **dois padrões**
> confirmados nesta instalação: **Padrão A** - título "irmão" com o mesmo
> FILIAL+PREFIXO+NÚMERO do original (`E2_TIPO='TX'`, tributo em
> `E2_NATUREZ`) - confirmado no título 000000002-1. **Padrão B** - título
> com numeração própria (prefixo "TG", gerado pela rotina `MATA100`),
> tributo direto em `E2_TIPO`, **sem nenhum campo estruturado** de vínculo
> com o original - só o texto do Histórico ("... NF: `<número>` /
> `<série>`") liga de volta - confirmado no título NFS58-01. Cada título
> tem baixa própria e independente da baixa do título original. Ver
> DOCUMENTACAO.md, seção 12, para os detalhes completos, inclusive o
> risco assumido do vínculo por texto (Padrão B) depender do formato do
> Histórico se manter estável. Ainda não confirmado: títulos com mais de
> uma parcela, e a lista completa de códigos de tributo usados.

## Segurança

- Usuário SQL somente leitura.
- Senhas somente no `.env` (fora do código e do versionamento).
- Consultas 100% parametrizadas.
- Nomes de tabela configuráveis e validados (sem interpolação de entrada do usuário).
- Erros técnicos registrados em `logs/dashboard.log` sem credenciais.

## Performance

- Consulta dos cards com CTEs + `CROSS JOIN` (evita múltiplos subselects).
- Filtros aplicados por faixa (`BETWEEN`) no campo de emissão sem conversão.
- Cache Streamlit (TTL 5 min) para evitar consultas repetidas.
- Antes de produção, verifique índices em filial e data de emissão.

## Roadmap

- **Entrega 2:** gráficos (faturamento mensal, entrada x saída, ICMS entrada x
  saída), comparativo por filial e tabela de documentos. ✅ Concluído -
  inclui também export CSV/Excel, visão consolidada multi-filial, checklist
  de qualidade e anotações locais (ver seção "Melhorias" no DOCUMENTACAO.md).
  - **Conciliação Fiscal x Contábil (CT2):** estrutura já criada (aba própria,
    status, drill-down e análise por período). Após o GO LIVE, validar a chave
    de vínculo (`CT2_DOC` + parceiro + `CT2_ORIGEM`) e o filtro `CT2_DC` no `.env`.
- **Entrega 3:** CFOP, PIS/COFINS e filtro opcional de notas canceladas. ✅
  Concluído em 21/08/2026 - CFOP (`D1_CF`/`D2_CF`) e PIS/COFINS confirmados
  com valores reais; o valor de "cancelada" em `F1_STATUS`/`F2_STATUS`
  ainda não foi confirmado (filtro desligado por padrão - ver seção
  "Melhorias" no DOCUMENTACAO.md).
  Relatório automático por e-mail e apuração via SFT ficam para uma etapa
  posterior.
- **Entrega 4:** relatório em PDF com PIS/COFINS, evolução mensal
  (comparativo mês a mês / ano a ano) e alertas visuais (semáforo). ✅
  Concluído em 21/08/2026.
- **Entrega 5:** aba **Retenções** (IR/PIS/COFINS/CSLL sobre pagamentos a
  fornecedores PJ - contas a pagar/SE2), equivalente ao relatório Reinf
  R-4020. ✅ Concluído em 25/08/2026 - valor retido confirmado com valores
  reais; o "Cod. R" (natureza de rendimento) não existe em nenhuma tabela
  do banco, fica disponível via mapeamento manual opcional no `.env`.
- **Entrega 6:** aba **Retenções x Financeiro** - valida se cada retenção já
  foi gerada como título de taxa no Financeiro. ✅ Concluído e REDESENHADO
  em 25/08/2026 (mesmo dia, após teste ao vivo do cliente) - vínculo é um
  self join na própria SE2010 (título original x título "irmão" com
  `E2_TIPO='TX'`), não SE2 x SEF010 como na primeira versão - ver seção
  "Melhorias" no DOCUMENTACAO.md.

## Como adicionar um novo indicador

1. Adicione a coluna na consulta em `database/queries.py` (ou um novo SQL).
2. Calcule/transforme o valor em `services/fiscal_service.py`.
3. Exiba o novo card em `app.py`.
