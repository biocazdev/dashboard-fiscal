"""Configurações centrais da aplicação.

Carrega as variáveis de ambiente do arquivo ``.env`` e centraliza
todas as configurações do projeto (conexão, tabelas físicas, etc.).

Nenhuma credencial deve ser gravada diretamente no código.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    """Lê uma variável de ambiente no formato booleano.

    Variáveis de ambiente são sempre texto (mesmo quando o ``.env`` tem
    ``ALGO=true``, o Python recebe a string ``"true"``, não o bool
    ``True``) - esta função aceita algumas grafias comuns ("1", "true",
    "yes", "sim", sem diferenciar maiúsc./minúsc.) e trata qualquer outra
    coisa como falso.
    """
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "sim"}


# ---------------------------------------------------------------------------
# Conexão SQL Server
# ---------------------------------------------------------------------------
# Todas as credenciais vêm do .env (nunca do código) - ver
# database/connection.py para como esses valores são usados para montar a
# connection string do pyodbc. Usuário deve ser somente leitura (ver seção
# "Segurança" do README.md).
DB_SERVER: str = os.getenv("DB_SERVER", "").strip()
DB_DATABASE: str = os.getenv("DB_DATABASE", "").strip()
DB_USER: str = os.getenv("DB_USER", "").strip()
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "").strip()
# Nome do driver ODBC instalado na máquina (Painel de Controle > Fontes de
# Dados ODBC, aba "Drivers", no Windows). Precisa bater exatamente com o
# nome do driver instalado - "ODBC Driver 18 for SQL Server" é o mais comum
# hoje em dia, mas instalações mais antigas podem ter só o 17 ou o 13.
DB_DRIVER: str = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server").strip()
# Tempo máximo (segundos) que uma consulta pode rodar antes do pyodbc
# desistir e estourar erro - evita que uma consulta pesada trave o
# dashboard indefinidamente.
DB_TIMEOUT: int = int(os.getenv("DB_TIMEOUT", "15").strip() or "15")

# ---------------------------------------------------------------------------
# Tabelas físicas do Protheus (configuráveis - seção 4 da especificação)
# ---------------------------------------------------------------------------
# TODO: Validar o sufixo das tabelas físicas na instalação (SX3/dicionário).
TABELA_NF_ENTRADA: str = os.getenv("TABELA_NF_ENTRADA", "SF1010").strip()
TABELA_NF_SAIDA: str = os.getenv("TABELA_NF_SAIDA", "SF2010").strip()
# SM0 concentra empresas e filiais (M0_CODIGO / M0_CODFIL).
TABELA_EMPRESAS: str = os.getenv("TABELA_EMPRESAS", "SM0010").strip()
# Cadastros de parceiros (nome/descrição de clientes e fornecedores).
# SA1 = clientes, SA2 = fornecedores (padrão TOTVS).
TABELA_CLIENTES: str = os.getenv("TABELA_CLIENTES", "SA1010").strip()
TABELA_FORNECEDORES: str = os.getenv("TABELA_FORNECEDORES", "SA2010").strip()

# ---------------------------------------------------------------------------
# IBS/CBS (reforma tributária) - calculados pelo Configurador de Tributos
# ---------------------------------------------------------------------------
# Os valores de IBS/CBS ficam gravados em F2D (tributos genéricos calculados),
# relacionados ao item da nota por IDREL -> IDTRIB. Exemplo:
#   F2D.F2D_IDREL = SD2.D2_IDTRIB = SD1.D1_IDTRIB
# Diferencia-se IBS de CBS pelo código do tributo (F2D_TRIB):
#   'SIBS01'/'SCBS01' (saída) e 'EIBS01'/'ECBS01' (entrada), normalmente.
# Ajuste os códigos conforme o dicionário da instalação (SX3).
TABELA_F2D: str = os.getenv("TABELA_F2D", "F2D010").strip()
TABELA_ITEM_ENTRADA: str = os.getenv("TABELA_ITEM_ENTRADA", "SD1010").strip()
TABELA_ITEM_SAIDA: str = os.getenv("TABELA_ITEM_SAIDA", "SD2010").strip()
COD_TRIB_IBS_ENTRADA: str = os.getenv("COD_TRIB_IBS_ENTRADA", "EIBS01").strip()
COD_TRIB_IBS_SAIDA: str = os.getenv("COD_TRIB_IBS_SAIDA", "SIBS01").strip()
COD_TRIB_CBS_ENTRADA: str = os.getenv("COD_TRIB_CBS_ENTRADA", "ECBS01").strip()
COD_TRIB_CBS_SAIDA: str = os.getenv("COD_TRIB_CBS_SAIDA", "SCBS01").strip()

# ---------------------------------------------------------------------------
# Conciliação Fiscal x Contábil (CT2)
# ---------------------------------------------------------------------------
# O vínculo fiscal -> contábil usa a chave padrão TOTVS do CT2:
#   filial + CT2_DOC (documento) + parceiro + CT2_ORIGEM (rotina de origem).
# Como a base está em implantação (sem dados contábeis reais), a chave é
# configurável no .env e deve ser validada após o GO LIVE (ver DOCUMENTACAO.md).
TABELA_CT2: str = os.getenv("TABELA_CT2", "CT2010").strip()
# Códigos de CT2_ORIGEM usados na contabilização de entradas/saídas
# (separados por vírgula). Vazio = considera qualquer origem.
# Ex.: "SE2" (contas a pagar) e "SE1" (contas a receber).
CT2_ORIGEM_ENTRADA: str = os.getenv("CT2_ORIGEM_ENTRADA", "").strip()
CT2_ORIGEM_SAIDA: str = os.getenv("CT2_ORIGEM_SAIDA", "").strip()
# Filtrar linhas do CT2 por CT2_DC (ex.: "3" ou "1,2"). Vazio = todas.
# IMPORTANTE: validar o significado de CT2_DC na instalação após o GO LIVE.
CT2_FILTRO_DC: str = os.getenv("CT2_FILTRO_DC", "").strip()
# Exigir que o parceiro (CT2_CODPAR/CT2_CODCLI/CT2_CODFOR) do lançamento
# contábil bata com o cliente/fornecedor da nota para considerar o documento
# CONCILIADO. Padrão TRUE (mais rigoroso). Desative (false) se a instalação
# NÃO preenche esses campos nos lançamentos automáticos do CT2.
# CONFIRMADO em 14/08/2026 (lote 008820, rotina CT2_ROTINA=MATA460): esta
# instalação (Biocaz) NÃO preenche CT2_CODPAR/CODCLI/CODFOR - por isso FALSE.
CT2_EXIGIR_PARCEIRO: bool = _get_bool("CT2_EXIGIR_PARCEIRO", True)
# Vincular pelo número da nota embutido em CT2_KEY, em vez de CT2_DOC.
# CONFIRMADO em 14/08/2026: nesta instalação, CT2_DOC guarda uma numeração
# interna do lançamento (ex.: "000001"), SEM relação com o número real da
# nota fiscal. O número da nota vem embutido em CT2_KEY (varchar 200), no
# padrão TOTVS: posições 1-6 = filial, 7-15 = documento (9 dígitos), 16-18 =
# série. Validado comparando os 5 lançamentos do lote 008820 (todos com
# CT2_ROTINA=MATA460) com as notas fiscais reais - filial, documento, série,
# data e valor bateram nos 5 casos. Ainda NÃO validado para notas de entrada
# (nenhum lançamento de entrada testado até agora).
CT2_DOC_VIA_KEY: bool = _get_bool("CT2_DOC_VIA_KEY", False)
# Restringe o vínculo via CT2_KEY às linhas cuja CT2_ROTINA esteja nesta
# lista (separados por vírgula; vazio = qualquer rotina). Reduz o risco de
# interpretar o CT2_KEY de um lançamento de outra origem/rotina (que pode
# ter um formato de KEY diferente) como se fosse filial+documento+série.
# CT2_ROTINA_SAIDA=MATA460 está validado (ver CT2_DOC_VIA_KEY acima).
# CT2_ROTINA_ENTRADA ainda não foi validado - preencher quando houver um
# lançamento de entrada real pra conferir o CT2_ROTINA correspondente.
CT2_ROTINA_SAIDA: str = os.getenv("CT2_ROTINA_SAIDA", "").strip()
CT2_ROTINA_ENTRADA: str = os.getenv("CT2_ROTINA_ENTRADA", "").strip()
# Tolerância (valor absoluto) para considerar um documento CONCILIADO.
TOLERANCIA_CONCILIACAO: str = os.getenv("TOLERANCIA_CONCILIACAO", "0.05").strip()
# Rótulos legíveis para o código de CT2_ORIGEM, exibidos na tela em vez do
# código cru (ex.: "SE1" -> "Contas a Receber"). Formato: "CODIGO:Rótulo"
# separados por vírgula. Código sem rótulo mapeado continua aparecendo cru.
# Ex.: CT2_ORIGEM_ROTULOS=SE1:Contas a Receber,SE2:Contas a Pagar,MATA460:Faturamento
CT2_ORIGEM_ROTULOS: str = os.getenv("CT2_ORIGEM_ROTULOS", "").strip()

# ---------------------------------------------------------------------------
# CFOP (Grupo B - Apuração fiscal)
# ---------------------------------------------------------------------------
# Nesta instalação NÃO existe D1_CFOP/D2_CFOP (nome padrão) - confirmado
# via INFORMATION_SCHEMA.COLUMNS em 21/08/2026. O CFOP fica em D1_CF/D2_CF
# (varchar 5): validado comparando valores reais - saída com 5101/5102 e
# entrada com 1406/2556/1551/2101/2102 etc., todos CFOPs plausíveis (4
# dígitos, 1/2 = entrada, 5/6 = saída). D1_TES/D2_TES é um código interno
# (TES, 3 dígitos) que o Protheus usa para DERIVAR o CFOP via cadastro, não
# é o CFOP em si - não usar para esta finalidade. Ajuste os campos abaixo
# se outra instalação usar outro nome.
CAMPO_CFOP_ENTRADA: str = os.getenv("CAMPO_CFOP_ENTRADA", "D1_CF").strip()
CAMPO_CFOP_SAIDA: str = os.getenv("CAMPO_CFOP_SAIDA", "D2_CF").strip()

# ---------------------------------------------------------------------------
# Notas canceladas (Grupo B - Apuração fiscal)
# ---------------------------------------------------------------------------
# F1_STATUS (SF1, varchar 1) e F2_STATUS (SF2, varchar 3) existem nesta
# instalação. Em 21/08/2026, os dados de teste não tinham nenhuma nota
# claramente cancelada: F2_STATUS estava em branco nas 9 notas de saída, e
# F1_STATUS tinha só branco (4 notas) e "A" (46 notas, maioria - parece ser
# o status normal/ativo, não cancelado). Por isso o filtro fica DESLIGADO
# por padrão (vazio) - ative preenchendo com o(s) valor(es) de status que
# representam cancelamento assim que uma nota cancelada real aparecer na
# base (separados por vírgula se houver mais de um valor). O checklist de
# qualidade do dashboard mostra a distribuição atual de F1_STATUS/F2_STATUS
# para ajudar a identificar o valor certo.
STATUS_CANCELADO_ENTRADA: str = os.getenv("STATUS_CANCELADO_ENTRADA", "").strip()
STATUS_CANCELADO_SAIDA: str = os.getenv("STATUS_CANCELADO_SAIDA", "").strip()

# ---------------------------------------------------------------------------
# Alertas visuais (semáforo)
# ---------------------------------------------------------------------------
# Limites configuráveis para os avisos exibidos no topo do dashboard. Todos
# têm um padrão razoável, mas devem ser ajustados conforme a realidade da
# empresa (ex.: uma base em implantação, como esta, pode ter % de
# conciliação baixo por um bom tempo sem que isso seja um problema real).
# % mínimo de conciliação esperado (abaixo disso, aviso). 0.80 = 80%.
ALERTA_PCT_CONCILIACAO_MIN: float = float(
    os.getenv("ALERTA_PCT_CONCILIACAO_MIN", "0.80").strip() or "0.80"
)
# Idade (em dias) a partir da qual uma pendência (não contabilizada ou
# divergente) é considerada "muito antiga" e gera aviso.
ALERTA_IDADE_PENDENCIA_DIAS: int = int(
    os.getenv("ALERTA_IDADE_PENDENCIA_DIAS", "30").strip() or "30"
)
# Avisa quando o Saldo de ICMS ficar negativo (crédito acumulado). Padrão
# ligado - desative (false) se isso for normal para o perfil da empresa.
ALERTA_SALDO_ICMS_CREDITO: bool = _get_bool("ALERTA_SALDO_ICMS_CREDITO", True)
# Avisa quando o Saldo de ICMS (positivo ou negativo) ultrapassar este valor
# absoluto. Vazio (padrão) = desligado - defina um valor de referência da
# empresa para ativar.
ALERTA_SALDO_ICMS_MAX: str = os.getenv("ALERTA_SALDO_ICMS_MAX", "").strip()

# ---------------------------------------------------------------------------
# Retenções (IR/PIS/COFINS/CSLL) - Contas a Pagar (SE2)
# ---------------------------------------------------------------------------
# Aba "Retenções" - equivalente ao relatório Reinf R-4020 (Pagamentos/
# Créditos a beneficiário PJ) que o contador já gera fora do dashboard.
# Diferente do resto do dashboard (SF1/SF2 - notas fiscais), esta aba lê os
# TÍTULOS de contas a pagar (SE2), onde ficam as retenções sobre pagamentos
# a fornecedores PJ.
# CONFIRMADO em 25/08/2026 (Biocaz): os valores retidos ficam em
# E2_IRRF/E2_PIS/E2_COFINS/E2_CSLL (validado recalculando as alíquotas
# padrão - 1,5% IR, 0,65% PIS, 3% COFINS, 1% CSLL - contra 2 títulos reais e
# batendo exatamente). NÃO usar E2_VRETIRF/E2_VRETPIS/E2_VRETCOF/E2_VRETCSL -
# ficaram zerados em todos os 85 títulos testados nesta instalação. COFINS
# segue o mesmo padrão de truncamento "COF" já visto em SD1/SD2
# (E2_BASECOF/E2_COFINS).
TABELA_CP: str = os.getenv("TABELA_CP", "SE2010").strip()

# Campo de CNPJ/CPF no cadastro de fornecedores (SA2) - nome padrão TOTVS.
# AINDA NÃO validado explicitamente nesta instalação (a investigação das
# retenções não chegou a consultar a SA2). Ajuste se a instalação usar outro
# nome de campo.
CAMPO_CNPJ_FORNECEDOR: str = os.getenv("CAMPO_CNPJ_FORNECEDOR", "A2_CGC").strip()

# "Cod. R" (código de natureza de rendimento do Reinf, ex.: 15014, 15099) -
# INVESTIGADO em 25/08/2026 e CONFIRMADO que não existe em nenhuma tabela
# acessível pelo banco desta instalação: E2_CODRET (no título) veio em
# branco nos 85 títulos testados, e os campos equivalentes na SED010
# (cadastro de Natureza financeira) - ED_CODRET, ED_NATREN, ED_GRPNAT,
# ED_INDRET - vieram em branco nas 38 naturezas cadastradas. Esse código
# provavelmente só é calculado pelo módulo Gerador EFD-Reinf na hora de
# gerar o evento oficial, fora do alcance do banco só-leitura.
# Solução: mapeamento manual e opcional de E2_NATUREZ -> Cod. R, no mesmo
# padrão de CT2_ORIGEM_ROTULOS. Formato "NATUREZA:CODIGO" separados por
# vírgula. Vazio (padrão) = coluna "Cod. R" em branco para todas as linhas.
# Ex.: RETENCAO_NATUREZA_CODRET=0000000001:15014,0000000002:15099
RETENCAO_NATUREZA_CODRET: str = os.getenv("RETENCAO_NATUREZA_CODRET", "").strip()

# ---------------------------------------------------------------------------
# Validação Retenções x Financeiro (SE2 x SE2) - 25/08/2026, REDESENHADA
# ---------------------------------------------------------------------------
# Descoberta em 25/08/2026 (Biocaz, título 000000002-1 testado ao vivo pelo
# cliente): a hipótese original (SE2 x SEF010, vínculo por
# FILIAL+PREFIXO+NÚMERO+PARCELA+FORNECEDOR) estava ERRADA. O Protheus não
# baixa o valor retido dentro do próprio movimento financeiro do título -
# ele gera um SEGUNDO TÍTULO na própria SE2010, com o MESMO
# FILIAL+PREFIXO+NÚMERO do título original, mas:
#   - E2_TIPO = 'TX'               (o título "pai"/NF é 'VL' - valor)
#   - E2_NATUREZ = código do tributo: 'IRF' / 'PIS' / 'COF' / 'CSL'
#   - E2_FORNECE = credor da guia (ex.: "UNIAO" para tributos federais, ou
#     um código de fornecedor específico para retenções estaduais/ICMS-ST -
#     não é o mesmo fornecedor do título original)
#   - E2_VALOR = o valor retido daquele tributo (confirmado batendo exato
#     com E2_IRRF/E2_PIS/E2_COFINS/E2_CSLL do título original)
#   - E2_BAIXA própria, independente da baixa do título original - dá pra
#     pagar a guia do imposto (título TX) antes, depois ou nunca em relação
#     à baixa do valor líquido ao fornecedor (título VL).
# A validação faz um SELF JOIN na SE2010, cobrindo DOIS padrões diferentes
# de geração encontrados nesta instalação (descobertos em duas rodadas de
# teste ao vivo com o cliente, mesmo dia):
#
#   Padrão A: título "irmão" com o MESMO FILIAL+PREFIXO+NÚMERO do título
#   original, E2_TIPO='TX', tributo em E2_NATUREZ (IRF/PIS/COF/CSL). Sem
#   PARCELA no vínculo (o título TX observado trouxe E2_PARCELA="01"
#   contra "1" no original - formatos diferentes) e sem FORNECEDOR (o
#   credor do TX não é o fornecedor original, ex. "UNIAO"). Confirmado com
#   o título 000000002-1 (fornecedor 000004).
#
#   Padrão B: título com numeração PRÓPRIA (prefixo "TG", gerado pela
#   rotina MATA100 - ver E2_ORIGEM), onde o tributo já vem direto em
#   E2_TIPO (IRF/PIS/COF/CSL). NÃO existe nenhum campo estruturado de
#   vínculo com o título original nesta instalação - `E2_ORIGEM` só grava
#   o nome da rotina geradora ("MATA100"), e `E2_DOCHAB`/`E2_NFELETR`
#   vêm em branco. O ÚNICO vínculo disponível é o texto livre do
#   Histórico (`E2_HIST`), no formato "<lote> - NF: <número> / <série>"
#   (ex.: "E00081 - NF: 58 / NFS") - o número/série são extraídos via
#   CHARINDEX/SUBSTRING e comparados com E2_NUM/E2_PREFIXO do título
#   original. FRÁGIL por natureza (depende do formato do texto se manter
#   estável) - é o único vínculo que a investigação encontrou depois de
#   duas varreduras de colunas candidatas na SE2010. Confirmado com o
#   título NFS58-01 (fornecedor 000316): os 4 tributos retidos batem
#   exatamente com TG0000002/TG0000003/TG0000004/TG0000005.
#
# Nenhum dos dois padrões usa mais SEF010/TABELA_FINANCEIRO. Ainda não
# confirmado: títulos com mais de uma parcela (o vínculo sem PARCELA pode
# somar retenções de parcelas diferentes juntas) e se o formato do texto
# do Histórico (Padrão B) é realmente constante em toda a base histórica
# (só foi confirmado nos títulos testados ao vivo em 25/08/2026).
TABELA_FINANCEIRO: str = os.getenv("TABELA_FINANCEIRO", "SEF010").strip()
"""Não usada mais pela validação Retenções x Financeiro (ver comentário
acima) - mantida apenas por compatibilidade com .env já configurados."""

# ---------------------------------------------------------------------------
# Anotações locais por documento (bloco "Produtividade")
# ---------------------------------------------------------------------------
# Como o Protheus é acessado somente leitura, as observações do contador
# sobre um documento (ex.: "aguardando NF do fornecedor") ficam guardadas
# localmente neste arquivo SQLite, ao lado da aplicação - não no Protheus.
ANOTACOES_DB: str = os.getenv("ANOTACOES_DB", "anotacoes.db").strip()
