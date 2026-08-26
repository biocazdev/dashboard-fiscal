# Documentação Técnica — Dashboard Fiscal Protheus

Dashboard fiscal para consulta de indicadores do ERP **TOTVS Protheus**,
construído em **Python + Streamlit**, conectando-se diretamente ao banco
**SQL Server** do ambiente (somente leitura).

---

## 1. Visão geral

O dashboard consulta cabeçalhos de notas fiscais de entrada (SF1) e saída
(SF2), itens (SD1/SD2) e tributos calculados (F2D) para apresentar, em tempo
real:

- **Movimentação** — Faturamento, Entradas, Notas de Saída/Entrada e Ticket Médio.
- **Tributos** — ICMS Saída/Entrada, Saldo de ICMS e **IBS/CBS** (reforma
  tributária, via Configurador de Tributos).
- **Detalhamento** — lista das notas que compõem os indicadores.
- **Relatório em PDF** — botão na barra lateral para gerar o relatório com a
  mesma estrutura visual do dashboard.

Todos os valores são **gerenciais**: servem para acompanhamento e conferência,
não substituem a apuração oficial (escrituração).

---

## 2. Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| Filtros | Empresa, filial, período (por data de emissão), **fornecedor** (entradas) e **cliente** (saídas) |
| Cards por bloco | "Movimentação" e "Tributos" com ícones |
| Período inteligente | Datas padrão = período disponível no banco |
| Atualizar | Limpa o cache para buscar dados novos |
| Abas | "📊 Visão Geral", "🔄 Conciliação Fiscal x Contábil", "📄 Documentos", "🧾 Retenções" e "🏦 Retenções x Financeiro" |
| Detalhamento | Aba "Documentos" com a lista de notas + download CSV |
| Conciliação CT2 | Aba própria com barra de progresso, status, drill-down e análise por período (ver seção 12) |
| Retenções (Reinf R-4020) | Aba própria com os títulos de contas a pagar (SE2) com retenção de IR/PIS/COFINS/CSLL, export CSV/Excel (ver seção 12) |
| Retenções x Financeiro | Aba de validação: confere se cada retenção já foi gerada como título de taxa na SE2010 (mesmo número do título original, `E2_TIPO='TX'`) e se já foi baixada, com status 🟢/🔵/🟡/🔴, filtro e export CSV/Excel (ver seção 12) |
| Relatório PDF | Geração sob demanda com estrutura do dashboard |
| Cache | 5 min (indicadores/detalhamento/conciliação), 10 min (empresas/filiais/período) |
| Logs | `logs/dashboard.log` com rotação automática (5 MB × 3 backups) |
| Erros amigáveis | Mensagens na tela sem expor detalhes técnicos ou credenciais |

---

## 3. Arquitetura

Aplicação em camadas para separar interface, dados e regras:

```
app.py                      Interface Streamlit (filtros, abas, cards, PDF)
  │
  ├── services/
  │   ├── fiscal_service.py     Busca dados no banco e calcula os indicadores
  │   ├── conciliacao_service.py Motor de conciliação Fiscal x Contábil (CT2)
  │   ├── retencao_service.py   Retenções IR/PIS/COFINS/CSLL (SE2) e validação x Financeiro (SEF)
  │   └── pdf_service.py        Gera o relatório PDF (reportlab)
  ├── database/
  │   ├── connection.py         Única responsável por abrir conexões (pyodbc)
  │   ├── queries.py            Consultas SQL parametrizadas (fiscal)
  │   └── conciliacao_queries.py Consultas SQL da conciliação (CT2)
  ├── config/
  │   └── settings.py           Configurações centralizadas (via .env)
  └── utils/
      ├── formatters.py         Formatação de moeda, quantidade e data (pt-BR)
      └── logger.py             Logging com rotação (logs/dashboard.log)
```

### Fluxo de execução

1. A **sidebar** carrega empresas e filiais (SM0; fallback para SF1/SF2),
   o período disponível da filial e os filtros.
2. Com filial + período definidos, `fiscal_service.buscar_indicadores`
   executa a consulta de cards (`SQL_INDICADORES`) e as consultas de
   IBS/CBS (`SQL_IBS_CBS_*`).
3. Os valores são formatados e exibidos em dois blocos de cards.
4. O **detalhamento** é carregado sob demanda dentro do expander.
5. O **PDF** é gerado sob demanda a partir dos dados já carregados.

---

## 4. Requisitos

- Python 3.11 ou superior (validado com 3.14).
- Driver ODBC do SQL Server (ex.: "ODBC Driver 18 for SQL Server").
- Usuário do SQL Server com permissão **somente de leitura**.
- Dependências em `requirements.txt`.

```
streamlit>=1.30.0
pandas>=2.0.0
pyodbc>=5.0.0
python-dotenv>=1.0.0
plotly>=5.15.0
reportlab>=4.0.0
```

---

## 5. Instalação

```powershell
cd C:\LDO\Fiscal
pip install -r requirements.txt
copy .env.example .env
```

Edite o `.env` com os dados reais da conexão (ver seção 6).

---

## 6. Configuração (`.env`)

O arquivo `.env` **não** deve ser versionado (está no `.gitignore`).

### Conexão SQL Server

| Variável | Descrição | Exemplo |
|---|---|---|
| `DB_SERVER` | Servidor + porta | `tcp:181.41.163.164,10472` |
| `DB_DATABASE` | Base de dados do Protheus | `C58SCI_213233_PR_PD` |
| `DB_USER` | Usuário somente leitura | `PRODLEITURA` |
| `DB_PASSWORD` | Senha | — |
| `DB_DRIVER` | Driver ODBC | `ODBC Driver 18 for SQL Server` |
| `DB_TIMEOUT` | Timeout de conexão (s) | `15` |

### Tabelas físicas (sufixo da instalação)

As tabelas do Protheus levam o sufixo do ambiente (ex.: `SF1010` = `SF1` + `010`).
Confirme no dicionário SX3 da instalação.

| Variável | Padrão | Descrição |
|---|---|---|
| `TABELA_NF_ENTRADA` | `SF1010` | Cabeçalho de notas de entrada |
| `TABELA_NF_SAIDA` | `SF2010` | Cabeçalho de notas de saída |
| `TABELA_ITEM_ENTRADA` | `SD1010` | Itens de entrada (IBS/CBS) |
| `TABELA_ITEM_SAIDA` | `SD2010` | Itens de saída (IBS/CBS) |
| `TABELA_F2D` | `F2D010` | Tributos genéricos calculados |
| `TABELA_EMPRESAS` | `SM0010` | Empresas e filiais |
| `TABELA_CLIENTES` | `SA1010` | Cadastro de clientes (descrição) |
| `TABELA_FORNECEDORES` | `SA2010` | Cadastro de fornecedores (descrição) |
| `TABELA_CT2` | `CT2010` | Lançamentos contábeis (conciliação) |

> Se o SM0 não existir ou não estiver acessível, o app **deriva automaticamente**
> as filiais das notas (SF1/SF2) e não interrompe o funcionamento.
> Se SA1/SA2 não existirem, o app exibe apenas o código do parceiro (fallback).

### Conciliação Fiscal x Contábil (CT2)

| Variável | Padrão | Descrição |
|---|---|---|
| `TABELA_CT2` | `CT2010` | Tabela física de lançamentos contábeis |
| `CT2_ORIGEM_ENTRADA` | (vazio) | Códigos de `CT2_ORIGEM` das entradas (ex.: `SE2`), separados por vírgula |
| `CT2_ORIGEM_SAIDA` | (vazio) | Códigos de `CT2_ORIGEM` das saídas (ex.: `SE1`), separados por vírgula |
| `CT2_FILTRO_DC` | (vazio) | Filtrar linhas por `CT2_DC`; vazio = todas |
| `TOLERANCIA_CONCILIACAO` | `0.05` | Tolerância absoluta (R$) para considerar um documento conciliado |

> **Implantação:** a base está em homologação e a CT2 ainda não tem dados reais.
> A chave de vínculo e o filtro `CT2_DC` devem ser validados após o GO LIVE
> (ver seção 12). Nesta instalação não existem `LCT100`/`LCT200`.

### IBS/CBS (reforma tributária)

IBS e CBS são gravados pelo **Configurador de Tributos** na tabela **F2D**,
diferenciados pelo código do tributo (`F2D_TRIB`), e não por campos separados
na SF1/SF2.

| Variável | Padrão | Observação |
|---|---|---|
| `COD_TRIB_IBS_ENTRADA` | `EIBS01` | Código IBS nas entradas |
| `COD_TRIB_CBS_ENTRADA` | `ECBS01` | Código CBS nas entradas |
| `COD_TRIB_IBS_SAIDA` | `SIBS01` | Código IBS nas saídas |
| `COD_TRIB_CBS_SAIDA` | `SCBS01` | Código CBS nas saídas |

Ajuste os códigos conforme o cadastro de tributos da instalação. Códigos sem
registros retornam R$ 0,00 (sem erro).

### Retenções (IR/PIS/COFINS/CSLL) — aba "Retenções"

| Variável | Padrão | Descrição |
|---|---|---|
| `TABELA_CP` | `SE2010` | Tabela física de contas a pagar |
| `CAMPO_CNPJ_FORNECEDOR` | `A2_CGC` | Campo de CNPJ/CPF no cadastro de fornecedores (SA2) - **não validado** nesta instalação |
| `RETENCAO_NATUREZA_CODRET` | (vazio) | Mapeamento manual `NATUREZA:CODIGO,...` de `E2_NATUREZ` para o "Cod. R" do Reinf - vazio = coluna em branco |

> O "Cod. R" (natureza de rendimento do Reinf, ex.: `15014`) **não existe em
> nenhuma tabela acessível pelo banco** desta instalação - ver seção 12 para
> os detalhes da investigação e o exemplo de preenchimento.

### Retenções x Financeiro — aba "Retenções x Financeiro"

| Variável | Padrão | Descrição |
|---|---|---|
| `TABELA_FINANCEIRO` | `SEF010` | **Não usada mais** por esta validação (mantida por compatibilidade com `.env` já configurado) |

> A validação faz um SELF JOIN na própria SE2010: cada retenção
> (IR/PIS/COFINS/CSLL) é gerada pelo Protheus como um título "irmão" na
> SE2010 (mesmo FILIAL+PREFIXO+NÚMERO do título original, `E2_TIPO='TX'`,
> `E2_NATUREZ` = código do tributo), com baixa própria e independente da
> baixa do título original. Ver seção 12 ("Redesenho do vínculo Retenções
> x Financeiro") para os detalhes completos e a descoberta que motivou a
> mudança.

---

## 7. Execução

### Local (modo de desenvolvimento)

```powershell
cd C:\LDO\Fiscal
C:\LDO\.venv\Scripts\python.exe -m streamlit run app.py
```

### Atalho do Windows

O arquivo `iniciar_dashboard_fiscal.bat` inicia o dashboard usando o Python do
ambiente virtual (`C:\LDO\.venv`).

---

## 8. Tabelas e campos utilizados

| Tabela | Descrição | Campos usados |
|---|---|---|
| SF1 (`TABELA_NF_ENTRADA`) | Cabeçalho de entrada | `F1_FILIAL`, `F1_EMISSAO`, `F1_DOC`, `F1_SERIE`, `F1_FORNECE`, `F1_LOJA`, `F1_VALBRUT`, `F1_VALICM`, `D_E_L_E_T_` |
| SF2 (`TABELA_NF_SAIDA`) | Cabeçalho de saída | `F2_FILIAL`, `F2_EMISSAO`, `F2_DOC`, `F2_SERIE`, `F2_CLIENTE`, `F2_LOJA`, `F2_VALBRUT`, `F2_VALICM`, `D_E_L_E_T_` |
| SD1 (`TABELA_ITEM_ENTRADA`) | Itens de entrada | `D1_IDTRIB`, `D1_FILIAL`, `D1_DOC`, `D1_SERIE`, `D1_EMISSAO`, `D_E_L_E_T_` |
| SD2 (`TABELA_ITEM_SAIDA`) | Itens de saída | `D2_IDTRIB`, `D2_FILIAL`, `D2_DOC`, `D2_SERIE`, `D2_EMISSAO`, `D_E_L_E_T_` |
| F2D (`TABELA_F2D`) | Tributos calculados | `F2D_TRIB`, `F2D_BASE`, `F2D_ALIQ`, `F2D_VALOR`, `F2D_IDREL`, `F2D_TABELA`, `D_E_L_E_T_` |
| SM0 (`TABELA_EMPRESAS`) | Empresas/filiais | `M0_CODIGO`, `M0_CODFIL`, `M0_FANTASIA`, `M0_NOME`, `D_E_L_E_T_` |
| SA1 (`TABELA_CLIENTES`) | Clientes (descrição) | `A1_FILIAL`, `A1_COD`, `A1_LOJA`, `A1_NOME`, `D_E_L_E_T_` |
| SA2 (`TABELA_FORNECEDORES`) | Fornecedores (descrição) | `A2_FILIAL`, `A2_COD`, `A2_LOJA`, `A2_NOME`, `D_E_L_E_T_` |
| SE2 (`TABELA_CP`) | Contas a pagar (retenções) | `E2_FILIAL`, `E2_PREFIXO`, `E2_NUM`, `E2_PARCELA`, `E2_FORNECE`, `E2_NOMFOR`, `E2_NATUREZ`, `E2_EMISSAO`, `E2_VENCTO`, `E2_BAIXA`, `E2_VALOR`, `E2_BASEIRF`, `E2_IRRF`, `E2_BASEPIS`, `E2_PIS`, `E2_BASECOF`, `E2_COFINS`, `E2_BASECSL`, `E2_CSLL`, `D_E_L_E_T_` |
| SEF (`TABELA_FINANCEIRO`) | Movimento financeiro (baixas) | `EF_FILIAL`, `EF_PREFIXO`, `EF_TITULO`, `EF_PARCELA`, `EF_FORNECE`, `EF_VALOR`, `D_E_L_E_T_` |

### Parceiros (fornecedores e clientes)

- O detalhamento exibe o parceiro como **"código - nome"**: fornecedores
  (entradas) de SA2 e clientes (saídas) de SA1.
- A filial do cadastro (SA1/SA2) corresponde aos **4 primeiros dígitos** da
  filial da nota (ex.: nota `010101` → cadastro `0101`).
- O join usa `RTRIM` no código e na loja para ignorar preenchimentos.
- **Filtro de fornecedor:** usa `F1_FORNECE` das notas de entrada e afeta
  apenas as entradas (cards de entrada, IBS/CBS de entrada e linhas de
  entrada do detalhamento).
- **Filtro de cliente:** usa `F2_CLIENTE` das notas de saída e afeta apenas
  as saídas (faturamento, IBS/CBS de saída e linhas de saída do detalhamento).
  O cartão **Faturamento** só responde a filial/período/cliente.

### Exclusão lógica (D_E_L_E_T_)

Todas as consultas ignoram registros deletados logicamente
(`D_E_L_E_T_ = ''`). No SQL Server, registros ativos podem vir como `' '`
(espaço) — a comparação com `''` os considera iguais, então ambos funcionam.

> **Atenção:** `D_E_L_E_T_` **não** identifica nota cancelada. O campo correto
> é `F1_STATUS`/`F2_STATUS`, mas o valor que representa cancelamento ainda
> não foi confirmado nesta instalação - ver seção "Grupo B: CFOP, PIS/COFINS
> e notas canceladas" (item 12) para o filtro opcional
> `STATUS_CANCELADO_ENTRADA/SAIDA`.

---

## 9. Indicadores e regras de negócio

> Todos os indicadores do dashboard são **gerenciais**, baseados em SF1
> (entradas) e SF2 (saídas). Antes de usar para apuração oficial, valide os
> campos no dicionário de dados (SX3) da instalação Protheus.

| Indicador | Origem / Fórmula |
|---|---|
| Notas de Saída (qtd) | `COUNT(*)` de SF2 no período |
| Notas de Entrada (qtd) | `COUNT(*)` de SF1 no período |
| Faturamento | `SUM(F2_VALBRUT)` |
| Entradas | `SUM(F1_VALBRUT)` |
| ICMS Saída | `SUM(F2_VALICM)` |
| ICMS Entrada | `SUM(F1_VALICM)` |
| Saldo de ICMS | `ICMS_SAIDA - ICMS_ENTRADA` |
| Ticket Médio | `VALOR_NF_SAIDA / QTD_NF_SAIDA` (evita divisão por zero) |
| IBS Saída | `SUM(F2D_VALOR)` onde `F2D_TRIB = COD_TRIB_IBS_SAIDA` |
| CBS Saída | `SUM(F2D_VALOR)` onde `F2D_TRIB = COD_TRIB_CBS_SAIDA` |
| IBS Entrada | `SUM(F2D_VALOR)` onde `F2D_TRIB = COD_TRIB_IBS_ENTRADA` |
| CBS Entrada | `SUM(F2D_VALOR)` onde `F2D_TRIB = COD_TRIB_CBS_ENTRADA` |

A consulta de cards usa **CTEs + CROSS JOIN** para obter entradas e saídas em
uma única execução (sem múltiplos subselects).

---

## 10. O que cada cartão mostra

Os cartões são agrupados em dois blocos: **Movimentação** e **Tributos**. Todos
os valores refletem a filial e o período selecionados. O filtro de **fornecedor**
afeta apenas os cartões de entrada; o filtro de **cliente** afeta apenas os
cartões de saída.

### Bloco "Movimentação"

| Cartão | O que significa | Origem | Fornecedor | Cliente |
|---|---|---|---|---|
| 💰 Faturamento | Soma do valor bruto das notas de **saída** no período — o total faturado/emitido em vendas. | `SUM(F2_VALBRUT)` da SF2 | Não | Sim |
| 🛒 Entradas | Soma do valor bruto das notas de **entrada** (compras) no período. | `SUM(F1_VALBRUT)` da SF1 | Sim | Não |
| 🚚 Notas de Saída | Quantidade de notas de saída emitidas no período. | `COUNT(*)` da SF2 | Não | Sim |
| 📦 Notas de Entrada | Quantidade de notas de entrada registradas no período. | `COUNT(*)` da SF1 | Sim | Não |
| 📊 Ticket Médio | Valor médio por nota de saída emitida (Faturamento ÷ Notas de Saída). Baseado apenas nas saídas. | `VALOR_NF_SAIDA / QTD_NF_SAIDA` | Não | Sim |

### Bloco "Tributos"

| Cartão | O que significa | Origem | Fornecedor | Cliente |
|---|---|---|---|---|
| 🧾 ICMS Saída | ICMS informado nas notas de **saída** do período (débito). | `SUM(F2_VALICM)` da SF2 | Não | Sim |
| 🧾 ICMS Entrada | ICMS informado nas notas de **entrada** do período (crédito presumível). | `SUM(F1_VALICM)` da SF1 | Sim | Não |
| ⚖️ Saldo de ICMS | ICMS Saída **menos** ICMS Entrada. Positivo = débito a pagar no período; negativo = crédito acumulado. | `ICMS_SAIDA - ICMS_ENTRADA` | Parcial | Parcial |
| 🏛️ IBS Saída | IBS calculado pelo **Configurador de Tributos** nas saídas do período. | `SUM(F2D_VALOR)` da F2D (código de saída) | Não | Sim |
| 🏦 CBS Saída | CBS calculado pelo **Configurador de Tributos** nas saídas do período. | `SUM(F2D_VALOR)` da F2D (código de saída) | Não | Sim |
| 🏛️ IBS Entrada | IBS calculado pelo **Configurador de Tributos** nas entradas do período. | `SUM(F2D_VALOR)` da F2D (código de entrada) | Sim | Não |
| 🏦 CBS Entrada | CBS calculado pelo **Configurador de Tributos** nas entradas do período. | `SUM(F2D_VALOR)` da F2D (código de entrada) | Sim | Não |

### Observações importantes

- **Sinal do Saldo de ICMS:** o cartão não tem semáforo de cor; interprete pelo
  sinal do valor (positivo = a pagar, negativo = crédito). É um indicador
  **gerencial**, não substitui a apuração/escrituração oficial.
- **IBS/CBS zerados:** quando a instalação não utiliza o Configurador de
  Tributos, ou os códigos `COD_TRIB_*` do `.env` não correspondem ao cadastro,
  os cartões exibem R$ 0,00 (sem erro). Ver seção 6 (configuração) e 15
  (solução de problemas).
- **Ícones:** 🏛️ identifica IBS e 🏦 identifica CBS, 📗 identifica PIS e 📘
  identifica COFINS, diferenciando os tributos dentro do bloco "Tributos".
- **PIS/COFINS zerados:** campos nativos de SD1/SD2 (`D1/D2_BASEPIS`,
  `VALPIS`, `BASECOF`, `VALCOF`) - se vierem zerados, confira se os nomes
  batem com o dicionário (SX3) da instalação (nesta o COFINS é truncado
  para "COF", não "COFINS").
- **Notas canceladas:** por padrão os valores consideram todas as notas não
  deletadas logicamente (`D_E_L_E_T_`), sem excluir canceladas - o valor de
  cancelamento em `F1_STATUS`/`F2_STATUS` ainda não foi confirmado nesta
  instalação. Filtro opcional em `STATUS_CANCELADO_ENTRADA/SAIDA` (ver
  seção 12, "Grupo B").

---

## 11. IBS/CBS — detalhamento técnico

O **Configurador de Tributos** do Protheus grava cada cálculo em **F2D**
(`F2D_TRIB`, `F2D_BASE`, `F2D_ALIQ`, `F2D_VALOR`) e vincula ao item da nota
pelo relacionamento documentado pela TOTVS:

```
SD1/SD2 (item)
   │  D1_IDTRIB / D2_IDTRIB
   ▼
SFT (livro fiscal, FT_IDTRIB)
   ▼
CJ3 (escrituração por item, CJ3_IDTGEN)
   ▼
F2D (tributos calculados, F2D_IDREL)
```

A consulta do dashboard usa o caminho direto **F2D → SD1/SD2 → SF1/SF2**:

- `F2D.F2D_IDREL = D1_IDTRIB / D2_IDTRIB`
- `F2D.F2D_TABELA = 'SD1' | 'SD2'`
- item → cabeçalho por filial + documento + série + emissão

**Entrada** (`SQL_IBS_CBS_ENTRADA`):

```
F2D ── INNER JOIN ── SD1 ── INNER JOIN ── SF1
ON F2D_IDREL = D1_IDTRIB   ON D1_DOC/D1_SERIE/D1_EMISSAO = F1_*
   AND F2D_TABELA = 'SD1'
WHERE F2D_TRIB IN (IBS_ENTRADA, CBS_ENTRADA)
  AND F1_EMISSAO BETWEEN ? AND ?
GROUP BY F2D_TRIB
```

**Saída** (`SQL_IBS_CBS_SAIDA`): análogo, com SD2/SF2 e `F2D_TABELA = 'SD2'`.

> Se a consulta de IBS/CBS falhar, o serviço degrada para R$ 0,00 (registra no
> log) para não derrubar o dashboard.

---

## 12. Conciliação Fiscal x Contábil (CT2)

A aba **"Conciliação Fiscal x Contábil"** compara os documentos fiscais
(SF1/SF2) com os lançamentos contábeis (**CT2**) e classifica cada documento.

### Regra em níveis

| Nível | Situação | Status |
|---|---|---|
| 1 | Vínculo exato (documento + valor dentro da tolerância) | ✅ Conciliado |
| 2 | Documento localizado, porém com valor diferente | ⚠️ Divergente |
| 3 | Documento fiscal sem lançamento contábil | ❌ Não contabilizado |
| 4 | Lançamento contábil sem documento fiscal correspondente | 🔍 Sem origem fiscal |

### Chave de vínculo (fiscal → contábil)

```
CT2_FILIAL = F1_FILIAL/F2_FILIAL
AND documento = F1_DOC/F2_DOC  [+ série, se via CT2_KEY]
AND (CT2_CODPAR = parceiro  OR  CT2_CODCLI = cliente saída  OR  CT2_CODFOR = fornecedor entrada)
    [somente se CT2_EXIGIR_PARCEIRO=true]
[AND CT2_ORIGEM em CT2_ORIGEM_*]   (vazio = qualquer origem)
```

- O lado contábil é **agregado por documento** (`SUM(CT2_VALOR)`,
  `COUNT(CT2.R_E_C_N_O_)`) porque uma nota gera várias partidas.
- A comparação de valores usa `Decimal` com tolerância configurável
  (`TOLERANCIA_CONCILIACAO`, padrão `0.05`).
- **Origem do "documento" (`CT2_DOC_VIA_KEY`):** por padrão o vínculo compara
  `CT2_DOC` diretamente com `F1_DOC`/`F2_DOC`. **Nesta instalação (Biocaz),
  isso não funciona:** `CT2_DOC` guarda uma numeração interna do lançamento
  (ex.: `000001`), sem relação com o número da nota (9 dígitos, ex.:
  `000000007`). **CONFIRMADO em 14/08/2026** decodificando o campo
  `CT2_KEY` (`varchar(200)`, um dos 89 campos da tabela `CT2010`) dos 5
  lançamentos do lote 008820 (todos com `CT2_ROTINA=MATA460`, a rotina do
  Protheus para nota fiscal de saída): `CT2_KEY` traz embutido, como texto de
  largura fixa, **filial (posições 1-6) + documento (posições 7-15, 9
  dígitos) + série (posições 16-18)**. Os 5 lançamentos decodificados bateram
  perfeitamente com 5 notas fiscais reais de saída (mesma filial, documento,
  série, data de emissão e valor) - vínculo validado, não é mais suposição.
  Com `CT2_DOC_VIA_KEY=true`, o SQL usa
  `SUBSTRING(CT2_KEY, 7, 9)` e `SUBSTRING(CT2_KEY, 16, 3)` no lugar de
  `CT2_DOC`. **Só validado para saída (`CT2_ROTINA=MATA460`)** - entrada
  ainda não tem nenhum lançamento real conferido, então
  `CT2_ROTINA_ENTRADA` deve ficar vazio (sem filtro de rotina) até validar.
- **Vínculo por parceiro (`CT2_EXIGIR_PARCEIRO`):** por padrão a chave exige
  que `CT2_CODPAR`/`CT2_CODCLI`/`CT2_CODFOR` bata com o cliente/fornecedor da
  nota. **CONFIRMADO em 14/08/2026 nesta instalação:** esses três campos
  ficam em branco em todos os lançamentos testados - por isso
  `CT2_EXIGIR_PARCEIRO=false` no `.env`. Como agora o vínculo por
  filial+documento+série via `CT2_KEY` já é bem específico, exigir também o
  parceiro deixou de ser necessário para a precisão do vínculo.
- **Filtro por rotina (`CT2_ROTINA_ENTRADA`/`CT2_ROTINA_SAIDA`):** só tem
  efeito com `CT2_DOC_VIA_KEY=true`. Restringe a extração via `CT2_KEY` às
  linhas cuja `CT2_ROTINA` esteja na lista - protege contra interpretar o
  `CT2_KEY` de um lançamento de outra origem/rotina (formato pode ser
  diferente) como se fosse filial+documento+série. `CT2_ROTINA_SAIDA=MATA460`
  está validado; `CT2_ROTINA_ENTRADA` segue vazio até validação.

### Variáveis de configuração

| Variável | Padrão | Descrição |
|---|---|---|
| `TABELA_CT2` | `CT2010` | Tabela física de lançamentos contábeis |
| `CT2_ORIGEM_ENTRADA` | (vazio) | Códigos de `CT2_ORIGEM` das entradas (ex.: `SE2`), separados por vírgula |
| `CT2_ORIGEM_SAIDA` | (vazio) | Códigos de `CT2_ORIGEM` das saídas (ex.: `SE1`), separados por vírgula |
| `CT2_FILTRO_DC` | (vazio) | Filtrar linhas por `CT2_DC` (ex.: `3` ou `1,2`); vazio = todas |
| `CT2_EXIGIR_PARCEIRO` | `true` | Exigir vínculo por parceiro (`CT2_CODPAR`/`CODCLI`/`CODFOR`) |
| `CT2_DOC_VIA_KEY` | `false` | `true` = extrai documento+série de `CT2_KEY` (posições 7-15/16-18) em vez de usar `CT2_DOC` diretamente |
| `CT2_ROTINA_ENTRADA` / `CT2_ROTINA_SAIDA` | (vazio) | Restringe o vínculo via `CT2_KEY` a estas `CT2_ROTINA` (separadas por vírgula); só com `CT2_DOC_VIA_KEY=true` |
| `TOLERANCIA_CONCILIACAO` | `0.05` | Tolerância absoluta (R$) para considerar um documento conciliado |

### Implementação

- `database/conciliacao_queries.py`: `SQL_CONCILIACAO_SAIDA`,
  `SQL_CONCILIACAO_ENTRADA` e `SQL_SEM_ORIGEM_FISCAL` (Nível 4);
  `_vinculo_doc_saida()`/`_vinculo_doc_entrada()` montam a cláusula de
  vínculo (CT2_DOC direto ou via CT2_KEY, conforme `CT2_DOC_VIA_KEY`).
- `services/conciliacao_service.py`: `conciliar()`, `sem_origem_fiscal()`,
  `resumo()` e `resumo_por_periodo()`.
- `app.py`: aba própria com barra de progresso, cartões de status, filtro de
  status, busca por documento/parceiro, drill-down por documento e análise
  por período (gráfico de barras empilhadas).

### Situação atual (homologação)

A base está em **implantação**. Em 14/08/2026, o vínculo fiscal → contábil
foi **validado para saída** usando os 5 lançamentos do lote 008820 (filial
010101, `CT2_ROTINA=MATA460`): todos batem com notas fiscais reais via
`CT2_KEY` (filial+documento+série), não via `CT2_DOC`. `.env` desta
instalação: `CT2_EXIGIR_PARCEIRO=false`, `CT2_DOC_VIA_KEY=true`,
`CT2_ROTINA_SAIDA=MATA460`, `CT2_ROTINA_ENTRADA` vazio (entrada **ainda não
validada** - nenhum lançamento de entrada conferido até agora). Nesta
instalação **não existem** as tabelas `LCT100`/`LCT200` (Contabilidade
Gerencial). Após o **GO LIVE**: (1) validar entrada assim que houver um
lançamento real (conferir `CT2_ROTINA` e preencher `CT2_ROTINA_ENTRADA`);
(2) revalidar `CT2_FILTRO_DC` com volume maior de dados; (3) confirmar que o
formato do `CT2_KEY` se mantém estável para outros tipos de lançamento
automático.

### Melhorias para o contador (20/08/2026)

Levantamento de melhorias feito com o usuário em 20/08/2026 (ver
`claude/ideias-melhoria-dashboard-fiscal.md` no projeto). Itens implementados
nesta rodada (Grupos A, C e D do levantamento):

- **Idade da pendência:** coluna `IDADE_DIAS` (dias desde a emissão até
  hoje) em `conciliacao_service.conciliar()`/`sem_origem_fiscal()`, exibida
  na tabela de exceções e no drill-down.
- **Nome do parceiro em "Sem origem fiscal":** antes mostrava só o código
  cru de `CT2_CODPAR` (tipo do parceiro - cliente ou fornecedor -
  desconhecido nesse nível). `_rotular_parceiro_desconhecido()` tenta o
  cadastro de clientes (SA1) e de fornecedores (SA2) e usa o primeiro nome
  encontrado.
- **Rótulo de `CT2_ORIGEM`:** `CT2_ORIGEM_ROTULOS` no `.env` (formato
  `CODIGO:Rótulo`, separados por vírgula) mapeia o código cru para um nome
  legível na coluna "Origem" de "Sem origem fiscal". Vazio = mostra o
  código cru (comportamento anterior).
- **Painel de status da configuração:** expander "⚙️ Configuração da
  conciliação (.env)" no topo da aba, gerado por
  `conciliacao_service.status_configuracao()` - mostra a chave de vínculo,
  rotinas, parceiro exigido, origem e tolerância vigentes, sem precisar
  abrir o `.env`.
- **Export CSV/Excel:** botões na tabela de exceções (filtro atual) e um
  botão "Baixar Excel completo" com abas Resumo/Conciliados/Pendentes/Sem
  origem (`app.py::_excel_conciliacao`). A aba Documentos ganhou também
  export em Excel (antes só tinha CSV).
- **Prazo médio de contabilização:** `conciliacao_service.tempo_medio_contabilizacao()`
  - média de dias entre emissão e `DATA_CONTABIL`, só para documentos com
  lançamento (Conciliado/Divergente). Exibido como cartão na aba.
- **Checklist de qualidade dos dados:** expander "🔎 Checklist de qualidade
  dos dados" - `services/qualidade_service.py` (notas duplicadas, valor
  zerado/negativo, a partir do detalhamento já consultado) +
  `conciliacao_service.lotes_saldo_diferente_zero()` (lotes CT2 cuja soma de
  `CT2_VALOR` não fecha em zero - **checagem informativa**, pois o sinal de
  débito/crédito de `CT2_DC` ainda não foi validado nesta instalação;
  confira um lote conhecido antes de confiar no resultado).
- **Visão consolidada multi-filial:** o filtro "Filial" na barra lateral
  virou seleção múltipla (`st.multiselect`, chave de sessão `filiais`).
  Todo o SQL de `database/queries.py` e `database/conciliacao_queries.py`
  foi ajustado para usar `IN (...)` em vez de `= ?` (uma filial selecionada
  é apenas uma lista de 1 elemento - comportamento antigo preservado por
  padrão). `fiscal_service`/`conciliacao_service` normalizam `filial` como
  string única OU lista via `_normalizar_filiais()`.
- **Anotações locais por documento:** `database/anotacoes_db.py` (SQLite,
  arquivo `ANOTACOES_DB` no `.env`, padrão `anotacoes.db`) +
  `services/anotacoes_service.py`. Uma observação vigente por documento
  (chave `filial+tipo+documento+série`), editável no drill-down
  (`_detalhe_documento` em `app.py`). Não é enviada ao Protheus (que é
  somente leitura) nem versionada no git.

### Grupo B: CFOP, PIS/COFINS e notas canceladas (21/08/2026)

Investigação feita em 3 rodadas via `investigacao_grupo_b*.sql` (raiz do
projeto), rodadas pelo usuário no SSMS. Resultado:

- **CFOP:** esta instalação **não** tem `D1_CFOP`/`D2_CFOP` (nome padrão -
  confirmado vazio via `INFORMATION_SCHEMA.COLUMNS`). O campo real é
  `D1_CF`/`D2_CF` (varchar 5) - validado comparando valores reais: saída
  com `5101`/`5102`, entrada com `1406`/`2556`/`1551`/`2101`/`2102`/etc.,
  todos CFOPs plausíveis (4 dígitos, 1x/2x = entrada, 5x/6x = saída).
  `D1_TES`/`D2_TES` (3 dígitos) é um código interno (TES) que o Protheus
  usa para **derivar** o CFOP via cadastro, não é o CFOP em si -
  descartado. `D1_CFPS`/`D2_CFPS` apareceu quase sempre em branco nos
  testes - não usado. Campo configurável via `CAMPO_CFOP_ENTRADA/SAIDA`
  no `.env` (padrão `D1_CF`/`D2_CF`).
  - Implementado em `database/queries.py::sql_cfop_entrada/saida()` (SD1/SD2
    agrupado por CFOP, com `COUNT(DISTINCT` documento`)`, contagem de itens
    e `SUM(D1_TOTAL`/`D2_TOTAL)` - nome padrão TOTVS para valor do item,
    **não validado explicitamente** nesta instalação, conferir antes de
    confiar no valor somado). `fiscal_service.buscar_cfop()` consolida
    entrada+saída. Exibido no expander "📋 CFOP (natureza das operações)"
    na aba Visão Geral.
- **PIS/COFINS:** campos nativos de SD1/SD2, **não** passam pelo F2D (ao
  contrário de IBS/CBS). PIS: `D1/D2_BASEPIS`, `VALPIS`, `ALQPIS`
  (confirmado na 1ª rodada). COFINS: o nome vem truncado para **"COF"**
  (não "COFI") - por isso a primeira busca por `%COFI%` veio vazia; os
  campos reais são `D1/D2_BASECOF`, `VALCOF`, `ALQCOF` (confirmados na
  3ª rodada, incluindo o lado de entrada que faltava).
  - Implementado em `database/queries.py::sql_pis_cofins_entrada/saida()`
    (soma direta de SD1/SD2, sem join com F2D) e
    `fiscal_service._buscar_pis_cofins()`, integrado a
    `buscar_indicadores()`. Cards "📗 PIS" e "📘 COFINS"
    (entrada/saída) no expander "🏛️ Tributos" da aba Visão Geral.
- **Notas canceladas:** `F1_STATUS` (SF1, varchar 1) e `F2_STATUS` (SF2,
  varchar 3) existem, mas **não foi possível confirmar o valor que
  representa cancelamento** - os dados de teste não têm nenhuma nota
  claramente cancelada: `F2_STATUS` estava em branco nas 9 notas de saída;
  `F1_STATUS` tinha só branco (4 notas) e `"A"` (46 notas, maioria -
  provavelmente é o status normal/ativo, não cancelado). Como filtrar por
  um valor errado poderia esconder notas válidas (`"A"` é a maioria dos
  dados), a decisão foi **não adivinhar**:
  - Filtro opcional `STATUS_CANCELADO_ENTRADA/SAIDA` no `.env`
    (`F1_STATUS`/`F2_STATUS NOT IN (...)`), **desligado por padrão**
    (vazio = nenhuma mudança de comportamento). Aplicado em
    `sql_indicadores()` e `sql_detalhamento()` (cards da Visão Geral e aba
    Documentos); ainda não aplicado na conciliação CT2 (que já tem sua
    própria complexidade e a base ainda não tem lançamentos reais).
  - Painel de diagnóstico: `fiscal_service.buscar_status_documentos()`
    mostra a distribuição atual de `F1_STATUS`/`F2_STATUS` no período
    selecionado, exibido no checklist de qualidade dos dados (aba
    Conciliação). Serve para o contador (ou TI) identificar o valor real
    de cancelado assim que uma nota cancelada aparecer na base, e
    preencher o `.env` sem precisar rodar SQL manualmente.

Todos os itens acima foram validados sem banco real via
`test_grupo_b.py`/`test_grupo_b_service.py` (contagem de `?` vs.
parâmetros em todas as combinações de fornecedor/cliente/tipo/status, e
mock de `_ler_sql` para checar os cálculos) antes de subir para o
ambiente com o driver ODBC real.

### Relatório em PDF, evolução mensal e alertas visuais (21/08/2026)

Terceira rodada de melhorias, a partir de uma nova pergunta do usuário
("o que podemos acrescentar de melhorias a mais?"):

- **Relatório em PDF com PIS/COFINS:** o bloco "Tributos" do PDF
  (`services/pdf_service.py::_bloco_tributos`) só tinha ICMS e IBS/CBS -
  os indicadores de PIS/COFINS (adicionados no Grupo B) ficavam só na
  tela. Agora o bloco tem 3 linhas de 4 cartões (antes eram 2), incluindo
  PIS Saída/Entrada e COFINS Saída/Entrada.
- **Evolução mensal (comparativo mês a mês / ano a ano):** nova consulta
  agrupando por `LEFT(F1_EMISSAO, 6)`/`LEFT(F2_EMISSAO, 6)` (ano+mês, no
  formato YYYYMMDD do Protheus) em vez de por dia -
  `database/queries.py::sql_evolucao_mensal_entrada/saida`,
  `sql_ibs_cbs_mensal_entrada/saida`, `sql_pis_cofins_mensal_entrada/saida`.
  `fiscal_service.buscar_evolucao_mensal()` monta uma série mensal
  completa (sem buracos - meses sem nenhum documento aparecem com zero)
  para os últimos N meses (6/12/24, selecionável na tela) até a data final
  do filtro. O % de conciliação mensal reaproveita `conciliar()` já
  existente, agrupando por mês em `conciliacao_service.evolucao_mensal_conciliacao()`
  - não precisou de uma consulta SQL nova para o CT2. Exibido no expander
  "📈 Evolução mensal (comparativo)" na Visão Geral, com gráfico de barras
  (valores) + linha pontilhada em eixo secundário (% conciliado), e cards
  de variação MoM (mês anterior) e AoA (mesmo mês ano passado, quando o
  período cobre 13+ meses).
- **Alertas visuais (semáforo):** `services/alertas_service.py` (novo) -
  recebe os dados já calculados pela tela (indicadores, resumo/DataFrame
  da conciliação, contagens do checklist de qualidade) e devolve uma
  lista de avisos, sem nenhuma consulta nova ao banco. Quatro checagens,
  todas com limite configurável no `.env` (seção "Alertas visuais" em
  `config/settings.py`):
  - % de conciliação abaixo de `ALERTA_PCT_CONCILIACAO_MIN` (padrão 80%).
  - Pendências (não contabilizadas/divergentes) com `IDADE_DIAS` maior ou
    igual a `ALERTA_IDADE_PENDENCIA_DIAS` (padrão 30 dias).
  - Saldo de ICMS negativo (`ALERTA_SALDO_ICMS_CREDITO`, padrão ligado) ou
    acima de `ALERTA_SALDO_ICMS_MAX` em módulo (padrão desligado - vazio).
  - Notas duplicadas ou com valor inválido encontradas pelo checklist de
    qualidade no período.
  Os avisos aparecem como `st.warning`/`st.error` dentro de um
  `st.expander` recolhido no topo da tela, antes das abas, reaproveitando
  os mesmos dados cacheados que a aba Conciliação já usa (mesma chamada de
  cache do Streamlit, sem consulta duplicada ao banco). **Ajuste de
  25/08/2026:** a lista de alertas ficava toda expandida por padrão,
  ocupando bastante espaço logo no topo - agora aparece recolhida atrás de
  um resumo (🔴/🟡 + quantidade, com a contagem de críticos quando houver
  algum), e só mostra os detalhes ao clicar.

Validado sem banco real via `test_evolucao_alertas.py` (contagem de `?`
vs. parâmetros nas novas consultas mensais, cálculo de janela de meses,
série mensal sem buracos com `_ler_sql` mockado, agrupamento mensal da
conciliação, e os quatro tipos de alerta com dados de exemplo) e geração
real de um PDF de amostra com os novos cartões de PIS/COFINS
(`reportlab`, sem stub).

### Retenções (IR/PIS/COFINS/CSLL) — Reinf R-4020 (25/08/2026)

Nova aba, a partir de um pedido do usuário anexando um relatório real do
Protheus ("Reinf - R4000", evento R-4020 - "Pag./Créd. a beneficiário PJ")
e pedindo uma aba equivalente no dashboard. Diferente de todo o resto do
dashboard (que lê notas fiscais - SF1/SF2), esta funcionalidade lê os
**títulos de contas a pagar (SE2)**, uma área do Protheus não usada
anteriormente por esta aplicação.

**Investigação (3 rodadas de SQL, banco de homologação):**

1. Confirmada a existência de `SE2010` e localizados os campos de retenção
   por nome (`LIKE '%IR%'`, `'%PIS%'`, `'%COF%'`, `'%CSLL%'` etc.) e pelo
   dump completo das colunas (mesma estratégia usada para achar o CFOP no
   Grupo B).
2. Extraídos os 6 títulos reais de teste com todos os campos de retenção,
   comparando com os valores do relatório anexado. **Confirmado:**
   `E2_IRRF`/`E2_PIS`/`E2_COFINS`/`E2_CSLL` são os valores retidos
   corretos - validado recalculando as alíquotas padrão (1,5% IR, 0,65%
   PIS, 3% COFINS, 1% CSLL) contra 2 títulos reais do relatório anexado
   (ex.: fornecedor CHI TERRAPLANAGEM, base R$ 19.820 → IR R$ 297,30, PIS
   R$ 128,83, COFINS R$ 594,60, CSLL R$ 198,20 - bateu exatamente).
   `E2_VRETIRF`/`E2_VRETPIS`/`E2_VRETCOF`/`E2_VRETCSL` ficaram **zerados**
   em todos os 85 títulos testados - não usar. COFINS segue o mesmo padrão
   de truncamento "COF" já visto em SD1/SD2. `E2_NOMFOR` (fornecedor)
   confirmado por contagem exata de caracteres com o nome do relatório.
   Não existe `E2_LOJA` nesta instalação - o vínculo com SA2 (para trazer o
   CNPJ) usa só o código do fornecedor.
3. Investigada a origem do **"Cod. R"** (código de natureza de rendimento
   do Reinf, ex.: `15014`, coluna do relatório anexado). `E2_CODRET` (no
   próprio título) veio em branco nos 85 títulos. Localizada a tabela
   `SED010` (cadastro de Natureza financeira) com campos que pareciam
   promissores (`ED_CODRET`, `ED_NATREN`, `ED_GRPNAT`, `ED_INDRET`) - mas
   **todos vieram em branco nas 38 naturezas cadastradas**. Conclusão: o
   "Cod. R" **não existe em nenhuma tabela acessível pelo banco** desta
   instalação - é provavelmente calculado só pelo módulo Gerador EFD-Reinf
   na hora de gerar o evento oficial, fora do alcance de um usuário
   só-leitura.

**Decisão (consultada com o usuário):** como o "Cod. R" não é recuperável
do banco, a aba usa um **mapeamento manual e opcional** de `E2_NATUREZ`
para "Cod. R" via `.env` (`RETENCAO_NATUREZA_CODRET`, formato
`NATUREZA:CODIGO,...`), no mesmo padrão já usado em `CT2_ORIGEM_ROTULOS`.
Sem mapeamento configurado, a coluna fica em branco e a tela mostra um
aviso explicando o motivo. O usuário também optou por uma **tabela simples
e filtrável** (sem os subtotais aninhados do relatório impresso - Total
Data/Fornecedor/Tipo/Empresa), com total geral e export CSV/Excel, no
mesmo padrão das outras abas.

**Implementação:**

- `database/queries.py::SQL_RETENCOES` / `sql_retencoes()` - título +
  `OUTER APPLY` com `TOP 1` em SA2 (evita duplicar linha quando o
  fornecedor tem mais de uma loja, já que não há `E2_LOJA` para o vínculo
  exato). Só retorna títulos com pelo menos uma retenção diferente de
  zero. Período filtra por `E2_EMISSAO` (mesma linha do resto do
  dashboard) - **atenção:** o evento Reinf oficial usa a data do
  pagamento, então o total da aba pode não bater 100% com o relatório
  oficial se houver título pago em mês diferente do de emissão.
- `services/retencao_service.py` (novo) - `buscar_retencoes()` calcula
  `VALOR_TOTAL_RETIDO` (soma de IR+PIS+COFINS+CSLL) e a coluna `COD_R` via
  `RETENCAO_NATUREZA_CODRET`. Degradação graciosa (DataFrame vazio) em
  caso de falha.
- `config/settings.py` - `TABELA_CP` (padrão `SE2010`),
  `CAMPO_CNPJ_FORNECEDOR` (padrão `A2_CGC`, **não validado** nesta
  instalação - a SA2 não foi consultada durante a investigação),
  `RETENCAO_NATUREZA_CODRET`.
- `app.py` - nova aba "🧾 Retenções": cartões de total por tributo (IR,
  PIS, COFINS, CSLL, total geral), tabela filtrável (reaproveita o filtro
  de fornecedor da sidebar) e export CSV/Excel.

Validado sem banco real via `test_retencoes.py` (contagem de `?` vs.
parâmetros com e sem filtro de fornecedor, parsing do mapeamento
`RETENCAO_NATUREZA_CODRET` incluindo entradas malformadas, e
`buscar_retencoes()` com `_ler_sql` mockado conferindo `VALOR_TOTAL_RETIDO`,
a coluna `COD_R` mapeada/em branco e a ordenação por emissão/fornecedor).

### Retenções x Financeiro — validação de baixa (25/08/2026)

> ⚠️ **SUPERADO no mesmo dia** - o vínculo SE2 x SEF010 descrito nesta
> seção foi confirmado errado após teste ao vivo do usuário. Ver
> "Redesenho do vínculo Retenções x Financeiro (25/08/2026, mesmo dia)"
> logo abaixo para o mecanismo real (título "TX" na própria SE2010) e a
> implementação atual. Seção mantida como registro histórico da
> investigação.

A pedido do usuário ("criar outra aba fazendo uma validação com as
retenções.SEF010"), depois de ele mesmo consultar e enviar a estrutura da
SEF010 (movimento financeiro/baixas bancárias) do banco. Perguntado o que
a validação deveria conferir, a resposta foi "verificar se gerou financeiro
do valor a pagar no financeiro" - ou seja, confirmar se o título com
retenção já tem baixa gerada no módulo Financeiro, e não só existência: o
valor líquido baixado também é conferido contra o valor esperado
(Valor do título - retenções).

**Vínculo SE2 (título) x SEF (movimento) - o mais importante desta
implementação:**

- Chave usada: `FILIAL` + `PREFIXO` + `NÚMERO` (`EF_TITULO` = `E2_NUM`) +
  `PARCELA` + `FORNECEDOR` (`EF_FORNECE` = `E2_FORNECE`).
- **Sem `TIPO`:** a SEF010 enviada pelo usuário tem `EF_TIPO` com valores
  como `"BOL"` e `"PA"` (ex.: "Valor pago s/ Titulo", "ADIANTAMENTO") -
  isso parece indicar a **forma do movimento/pagamento**, não
  necessariamente o mesmo código de `E2_TIPO` (tipo de título, ex. "NF").
  Incluir `EF_TIPO` no vínculo arriscava excluir pagamentos legítimos por
  um código que não bate; por segurança, o vínculo não usa esse campo.
- **Sem `LOJA`:** mesma razão já documentada na aba Retenções - `E2_LOJA`
  não existe na SE2010 desta instalação.
- Um título pode ter mais de um movimento na SEF010 (ex.: pagamento
  parcelado) - por isso a consulta soma (`SUM`) o `EF_VALOR` de todos os
  movimentos vinculados ao título, via `OUTER APPLY` (mesmo padrão já usado
  no vínculo com a SA2 na aba Retenções).
- `E2_VALOR` (valor original do título, usado para calcular o valor líquido
  esperado) é um campo padrão TOTVS - assumido aqui mas **ainda não
  validado explicitamente** nesta instalação (diferente de
  `E2_IRRF`/`E2_PIS`/`E2_COFINS`/`E2_CSLL`, que já foram confirmados
  recalculando as alíquotas contra títulos reais).

**Cálculo e status (`services/retencao_service.py`):**

- `VALOR_LIQUIDO_ESPERADO = VALOR_TITULO - VALOR_RETIDO` (soma de
  IR+PIS+COFINS+CSLL, já calculada na aba Retenções).
- `DIFERENCA = VALOR_LIQUIDO_ESPERADO - VALOR_FINANCEIRO` (soma do que foi
  encontrado na SEF010).
- `STATUS`, usando a mesma tolerância da Conciliação Fiscal x Contábil
  (`TOLERANCIA_CONCILIACAO`, padrão R$ 0,05, comparação com `Decimal` -
  nunca igualdade de ponto flutuante). O primeiro critério é a própria
  `E2_BAIXA` do título (**não** a SEF010) - ver "Ajuste de status" abaixo:
  - ⚪ **Em aberto** - o título ainda não tem `E2_BAIXA` preenchida (não
    foi pago) - situação normal, não é comparado com a SEF010.
  - 🔴 **Não gerado** - título já tem `E2_BAIXA`, mas nenhum movimento foi
    encontrado na SEF010.
  - 🟡 **Divergente** - título já tem `E2_BAIXA`, movimento encontrado na
    SEF010, mas a diferença passa da tolerância.
  - 🟢 **OK** - título já tem `E2_BAIXA`, movimento encontrado e o valor
    bate dentro da tolerância.

**Implementação:**

- `database/queries.py::SQL_VALIDACAO_FINANCEIRO_RETENCOES` /
  `sql_validacao_financeiro_retencoes()` - mesmo filtro de título da aba
  Retenções (pelo menos uma retenção diferente de zero), com `OUTER APPLY`
  trazendo `COUNT(*)` e `SUM(EF_VALOR)` da SEF010 por título.
- `services/retencao_service.py` - `buscar_validacao_financeiro()` calcula
  `VALOR_LIQUIDO_ESPERADO`, `DIFERENCA` e `STATUS` (`_status_financeiro()`,
  que agora recebe também se o título tem `E2_BAIXA`; `_tolerancia()` -
  mesmo padrão de `conciliacao_service.py`). Degradação graciosa (DataFrame
  vazio) em caso de falha.
- `config/settings.py` - `TABELA_FINANCEIRO` (padrão `SEF010`).
- `app.py` - nova aba "🏦 Retenções x Financeiro": cartões de resumo
  (títulos, ⚪ Em aberto, 🟢 OK, 🟡 Divergente, 🔴 Não gerado) dentro de um
  `st.expander` ("📊 Resumo"), e uma tabela filtrável por status
  (`st.segmented_control`, com "⚠️ Com problema" como padrão - mesmo
  padrão da aba Conciliação) dentro de outro expander ("📋 Ver títulos e
  status", recolhido por padrão), com a coluna "Baixa (SE2)" visível e
  export CSV/Excel.

Validado sem banco real via `test_validacao_financeiro.py` (contagem de `?`
vs. parâmetros com e sem filtro de fornecedor, confirmação de que o SQL não
usa `EF_TIPO`/`EF_LOJA` no vínculo, e `buscar_validacao_financeiro()` com
`_ler_sql` mockado cobrindo os quatro cenários: título em aberto - sem
`E2_BAIXA`, título já baixado mas sem nenhum movimento na SEF010, baixa com
valor batendo e baixa com valor divergente).

**Ajuste de status a partir de dados reais (25/08/2026):** a primeira
versão da aba comparava TODOS os títulos com a SEF010, sem olhar para
`E2_BAIXA` - e no primeiro teste do usuário, os 6 títulos do período
apareceram como "🔴 Não gerado". Isso levantou a suspeita de que o vínculo
por PREFIXO+NÚMERO+PARCELA estivesse errado (a amostra da SEF010 enviada
antes tinha `EF_TITULO = "1"` para o fornecedor 000004, o que não parece
um número de título real). O usuário rodou uma consulta comparando SE2 x
SEF010 lado a lado (sem aplicar o vínculo) para dois fornecedores, e os
dois retornaram **zero linhas na SEF010** com `D_E_L_E_T_ = ''`. Ao
reexaminar a amostra original da SEF010, ficou claro que **todas as linhas
daquela amostra tinham `D_E_L_E_T_ = '*'`** (registros logicamente
excluídos) - o que explica o `EF_TITULO = "1"` estranho (não é
representativo de um movimento ativo) e também por que a consulta correta
(`D_E_L_E_T_ = ''`) não achou nada para aqueles fornecedores. Cruzando com
a SE2: os dois títulos do fornecedor 000004 têm `E2_BAIXA` **em branco**
(ainda não foram pagos) - ou seja, zero resultado na SEF010 é o esperado,
não um bug de vínculo. Como essa distinção (título não pago vs. título
pago sem registro no Financeiro) é exatamente o que importa para o usuário
saber se está "correto", o status passou a considerar `E2_BAIXA` primeiro
(ver "Cálculo e status" acima) e a coluna "Baixa (SE2)" foi adicionada à
tabela, para o usuário conferir com os próprios olhos, direto na tela, sem
precisar rodar SQL toda vez. O vínculo por si (PREFIXO+NÚMERO+PARCELA+
FORNECEDOR, sem TIPO/LOJA) continua **não confirmado com um caso positivo
real** (um título com `E2_BAIXA` preenchida E um movimento correspondente
na SEF010) - o próximo título que aparecer com `E2_BAIXA` preenchida é a
oportunidade de validar isso.

### Redesenho do vínculo Retenções x Financeiro (25/08/2026, mesmo dia)

**A hipótese do vínculo SE2 x SEF010 (seções acima) estava errada** -
descoberto porque o usuário testou ao vivo: fez uma baixa real em um
título com retenção e nada mudou na aba. Investigando por que, ele
abriu a tela "Liquidação" do Protheus filtrando pelo próprio número do
título (`000000002-1`, fornecedor 000004) e mandou o print: **apareciam
DUAS linhas**, não uma:

- `E2_TIPO = 'VL'` (valor) - fornecedor 000004, R$ 19.700,00, histórico
  "TARIFA COM RET" - a nota em si. **Saldo aberto, sem baixa.**
- `E2_TIPO = 'TX'` (taxa) - `E2_NATUREZ = 'IRF'`, credor "UNIAO" (sem
  fornecedor - o credor é a Receita, não o fornecedor da nota),
  R$ 300,00 (== `E2_IRRF` do título VL, valor batendo exato). **Já
  baixado hoje** (`E2_BAIXA = 25/08/2026`, saldo zero).

Ou seja: **o Protheus grava a retenção como um SEGUNDO TÍTULO na
própria SE2010**, não como um movimento em SEF010 vinculado ao título
original. Confirmado consultando todos os campos relevantes da SE2010
para o `E2_NUM = '000000002'` (`investigacao_financeiro_parte3.sql`):

| Campo | Linha VL (título original) | Linha TX (título de taxa) |
|---|---|---|
| `E2_TIPO` | VL | TX |
| `E2_NATUREZ` | 0000000001 (código genérico) | IRF (código do tributo) |
| `E2_FORNECE` / `E2_NOMFOR` | 000004 / SAMSUNG ELETRONICA | UNIAO / UNIAO |
| `E2_PARCELA` | 1 | 01 (formato diferente!) |
| `E2_VALOR` | 19.700,00 | 300,00 |
| `E2_IRRF` (campo) | 300,00 | 0,00 |
| `E2_BAIXA` | (em branco) | 20260825 |

Isso também explica o print anterior (títulos `TG0000002` a
`TG0000005`, um por tributo - IRF/CSL/PIS/COF - creditados ao
"portador" 000656): é o **mesmo mecanismo**, só que gerando o prefixo
`TG` em vez de deixar o prefixo em branco, e usando um portador
numérico (provavelmente uma retenção estadual/ICMS-ST, diferente do
"UNIAO" usado para os tributos federais) em vez de "UNIAO" como credor.
O vínculo de qualquer forma é o mesmo: `E2_TIPO = 'TX'`, mesmo
`FILIAL + PREFIXO + NÚMERO` do título original.

**Novo vínculo (`database/queries.py::SQL_VALIDACAO_FINANCEIRO_RETENCOES`):**
SELF JOIN na SE2010 (`OUTER APPLY`) por `FILIAL + PREFIXO + NÚMERO`,
`E2_TIPO = 'TX'` e `E2_NATUREZ IN ('IRF','PIS','COF','CSL')` - **sem**
`PARCELA` (formato observado diferente entre as duas linhas, "01" x
"1") e **sem** `FORNECEDOR` (o credor da linha TX não é o fornecedor
original). `TABELA_FINANCEIRO`/SEF010 não é mais usada nesta consulta
(variável mantida em `settings.py` só por compatibilidade com `.env`
já configurado).

**Novo cálculo e status (`services/retencao_service.py`):** para cada
título original, soma quantos títulos TX foram encontrados
(`QTD_TITULOS_RETENCAO`), a soma do valor deles
(`VALOR_GERADO_FINANCEIRO`) e quantos já têm baixa (`QTD_BAIXADOS`,
`DATA_ULTIMA_BAIXA`). `DIFERENCA = VALOR_RETIDO - VALOR_GERADO_FINANCEIRO`.
O status "⚪ Em aberto" (baseado na baixa do título ORIGINAL) foi
removido - não fazia mais sentido, já que a baixa relevante agora é a
do título TX, que é independente:

- 🔴 **Não gerado** - nenhum título TX encontrado ainda para os
  tributos retidos.
- 🟡 **Divergente** - título(s) TX encontrado(s), mas a soma do valor
  não bate com o total retido (fora da tolerância).
- 🔵 **Aguardando baixa** (novo) - título(s) TX encontrado(s), valor
  batendo, mas nem todos ainda foram pagos - situação normal, **não**
  tratada como problema.
- 🟢 **OK** - título(s) TX encontrado(s), valor batendo e todos já
  baixados.

`app.py`: cartões de resumo e filtro (`st.segmented_control`)
atualizados para os 4 novos status; colunas da tabela trocadas
(`QTD_TITULOS_RETENCAO`, `VALOR_GERADO_FINANCEIRO`, `QTD_BAIXADOS`,
`DATA_ULTIMA_BAIXA` no lugar de `QTD_MOVIMENTOS_FINANCEIRO`/
`VALOR_FINANCEIRO`). `test_validacao_financeiro.py` reescrito com 5
cenários, incluindo o caso real confirmado (título `000000002-1`: TX já
baixado, VL ainda aberto → 🟢 OK).

**Ainda não confirmado:** títulos com mais de uma parcela (o vínculo
sem `PARCELA` pode somar retenções de parcelas diferentes juntas) e a
lista completa de códigos de `E2_NATUREZ` usados nos títulos TX (por
ora: `IRF`, `PIS`, `COF`, `CSL`, only confirmado IRF ao vivo). O padrão
"VL + TX" foi confirmado para um único título até agora - vale
confirmar em mais 1-2 dos outros títulos rastreados antes de considerar
o vínculo 100% validado.

### Segundo padrão de geração descoberto (mesmo dia, 25/08/2026) — títulos "TG"

O usuário testou de novo: buscou na tela "Liquidação" do Protheus (sem
filtro, grade completa) e apontou vários títulos `TG0000001` a
`TG0000012` que **não tinham nenhuma relação de número** com os títulos
rastreados (`000000002`, `NFS58`, `NFS18412` etc.) - eram uma numeração
própria e sequencial, criada pela rotina `E2_ORIGEM = 'MATA100'` (a
rotina padrão de inclusão de contas a pagar do Protheus). Isso é
**diferente** do Padrão A (`000000002` → título irmão com o mesmo
número, `E2_TIPO='TX'`).

Investigado com duas rodadas de SQL adicionais
(`investigacao_financeiro_parte4.sql` e `_parte5.sql`):

- **Nenhum campo estruturado liga o título TG de volta ao título
  original.** `E2_ORIGEM` só grava o nome da rotina geradora
  (`MATA100`), não uma referência à NF. Os dois campos candidatos mais
  promissores encontrados na varredura de colunas (`E2_DOCHAB`,
  `E2_NFELETR`) vieram **em branco** em todos os 12 títulos TG
  testados.
- **O único vínculo disponível é o texto livre do Histórico**
  (`E2_HIST`), no formato `"<lote> - NF: <número> / <série>"` (ex.:
  `"E00081 - NF: 58 / NFS"`). Confirmado batendo exato: o título
  `NFS58-01` (fornecedor 000316, Estruturas Metálicas) tem
  `E2_IRRF=184,62` / `E2_PIS=80` / `E2_COFINS=369,24` / `E2_CSLL=123,08`
  - e esses quatro valores batem exatamente com `TG0000002` (IRF),
  `TG0000004` (PIS), `TG0000005` (COF) e `TG0000003` (CSL), todos com
  Histórico referenciando "NF: 58 / NFS".
- Diferente do Padrão A, aqui o **tributo já vem direto em `E2_TIPO`**
  (`IRF`/`CSL`/`PIS`/`COF`, além de `INS`/`ISS` para INSS e ISS - fora
  do escopo desta aba, que só cobre IR/PIS/COFINS/CSLL, mesmo escopo do
  Reinf R-4020 da aba "Retenções"), e `E2_NATUREZ` é um código genérico
  (`0000000001` a `0000000004`), não o tributo.
- O credor (`E2_FORNECE`) desses títulos é um cadastro genérico por
  tipo de tributo: `000656` ("RECEITA FEDERAL", para IR/PIS/COFINS/
  CSLL/INSS) ou `000657` ("PREF. MUN. DE ARCOS", para ISS municipal) -
  diferente do "UNIAO" (texto livre) visto no título `000000002-1`
  (Padrão A) - mais um indício de que são dois mecanismos distintos
  coexistindo nesta base (possivelmente um customização específica do
  cliente para o Padrão B, rodando junto com o módulo padrão de
  retenção do Protheus usado no Padrão A).

**Implementação (`database/queries.py::SQL_VALIDACAO_FINANCEIRO_RETENCOES`):**
o `OUTER APPLY` passou a agregar um `UNION ALL` de duas sub-consultas -
Padrão A (como antes) e Padrão B, que filtra `E2_TIPO IN
('IRF','PIS','COF','CSL')` e extrai o número/série da NF do Histórico via
`CHARINDEX`/`SUBSTRING` (procurando `'NF: '` e `' / '` no texto),
comparando com `E2_NUM`/`E2_PREFIXO` do título original. `WHERE
CHARINDEX(...) > 0` antes de extrair evita erro em históricos que não
seguem o padrão (a linha simplesmente não entra no vínculo, não quebra a
consulta). Testado com `test_validacao_financeiro.py` -
`testar_parsing_historico_padrao_b()` replica a mesma lógica em Python e
confere contra os 6 textos de Histórico reais enviados pelo cliente.

**Risco conhecido e assumido:** o vínculo do Padrão B depende do formato
do texto do Histórico se manter estável (`"... NF: <número> / <série>"`)
em toda a base - é o único vínculo que restou depois de duas varreduras
de colunas candidatas na SE2010. Se a rotina que gera esses títulos for
alterada no Protheus (ou o texto for editado manualmente), o vínculo
pode parar de funcionar silenciosamente (o título passaria a aparecer
como "🔴 Não gerado" mesmo já gerado). Vale o usuário confirmar
periodicamente que os totais da aba continuam batendo com o que ele vê
direto no Protheus.

### Limpeza de legendas técnicas da tela (25/08/2026)

A partir de feedback direto do usuário na tela (\"não precisa amostrar\",
depois de ver o painel de status da configuração e captions parecidos),
removidos da interface os avisos/legendas que expunham detalhes de
implementação (nomes de campo, variáveis do `.env`, tabelas físicas) sem
agregar nada ao uso do dia a dia. O conteúdo removido não foi perdido -
está registrado nesta documentação, na seção correspondente a cada
funcionalidade. Removido de `app.py`:

- Expander "⚙️ Configuração fiscal (.env)" na aba Conciliação (chave de
  vínculo, rotinas, tolerância etc. - ver seção 12, "Situação atual
  (homologação)").
- Caption sobre o sinal de `CT2_DC` não validado, no checklist de
  qualidade (ver "Melhorias para o contador", acima).
- Caption sobre o valor de "cancelada" em `F1_STATUS`/`F2_STATUS` ainda não
  confirmado (ver seção "Grupo B: CFOP, PIS/COFINS e notas canceladas").
- Caption "Módulo em implantação" (CT2 vazio, chave/origem/tolerância
  configuráveis) ao final da aba Conciliação (ver seção 12, "Situação
  atual (homologação)").
- Caption sobre o campo de CFOP configurável (`CAMPO_CFOP_ENTRADA/SAIDA`)
  no expander de CFOP (ver seção "Grupo B", acima, e seção 6).
- Na aba Retenções: a descrição inicial da aba (o que ela mostra e a
  ressalva sobre emissão x pagamento), o aviso sobre o mapeamento do
  "Cod. R" (`RETENCAO_NATUREZA_CODRET`) e a nota sobre `CAMPO_CNPJ_FORNECEDOR`
  não validado - todos já documentados acima, nesta seção, e na seção 6.
- Caption final do rodapé ("Indicadores gerenciais... validar no
  dicionário SX3") - movida para a seção 9.

O que ficou na tela: captions puramente funcionais (totais, contagens,
período disponível, instruções de uso do gráfico de conciliação por dia,
glossário MoM/AoA) - nada que exponha nome de campo, tabela física ou
variável de configuração.

Também a pedido do usuário: a tabela de títulos da aba Retenções (antes
sempre visível) passou a ficar dentro de um `st.expander` ("📋 Ver títulos
com retenção", recolhido por padrão) - os cartões de total por tributo
continuam sempre visíveis, só a tabela detalhada (com export CSV/Excel)
fica escondida até o clique, no mesmo padrão já usado em "📄 Ver documentos"
(aba Conciliação) e "🔎 Checklist de qualidade dos dados".

---

## 13. Relatório em PDF

- **Onde:** botão "Gerar relatório em PDF" na barra lateral, abaixo de "Atualizar".
- **Geração:** ao clicar, a área principal gera o PDF com os dados já carregados
  e o botão "Baixar relatório PDF" aparece na sidebar (abaixo do gerar),
  permanecendo disponível enquanto os filtros não mudarem.
- **Conteúdo (25/08/2026 - relatório completo, todas as abas):** o PDF sempre
  traz, em um único documento, o cabeçalho (título/filial/período/logo, e
  Fornecedor/Cliente quando filtrados) seguido de:
  1. Bloco "Movimentação" (Visão Geral).
  2. Bloco "Tributos" (Visão Geral).
  3. Bloco "Conciliação Fiscal x Contábil" (cartões de resumo: total,
     conciliados, não contabilizados, divergentes, valores e pendência).
  4. "Detalhamento das notas" (mesma tabela da aba Documentos).
  5. Bloco "Retenções (IR/PIS/COFINS/CSLL)" (cartões de resumo e tabela dos
     títulos com retenção, com aviso "nenhum título encontrado" quando vazio).

  Antes, o PDF só continha a seção da aba em que o usuário estava no
  momento do clique (parâmetro `secao` em `gerar_relatorio_pdf`). Isso foi
  trocado por um relatório sempre completo, para permitir imprimir/visualizar
  todas as informações de uma vez. O parâmetro `secao` continua existindo na
  assinatura da função por compatibilidade, mas não altera mais o conteúdo.
- **Rodapé (desenhado por canvas, em todas as páginas):** "Biocaz | Dashboard
  Fiscal Protheus", "Emissão do relatório: dd/mm/aaaa às HH:MM", "Página X de Y"
  e a nota gerencial em itálico.
- **Layout:** blocos do cabeçalho, "Movimentação" e "Tributos" usam
  `KeepTogether` para evitar página quase vazia; margem inferior de 18 mm.
  Os blocos de "Conciliação" e "Retenções" são adicionados via
  `list.extend(...)` (não `list.append(...)`) porque cada bloco já retorna
  uma lista de flowables do reportlab — usar `append` aninha essa lista
  dentro da lista principal e quebra `doc.build()` com
  `AttributeError: 'list' object has no attribute 'getKeepWithNext'`.
- **Uma página por aba (25/08/2026):** cada seção a partir da Conciliação
  começa em página nova (`PageBreak()` antes de Conciliação, de
  "Detalhamento das notas" e de Retenções), na mesma ordem das abas na
  tela: Visão Geral (Movimentação + Tributos) → Conciliação Fiscal x
  Contábil → Documentos → Retenções. O bloco da Conciliação também é
  envolvido em `KeepTogether` inteiro (título + os dois cartões) logo após
  o `PageBreak`. Isso corrige um bug em que o título "Retenções
  (IR/PIS/COFINS/CSLL)" podia ficar sozinho no rodapé de uma página, com o
  conteúdo (cartões e tabela) começando isolado na página seguinte — o
  título "órfão" acontecia porque, sem quebra de página forçada, o
  `SimpleDocTemplate` só decide manter um `Paragraph` e o que vem depois
  juntos quando ambos cabem no espaço restante da página atual; título e
  conteúdo cabendo cada um sozinho, mas não os dois juntos, é o cenário
  que gera o órfão.
- **Implementação:** `services/pdf_service.py` (reportlab, página A4, cores
  institucionais #43AA8A / #0C1B7D, `_CanvasNumerado` para a paginação).
  Em `app.py`, o botão agora sempre busca conciliação (`_conciliacao_cached`)
  e retenções (`_retencoes_cached`) antes de montar o PDF, independente da
  aba ativa (`st.session_state["aba_ativa"]` deixou de ser usado aqui).
- **Nome do arquivo:** `RelFiscal_{DD_MM_YYYY}.pdf` (data de emissão, ex.:
  `RelFiscal_12_08_2026.pdf`).

---

## 14. Cache e performance

| Recurso | Detalhe |
|---|---|
| Cache dos dados | `@st.cache_data` (TTL 300 s) para indicadores e detalhamento |
| Cache de filtros | TTL 600 s para empresas, filiais, fornecedores, clientes e período disponível |
| Atualizar | `st.cache_data.clear()` + limpeza do PDF armazenado |
| Índices | Antes de produção, verifique índices em filial e data de emissão |
| Filtros por faixa | `BETWEEN` direto no campo `F1_EMISSAO`/`F2_EMISSAO` (sem conversão) |

---

## 15. Segurança

- Usuário do SQL Server **somente leitura**.
- Senhas apenas no `.env` (fora do código e do versionamento).
- Consultas **100% parametrizadas** (filtros do usuário nunca concatenados).
- Nomes de tabela vêm de configuração e são **validados por expressão regular**
  antes da interpolação no SQL (`_tabela` em `database/queries.py`).
- Erros técnicos registrados em `logs/dashboard.log` **sem credenciais** ou
  connection string.

---

## 16. Logs e solução de problemas

### Logs

- Arquivo: `logs/dashboard.log` (rotação de 5 MB, 3 backups, UTF-8).
- Níveis: INFO (padrão), erros em ERROR, avisos de fallback em WARNING.

### Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| "Não foi possível conectar ao banco" | `.env` errado ou servidor indisponível | Conferir `DB_SERVER/DB_DATABASE/DB_USER/DB_PASSWORD` |
| Nenhuma nota listada | Base de leitura aponta para ambiente sem dados | Confirmar o banco/ambiente no `.env` |
| Filial com 6 dígitos não aparece | Código diferente no SM0 | Usar o código exibido no ERP (ex.: `010101`) |
| IBS/CBS zerados | Códigos de tributo diferentes na instalação | Ajustar `COD_TRIB_*` no `.env` |
| Datas em inglês | — | Já resolvido: `format="DD/MM/YYYY"` nos filtros |
| SM0 não encontrado no log | Tabela não existe na base | Fallback automático via SF1/SF2 (não é erro) |

---

## 17. Roadmap

- **Entrega 2:** gráficos (faturamento mensal, entrada × saída, ICMS),
  comparativo por filial e tabela de documentos.
  - **Conciliação Fiscal x Contábil (CT2):** estrutura já criada (aba própria,
    status em níveis, drill-down e análise por período — seção 12). Após o
    **GO LIVE**, apontar o `.env` para produção e validar a chave de vínculo
    (`CT2_DOC` + parceiro + `CT2_ORIGEM`) e o filtro `CT2_DC`.
- **Entrega 3:** escrituração pela SFT com PIS, COFINS, CFOP, CST e bases
  ICMS/PIS/COFINS para apuração mais precisa.
- **Tratamento de cancelamento:** definir o campo de cancelamento conforme a
  instalação (não usar `D_E_L_E_T_`).
- **Retenções (aba "Retenções", Reinf R-4020):** ✅ Concluído em 25/08/2026 -
  valor retido confirmado com valores reais (ver seção 12). Pendente:
  validar `CAMPO_CNPJ_FORNECEDOR` (`A2_CGC`) nesta instalação e, se
  necessário, preencher `RETENCAO_NATUREZA_CODRET` para exibir o "Cod. R".
- **Retenções x Financeiro (aba "Retenções x Financeiro"):** ✅ Concluído e
  REDESENHADO DUAS VEZES em 25/08/2026 (mesmo dia, após dois testes ao
  vivo do usuário) - self join na própria SE2010 cobrindo dois padrões de
  geração confirmados nesta instalação, não SE2 x SEF010 (ver seção 12,
  "Redesenho do vínculo" e "Segundo padrão de geração descoberto"):
  Padrão A (título "irmão" com o mesmo número, `E2_TIPO='TX'` - título
  000000002-1) e Padrão B (título com numeração própria "TG", vinculado
  só pelo texto do Histórico - título NFS58-01). Pendente: confirmar os
  dois padrões em mais títulos, validar o vínculo sem `PARCELA` quando
  houver mais de uma parcela, e monitorar se o formato do texto do
  Histórico (Padrão B) se mantém estável em toda a base.

---

## 18. Como adicionar um novo indicador

1. Adicione a coluna em `database/queries.py` (ou um novo SQL parametrizado).
2. Transforme/calcule em `services/fiscal_service.py`.
3. Exiba o novo card em `app.py` (e, se desejar, em `services/pdf_service.py`).
4. Atualize esta documentação e o `README.md`.

