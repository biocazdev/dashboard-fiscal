# Estrutura do projeto

Este documento explica para que serve cada pasta e cada arquivo na raiz do
projeto **Dashboard Fiscal**. É um mapa de orientação para quem está
chegando agora no código - para entender o *porquê* de cada trecho, o
código-fonte em si foi comentado (em português) explicando as decisões
não óbvias, e o `DOCUMENTACAO.md` traz o histórico funcional completo
(descobertas, regras de negócio, decisões de projeto).

## Visão geral da arquitetura

O dashboard é uma aplicação Streamlit de uma camada só de interface, que
se apoia em três camadas internas bem separadas:

```
app.py  (interface Streamlit: filtros, abas, gráficos, tabelas)
   |
   v
services/   (regras de negócio: agrega, calcula, formata para exibição)
   |
   v
database/   (monta e executa SQL contra o Protheus / SQLite local)
   |
   v
config/     (lê as configurações do .env que todas as camadas usam)
```

`utils/` é transversal (formatação de texto e log), usado por qualquer
camada. A regra geral do projeto é que **cada camada só conversa com a
camada logo abaixo dela** - `app.py` nunca monta SQL diretamente, e
`database/` nunca sabe nada sobre Streamlit.

## Pastas

### `config/`

Configuração da aplicação, lida a partir do arquivo `.env` (nunca do
código-fonte, por segurança - ver seção sobre `.env` mais abaixo).

- `settings.py` - define todas as variáveis de configuração (conexão com o
  banco, nomes de tabelas/campos do Protheus, que são configuráveis porque
  cada instalação Protheus pode ter nomes de campo customizados, limites de
  alerta, etc.). É o único lugar do projeto que lê `os.environ`/`.env`
  diretamente; todo o resto do código importa `config.settings` em vez de
  ler variáveis de ambiente por conta própria.

### `database/`

Camada de acesso a dados. É a única camada que sabe montar e executar SQL.

- `connection.py` - abre a conexão ODBC com o SQL Server do Protheus
  (somente leitura). Contém a regra de segurança de nunca logar a
  connection string ou a exceção crua do driver (que pode conter
  usuário/senha).
- `queries.py` - o maior arquivo da pasta: monta o SQL (parametrizado) de
  praticamente todas as consultas ao Protheus - indicadores, IBS/CBS,
  evolução mensal, detalhamento de notas, CFOP, empresas/filiais,
  retenções e a validação cruzada "Retenções x Financeiro" (que identifica
  se um título de retenção já foi baixado, cobrindo os dois padrões de
  vínculo descobertos no Protheus desta instalação - título "irmão" com
  `E2_TIPO='TX'`, e título com numeração própria "TG" vinculado só pelo
  texto do histórico).
- `conciliacao_queries.py` - SQL da conciliação entre o módulo fiscal
  (notas SF1/SF2) e o financeiro/contábil (CT2), incluindo notas sem
  origem fiscal reconhecida e lotes com saldo diferente de zero.
- `anotacoes_db.py` - único módulo que grava dado (ao contrário dos
  outros dois acima, que só leem o Protheus). Mantém um banco **SQLite
  local**, separado do Protheus, com anotações do contador sobre
  documentos (ex.: "aguardando NF do fornecedor") - porque o Protheus é
  acessado somente leitura e não há como gravar essas observações nele.

### `services/`

Camada de regras de negócio. Cada serviço chama funções de `database/`,
executa a consulta, e transforma o resultado bruto (linhas de SQL) em
algo pronto para a tela consumir (normalmente um `DataFrame` do pandas já
calculado/formatado, ou um dicionário de indicadores).

- `fiscal_service.py` - indicadores gerais (cards da Visão Geral), IBS/CBS,
  detalhamento de notas, CFOP, evolução mensal, qualidade de status.
- `conciliacao_service.py` - classifica cada documento como conciliado,
  divergente ou não contabilizado (comparando valor fiscal x valor
  contábil com tolerância), calcula o percentual de conciliação e o tempo
  médio até a contabilização.
- `retencao_service.py` - lista os títulos de retenção e cruza com o
  financeiro para indicar se já foram baixados (usa as consultas de
  `queries.py` que tratam os dois padrões de vínculo mencionados acima).
- `alertas_service.py` - monta os alertas visuais (semáforo) do topo do
  dashboard: percentual de conciliação baixo, pendências antigas, saldo de
  ICMS negativo, problemas de qualidade de dados.
- `qualidade_service.py` - detecta notas duplicadas e notas com valor
  inválido (zero/negativo), para o checklist de qualidade de dados.
- `anotacoes_service.py` - camada fina sobre `database/anotacoes_db.py`,
  adicionando normalização de dados e o usuário atual à anotação.
- `pdf_service.py` - gera o relatório em PDF (via `reportlab`) a partir dos
  dados já calculados pelos outros serviços.

### `utils/`

Utilitários pequenos, sem regra de negócio, usados por várias camadas.

- `formatters.py` - formatação de moeda, quantidade e data no padrão
  brasileiro (ex.: `R$ 1.250.430,75`).
- `logger.py` - configura o logger da aplicação (grava em
  `logs/dashboard.log`, com rotação automática). Feito para ser
  idempotente porque o Streamlit reexecuta o script inteiro a cada
  interação do usuário.

### `logs/`

Pasta gerada automaticamente (não faz parte do código-fonte) onde
`utils/logger.py` grava `dashboard.log`. Pode ser apagada com segurança;
é recriada sozinha na próxima execução.

### `.streamlit/`

Pasta reservada para configuração específica do Streamlit (ex.: um futuro
`config.toml` de tema/porta/servidor). Está vazia atualmente - existe só
para o caso de precisar customizar o Streamlit no futuro.

### `BKPBIFISCAL/`

**Backup manual de uma versão anterior da aplicação inteira** (config/,
database/, services/, utils/, app.py, README.md, DOCUMENTACAO.md,
requirements.txt, etc.), feito antes de um conjunto grande de novas
funcionalidades (retenções, conciliação, PDF, etc.) ser implementado.

Importante: **esta pasta não é executada** - é só uma cópia de referência
para permitir comparar "como era antes" ou reverter manualmente algum
trecho específico se algo quebrar. Não precisa ser mantida sincronizada
com o restante do projeto e não deve ser confundida com a versão ativa.

## Arquivos na raiz

- **`app.py`** - ponto de entrada da aplicação Streamlit (`streamlit run
  app.py`). Monta a página inteira: CSS, cache, sidebar de filtros e as
  abas (Visão Geral, Conciliação Fiscal x Contábil, Documentos, Retenções,
  Retenções x Financeiro). É o único arquivo que sabe sobre Streamlit
  (`st.*`) - toda a lógica de cálculo fica em `services/`.
- **`README.md`** - visão rápida do projeto: funcionalidades, como
  instalar e rodar.
- **`DOCUMENTACAO.md`** - documentação funcional completa e histórico
  detalhado: decisões de projeto, mapeamento de campos do Protheus
  confirmados nesta instalação, descobertas de investigação (como os
  padrões de vínculo de título de retenção), bugs encontrados e
  corrigidos. É o documento de referência para "por que o sistema foi
  feito assim".
- **`.env`** - configuração real desta instalação (credenciais do banco,
  nomes de tabela/campo, limites de alerta). **Nunca deve ser versionado
  nem compartilhado** - está listado no `.gitignore`.
- **`.env.example`** - modelo do `.env`, com todas as variáveis
  documentadas mas sem valores sensíveis. Use como ponto de partida ao
  configurar uma instalação nova.
- **`.gitignore`** - lista o que o Git deve ignorar (`.env`, `__pycache__`,
  `logs/`, etc.).
- **`requirements.txt`** - dependências Python do projeto (`streamlit`,
  `pandas`, `pyodbc`, `python-dotenv`, `plotly`, `reportlab`, `openpyxl`),
  instaláveis com `pip install -r requirements.txt`.
- **`iniciar_dashboard_fiscal.bat`** - atalho para Windows que ativa o
  ambiente Python e roda `streamlit run app.py`, para não precisar abrir
  terminal/digitar comandos toda vez.
- **`logo.png`** - logotipo exibido no cabeçalho do dashboard e nos
  relatórios em PDF.
