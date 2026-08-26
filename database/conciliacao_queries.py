"""Consultas SQL da conciliação Fiscal x Contábil (CT2).

Regras desta camada (mesmas de ``queries.py``):
- Nenhum SQL é montado no ``app.py`` nem no serviço.
- Valores vindos do usuário (filial, datas) são sempre enviados via parâmetros.
- Os nomes das tabelas físicas são configuráveis e validados antes de serem
  interpolados no SQL.
- ``filiais`` chega aqui como lista (visão consolidada multi-filial); o SQL
  usa ``IN (...)`` em vez de ``= ?``.

Chave de ligação (CT2):
    filial + documento + parceiro (opcional via CT2_EXIGIR_PARCEIRO) +
    CT2_ORIGEM (rotina de origem, configurável e vazio = qualquer).

    O "documento" normalmente é CT2_DOC. NESTA INSTALAÇÃO (Biocaz), porém,
    CT2_DOC guarda uma numeração interna do lançamento (ex.: "000001"), SEM
    relação com o número real da nota fiscal - CONFIRMADO em 14/08/2026
    comparando os 5 lançamentos do lote 008820 (rotina CT2_ROTINA=MATA460)
    com as notas fiscais reais (filial, número, série, data e valor
    bateram nos 5 casos). O número real da nota vem embutido no campo
    CT2_KEY (varchar 200, padrão TOTVS): posições 1-6 = filial, 7-15 =
    documento (9 dígitos), 16-18 = série. Ative CT2_DOC_VIA_KEY (.env) para
    usar CT2_KEY em vez de CT2_DOC - ver ``_vinculo_doc_saida``/
    ``_vinculo_doc_entrada`` e ``config.settings``.

Também CONFIRMADO em 14/08/2026: CT2_CODPAR/CT2_CODCLI/CT2_CODFOR não são
preenchidos nos lançamentos desta instalação - por isso
CT2_EXIGIR_PARCEIRO=false no .env.

Validado até agora só para saídas (CT2_ROTINA=MATA460). Vínculo de entrada
via CT2_KEY ainda não foi conferido com um lançamento real.

A base está em implantação, então a chave e o filtro de CT2_DC também devem
ser revalidados após o GO LIVE (ver DOCUMENTACAO.md, seção 12).
"""

import re

from config import settings

# Nomes de tabela devem conter apenas letras, números e underline.
_TABELA_VALIDA = re.compile(r"^[A-Za-z0-9_]+$")


def _tabela_conc(nome: str) -> str:
    """Valida o nome da tabela física antes de interpolar no SQL.

    Os nomes de tabela vêm de ``config.settings`` (configuráveis via .env),
    não de input do usuário final - mas como entram na string do SQL via
    ``.format()`` (e não como parâmetro "?"), ainda assim precisam ser
    validados aqui contra a regex acima antes de qualquer interpolação,
    para não abrir brecha caso o .env seja alterado de forma inesperada
    (ou por engano) com um valor que contenha SQL arbitrário.
    """
    if not _TABELA_VALIDA.fullmatch(nome):
        raise ValueError(f"Nome de tabela inválido: {nome!r}")
    return nome


def _in_clause(coluna: str, valores: list[str]) -> tuple[str, list[str]]:
    """Monta ``coluna IN (?, ?, ...)`` a partir de uma lista de filiais.

    O número de "?" é gerado dinamicamente a partir do tamanho de
    ``valores`` (visão consolidada pode ter 1 ou N filiais) - por isso não
    dá para usar um SQL fixo com "?" pré-contado para esse filtro.
    """
    placeholders = ", ".join("?" for _ in valores)
    return f"{coluna} IN ({placeholders})", list(valores)


def _filtro_origem(codigos: str) -> tuple[str, list[str]]:
    """Monta o filtro de CT2_ORIGEM. Vazio = considera qualquer origem.

    ``codigos`` vem de configuração (.env), não de input do usuário, mas
    mesmo assim os valores são passados como parâmetros ("?"), nunca
    interpolados na string - só a cláusula/quantidade de "?" é montada
    dinamicamente. Retorna string vazia quando não há filtro configurado,
    para que o placeholder {FILTRO_ORIGEM} no SQL vire uma linha em branco
    (sintaticamente inofensiva).
    """
    codigos = [c.strip() for c in codigos.split(",") if c.strip()]
    if not codigos:
        return "", []
    clausula = " AND CT2.CT2_ORIGEM IN (" + ", ".join("?" for _ in codigos) + ")"
    return clausula, codigos


def _filtro_dc() -> tuple[str, list[str]]:
    """Monta o filtro de CT2_DC. Vazio = considera todas as linhas.

    CT2_DC normalmente marca débito/crédito do lançamento contábil. Como o
    significado exato de CT2_DC ainda não foi validado nesta instalação
    (ver docstring do módulo), o filtro fica desligado por padrão e só é
    ativado explicitamente via ``CT2_FILTRO_DC`` no .env depois de validar
    um lote conhecido.
    """
    dc = [c.strip() for c in settings.CT2_FILTRO_DC.split(",") if c.strip()]
    if not dc:
        return "", []
    clausula = " AND CT2.CT2_DC IN (" + ", ".join("?" for _ in dc) + ")"
    return clausula, dc


def _filtro_rotina(codigos: str) -> tuple[str, list[str]]:
    """Monta o filtro de CT2_ROTINA. Vazio = considera qualquer rotina.

    Diferente de ``_filtro_origem``/``_filtro_dc``, a cláusula aqui NÃO
    começa com espaço antes do "AND" porque quem chama
    (``_vinculo_doc_saida``/``_vinculo_doc_entrada``) sempre concatena esse
    retorno logo depois de uma string que já termina com espaço.
    RTRIM é necessário porque CT2_ROTINA é um campo CHAR de tamanho fixo no
    Protheus (vem preenchido com espaços à direita).
    """
    codigos = [c.strip() for c in codigos.split(",") if c.strip()]
    if not codigos:
        return "", []
    clausula = "AND RTRIM(CT2.CT2_ROTINA) IN (" + ", ".join("?" for _ in codigos) + ")"
    return clausula, codigos


def _vinculo_doc_saida() -> tuple[str, list[str]]:
    """Cláusula (e parâmetros) que vincula o CT2 ao documento de saída (F2).

    Padrão: compara CT2_DOC diretamente com F2_DOC. Quando
    ``settings.CT2_DOC_VIA_KEY`` está ligado, usa o número da nota embutido
    em CT2_KEY (posições 7-15) e a série (posições 16-18) em vez de
    CT2_DOC - necessário quando CT2_DOC guarda uma numeração interna do
    lançamento, não o número da nota (ver docstring do módulo).

    SUBSTRING(CT2_KEY, 7, 9)/(16, 3): índices em BASE 1 (padrão SQL Server,
    não base 0), correspondendo às posições 7-15 (documento, 9 dígitos) e
    16-18 (série, 3 dígitos) descritas na docstring do módulo. Quando o modo
    via-KEY está ligado, também aplica o filtro de CT2_ROTINA para
    restringir a rotinas de saída conhecidas (ex.: MATA460) - importante
    porque CT2_KEY é um campo genérico usado por várias rotinas do Protheus,
    então sem esse filtro poderíamos casar com lançamentos de outra origem
    que por coincidência têm os mesmos dígitos nessas posições.

    Retorna (cláusula_sql, parâmetros_dessa_cláusula) - os parâmetros aqui
    são só os do filtro de rotina (lista vazia quando CT2_DOC_VIA_KEY está
    desligado, já que a comparação direta CT2_DOC = F2_DOC não usa "?").
    """
    if not settings.CT2_DOC_VIA_KEY:
        return "RTRIM(CT2.CT2_DOC) = RTRIM(F2.F2_DOC)", []
    rotina, rotina_params = _filtro_rotina(settings.CT2_ROTINA_SAIDA)
    clausula = (
        "RTRIM(SUBSTRING(CT2.CT2_KEY, 7, 9)) = RTRIM(F2.F2_DOC) "
        "AND RTRIM(SUBSTRING(CT2.CT2_KEY, 16, 3)) = RTRIM(F2.F2_SERIE) "
        + rotina
    )
    return clausula, rotina_params


def _vinculo_doc_entrada() -> tuple[str, list[str]]:
    """Ver ``_vinculo_doc_saida``; versão para notas de entrada (F1).

    Mesma lógica, mas ainda NÃO validada com um lançamento real via KEY
    (ver docstring do módulo) - usar com cautela enquanto
    CT2_DOC_VIA_KEY estiver ligado para entradas.
    """
    if not settings.CT2_DOC_VIA_KEY:
        return "RTRIM(CT2.CT2_DOC) = RTRIM(F1.F1_DOC)", []
    rotina, rotina_params = _filtro_rotina(settings.CT2_ROTINA_ENTRADA)
    clausula = (
        "RTRIM(SUBSTRING(CT2.CT2_KEY, 7, 9)) = RTRIM(F1.F1_DOC) "
        "AND RTRIM(SUBSTRING(CT2.CT2_KEY, 16, 3)) = RTRIM(F1.F1_SERIE) "
        + rotina
    )
    return clausula, rotina_params


def _filtro_parceiro_saida() -> str:
    """Cláusula que exige o vínculo do parceiro (cliente) nas saídas.

    Controlada por ``CT2_EXIGIR_PARCEIRO``. Quando desligada (instalação
    que não preenche CT2_CODPAR/CT2_CODCLI nos lançamentos automáticos),
    o vínculo passa a valer só por filial + CT2_DOC (+ origem/DC).
    """
    if not settings.CT2_EXIGIR_PARCEIRO:
        return ""
    # OR entre CODPAR/CODCLI: instalações diferentes do Protheus podem
    # gravar o cliente em um campo genérico (CT2_CODPAR) ou no específico
    # (CT2_CODCLI) - o OR cobre as duas possibilidades sem precisar saber
    # qual delas a instalação usa.
    return (
        "AND (RTRIM(CT2.CT2_CODPAR) = RTRIM(F2.F2_CLIENTE) "
        "OR RTRIM(CT2.CT2_CODCLI) = RTRIM(F2.F2_CLIENTE))"
    )


def _filtro_parceiro_entrada() -> str:
    """Cláusula que exige o vínculo do parceiro (fornecedor) nas entradas.

    Ver ``_filtro_parceiro_saida`` para o comportamento de
    ``CT2_EXIGIR_PARCEIRO``.
    """
    if not settings.CT2_EXIGIR_PARCEIRO:
        return ""
    # Mesma lógica de OR entre campo genérico (CODPAR) e específico
    # (CODFOR) explicada em ``_filtro_parceiro_saida``.
    return (
        "AND (RTRIM(CT2.CT2_CODPAR) = RTRIM(F1.F1_FORNECE) "
        "OR RTRIM(CT2.CT2_CODFOR) = RTRIM(F1.F1_FORNECE))"
    )


# ---------------------------------------------------------------------------
# Conciliação das notas de saída (SF2 x CT2)
# ---------------------------------------------------------------------------
# Uma nota pode gerar várias partidas contábeis; por isso o lado contábil é
# AGREGADO por documento (soma) e não comparado linha a linha.
# CT2_DC/CT2_VALOR: a soma usa todos os valores do CT2; se a instalação
# gravar débito e crédito em linhas separadas, defina CT2_FILTRO_DC no .env
# para somar apenas um dos lados (validar após o GO LIVE).
SQL_CONCILIACAO_SAIDA = """
SELECT
    'Saida' AS TIPO,
    F2.F2_FILIAL AS FILIAL,
    F2.F2_DOC AS DOC,
    F2.F2_SERIE AS SERIE,
    F2.F2_EMISSAO AS EMISSAO,
    F2.F2_CLIENTE AS PARCEIRO,
    F2.F2_VALBRUT AS VALOR_FISCAL,
    -- COUNT(CT2.R_E_C_N_O_) conta só linhas com R_E_C_N_O_ não-nulo: como o
    -- JOIN é LEFT, uma nota sem lançamento contábil correspondente gera uma
    -- linha com todos os campos de CT2 nulos (inclusive R_E_C_N_O_), então
    -- COUNT(coluna) aqui dá 0 - diferente de COUNT(*), que contaria 1.
    CASE WHEN COUNT(CT2.R_E_C_N_O_) > 0 THEN 1 ELSE 0 END AS TEM_LANCAMENTO,
    -- ISNULL(SUM(...), 0): SUM de um grupo sem nenhuma linha real (só a
    -- linha "fantasma" do LEFT JOIN) retorna NULL, não 0 - por isso o
    -- ISNULL para o front-end nunca receber NULL em VALOR_CONTABIL.
    ISNULL(SUM(CT2.CT2_VALOR), 0) AS VALOR_CONTABIL,
    ISNULL(MAX(RTRIM(CT2.CT2_LOTE)), '') AS LOTE,
    ISNULL(MAX(CT2.CT2_DATA), '') AS DATA_CONTABIL,
    COUNT(CT2.R_E_C_N_O_) AS QTDE_LANCAMENTOS
FROM {TABELA_NF_SAIDA} F2
-- LEFT JOIN (não INNER JOIN) é essencial: o objetivo da conciliação é
-- justamente listar também as notas fiscais que NÃO têm lançamento
-- contábil correspondente (TEM_LANCAMENTO = 0), então perder essas notas
-- por causa de um INNER JOIN quebraria a análise.
LEFT JOIN {TABELA_CT2} CT2
    ON RTRIM(CT2.CT2_FILIAL) = RTRIM(F2.F2_FILIAL)
   AND {VINCULO_DOC}
   -- D_E_L_E_T_ = '' precisa estar na condição do JOIN (não no WHERE):
   -- como o JOIN é LEFT, colocar esse filtro no WHERE transformaria o
   -- LEFT JOIN em INNER JOIN de fato (linhas com CT2 nulo seriam
   -- descartadas pelo WHERE), voltando a esconder notas sem lançamento.
   AND CT2.D_E_L_E_T_ = ''
   {FILTRO_PARCEIRO}
   {FILTRO_ORIGEM}
   {FILTRO_DC}
WHERE F2.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2.F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
-- GROUP BY precisa listar exatamente as colunas não-agregadas do SELECT
-- (exigência do SQL Server); como cada nota (F2_FILIAL+F2_DOC+F2_SERIE) é
-- única, isso na prática agrupa por nota e soma todas as partidas
-- contábeis (CT2) vinculadas a ela.
GROUP BY F2.F2_FILIAL, F2.F2_DOC, F2.F2_SERIE, F2.F2_EMISSAO,
         F2.F2_CLIENTE, F2.F2_VALBRUT
ORDER BY F2.F2_EMISSAO, F2.F2_DOC
"""

# ---------------------------------------------------------------------------
# Conciliação das notas de entrada (SF1 x CT2)
# ---------------------------------------------------------------------------
# Espelho de SQL_CONCILIACAO_SAIDA (mesmos truques: LEFT JOIN para não
# perder nota sem lançamento, COUNT(R_E_C_N_O_) para detectar linha
# "fantasma" do LEFT JOIN, ISNULL para nunca devolver NULL, D_E_L_E_T_ do
# CT2 dentro do ON, GROUP BY casando com as colunas não-agregadas) - ver os
# comentários daquele bloco para o detalhe de cada um.
SQL_CONCILIACAO_ENTRADA = """
SELECT
    'Entrada' AS TIPO,
    F1.F1_FILIAL AS FILIAL,
    F1.F1_DOC AS DOC,
    F1.F1_SERIE AS SERIE,
    F1.F1_EMISSAO AS EMISSAO,
    F1.F1_FORNECE AS PARCEIRO,
    F1.F1_VALBRUT AS VALOR_FISCAL,
    CASE WHEN COUNT(CT2.R_E_C_N_O_) > 0 THEN 1 ELSE 0 END AS TEM_LANCAMENTO,
    ISNULL(SUM(CT2.CT2_VALOR), 0) AS VALOR_CONTABIL,
    ISNULL(MAX(RTRIM(CT2.CT2_LOTE)), '') AS LOTE,
    ISNULL(MAX(CT2.CT2_DATA), '') AS DATA_CONTABIL,
    COUNT(CT2.R_E_C_N_O_) AS QTDE_LANCAMENTOS
FROM {TABELA_NF_ENTRADA} F1
LEFT JOIN {TABELA_CT2} CT2
    ON RTRIM(CT2.CT2_FILIAL) = RTRIM(F1.F1_FILIAL)
   AND {VINCULO_DOC}
   AND CT2.D_E_L_E_T_ = ''
   {FILTRO_PARCEIRO}
   {FILTRO_ORIGEM}
   {FILTRO_DC}
WHERE F1.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1.F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
GROUP BY F1.F1_FILIAL, F1.F1_DOC, F1.F1_SERIE, F1.F1_EMISSAO,
         F1.F1_FORNECE, F1.F1_VALBRUT
ORDER BY F1.F1_EMISSAO, F1.F1_DOC
"""

# ---------------------------------------------------------------------------
# Lançamentos contábeis sem documento fiscal correspondente (Nível 4)
# ---------------------------------------------------------------------------
# Caminho inverso dos dois blocos acima: aqui partimos do CT2 (lado
# contábil) e procuramos lançamentos que NÃO batem com nenhuma nota fiscal,
# nem de entrada nem de saída - candidatos a lançamento manual, erro de
# rotina de origem ou lançamento de outra natureza (ex.: ajuste contábil)
# sem relação com uma NF-e.
SQL_SEM_ORIGEM_FISCAL = """
SELECT
    'Contabil' AS TIPO,
    CT2.CT2_FILIAL AS FILIAL,
    RTRIM(CT2.CT2_DOC) AS DOC,
    RTRIM(CT2.CT2_ORIGEM) AS ORIGEM,
    RTRIM(CT2.CT2_CODPAR) AS PARCEIRO,
    ISNULL(MAX(CT2.CT2_DATA), '') AS EMISSAO,
    ISNULL(MAX(RTRIM(CT2.CT2_LOTE)), '') AS LOTE,
    SUM(CT2.CT2_VALOR) AS VALOR_CONTABIL
FROM {TABELA_CT2} CT2
WHERE CT2.D_E_L_E_T_ = ''
  {FILTRO_DC}
  AND {FILIAL}
  AND CT2.CT2_DATA BETWEEN ? AND ?
  -- NOT EXISTS (em vez de LEFT JOIN ... IS NULL): mais claro para expressar
  -- "não existe nenhuma NF de entrada que bata com este lançamento", e evita
  -- multiplicar linhas de CT2 caso existisse mais de um match possível.
  -- As duas subconsultas (entrada e saída) reutilizam o mesmo vínculo de
  -- documento (CT2_DOC ou CT2_KEY, conforme CT2_DOC_VIA_KEY) e o mesmo
  -- filtro de parceiro usados nos blocos de conciliação acima, para manter
  -- a mesma definição de "bate com uma nota fiscal" em todo o dashboard.
  AND NOT EXISTS (
      SELECT 1 FROM {TABELA_NF_ENTRADA} F1
      WHERE F1.D_E_L_E_T_ = ''
        AND RTRIM(F1.F1_FILIAL) = RTRIM(CT2.CT2_FILIAL)
        AND {VINCULO_DOC_ENTRADA}
        {FILTRO_PARCEIRO_ENTRADA}
  )
  AND NOT EXISTS (
      SELECT 1 FROM {TABELA_NF_SAIDA} F2
      WHERE F2.D_E_L_E_T_ = ''
        AND RTRIM(F2.F2_FILIAL) = RTRIM(CT2.CT2_FILIAL)
        AND {VINCULO_DOC_SAIDA}
        {FILTRO_PARCEIRO_SAIDA}
  )
-- Agrupa por documento contábil (não por filial+data) para consolidar as
-- várias partidas de um mesmo lançamento em uma única linha, somando
-- CT2_VALOR - mesmo raciocínio de agregação usado nos dois SELECTs acima.
GROUP BY CT2.CT2_FILIAL, CT2.CT2_DOC, CT2.CT2_ORIGEM, CT2.CT2_CODPAR
ORDER BY CT2.CT2_FILIAL, CT2.CT2_DOC
"""


def sql_conciliacao_saida(
    filiais: list[str], cliente: str | None = None
) -> tuple[str, list[str]]:
    """SQL de conciliação das saídas + parâmetros (prefixo, na ordem do SQL).

    Quando ``cliente`` é informado, adiciona o filtro de SF2.

    A ordem de ``vinculo_params + origem_params + dc_params + filiais_params``
    segue a ordem em que os "?" aparecem no texto do SQL (todos dentro do
    ON do LEFT JOIN, antes do WHERE): vínculo de documento (rotina, só
    quando CT2_DOC_VIA_KEY está ligado) -> CT2_ORIGEM -> CT2_DC -> filiais
    (IN). O parâmetro do filtro de cliente (quando ``cliente`` é passado)
    NÃO entra aqui: como ele fica no WHERE, depois de F2_EMISSAO BETWEEN,
    quem chamar esta função precisa adicioná-lo por conta própria ao final
    da lista de parâmetros, junto com data_ini/data_fim.
    """
    vinculo, vinculo_params = _vinculo_doc_saida()
    origem, origem_params = _filtro_origem(settings.CT2_ORIGEM_SAIDA)
    dc, dc_params = _filtro_dc()
    filiais_sql, filiais_params = _in_clause("F2.F2_FILIAL", filiais)
    filtro_cliente = "AND F2.F2_CLIENTE = ?" if cliente else ""
    sql = SQL_CONCILIACAO_SAIDA.format(
        TABELA_NF_SAIDA=_tabela_conc(settings.TABELA_NF_SAIDA),
        TABELA_CT2=_tabela_conc(settings.TABELA_CT2),
        VINCULO_DOC=vinculo,
        FILTRO_PARCEIRO=_filtro_parceiro_saida(),
        FILTRO_ORIGEM=origem,
        FILTRO_DC=dc,
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro_cliente,
    )
    return sql, vinculo_params + origem_params + dc_params + filiais_params


def sql_conciliacao_entrada(
    filiais: list[str], fornecedor: str | None = None
) -> tuple[str, list[str]]:
    """SQL de conciliação das entradas + parâmetros (prefixo, na ordem do SQL).

    Quando ``fornecedor`` é informado, adiciona o filtro de SF1.

    Mesma ordem/regra de ``sql_conciliacao_saida``: os parâmetros retornados
    (``vinculo_params + origem_params + dc_params + filiais_params``) cobrem
    só os "?" do JOIN; quem chamar deve completar com
    ``[data_ini, data_fim]`` e, se houver ``fornecedor``, o valor do filtro
    de fornecedor, nessa ordem, ao final.
    """
    vinculo, vinculo_params = _vinculo_doc_entrada()
    origem, origem_params = _filtro_origem(settings.CT2_ORIGEM_ENTRADA)
    dc, dc_params = _filtro_dc()
    filiais_sql, filiais_params = _in_clause("F1.F1_FILIAL", filiais)
    filtro_forn = "AND F1.F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_CONCILIACAO_ENTRADA.format(
        TABELA_NF_ENTRADA=_tabela_conc(settings.TABELA_NF_ENTRADA),
        TABELA_CT2=_tabela_conc(settings.TABELA_CT2),
        VINCULO_DOC=vinculo,
        FILTRO_PARCEIRO=_filtro_parceiro_entrada(),
        FILTRO_ORIGEM=origem,
        FILTRO_DC=dc,
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro_forn,
    )
    return sql, vinculo_params + origem_params + dc_params + filiais_params


def sql_sem_origem_fiscal(filiais: list[str]) -> tuple[str, list[str], list[str]]:
    """SQL dos lançamentos contábeis sem documento fiscal correspondente.

    Retorna ``(sql, params_antes_filial_data, params_depois_filial_data)``.
    Os dois grupos ficam em posições diferentes do texto do SQL (o filtro de
    CT2_DC vem antes de filial/período; o vínculo por documento das duas
    subconsultas NOT EXISTS vem depois), por isso são retornados separados -
    quem chamar deve intercalar ``filiais + [data_ini, data_fim]`` entre eles.

    Ou seja, a lista final de parâmetros a passar para o driver deve ser
    montada assim, na ordem exata dos "?" do SQL:
        dc_params + filiais_params + [data_ini, data_fim]
        + vinculo_entrada_params + vinculo_saida_params
    (``filiais_params`` já vem embutido no primeiro grupo retornado, junto
    de ``dc_params``; ``vinculo_entrada_params``/``vinculo_saida_params``
    só têm conteúdo quando ``CT2_DOC_VIA_KEY`` está ligado e um filtro de
    rotina configurado).
    """
    dc, dc_params = _filtro_dc()
    vinculo_entrada, vinculo_entrada_params = _vinculo_doc_entrada()
    vinculo_saida, vinculo_saida_params = _vinculo_doc_saida()
    filiais_sql, filiais_params = _in_clause("CT2.CT2_FILIAL", filiais)
    sql = SQL_SEM_ORIGEM_FISCAL.format(
        TABELA_CT2=_tabela_conc(settings.TABELA_CT2),
        TABELA_NF_ENTRADA=_tabela_conc(settings.TABELA_NF_ENTRADA),
        TABELA_NF_SAIDA=_tabela_conc(settings.TABELA_NF_SAIDA),
        FILTRO_DC=dc,
        FILIAL=filiais_sql,
        VINCULO_DOC_ENTRADA=vinculo_entrada,
        FILTRO_PARCEIRO_ENTRADA=_filtro_parceiro_entrada(),
        VINCULO_DOC_SAIDA=vinculo_saida,
        FILTRO_PARCEIRO_SAIDA=_filtro_parceiro_saida(),
    )
    return (
        sql,
        dc_params + filiais_params,
        vinculo_entrada_params + vinculo_saida_params,
    )


# ---------------------------------------------------------------------------
# Qualidade dos dados: lotes contábeis com saldo diferente de zero
# ---------------------------------------------------------------------------
# ATENÇÃO: esta checagem soma CT2_VALOR por lote sem considerar o sinal de
# débito/crédito (CT2_DC), porque o significado de CT2_DC ainda não foi
# validado nesta instalação. Se a instalação gravar débito e crédito com o
# mesmo sinal, todo lote vai aparecer aqui - valide um lote conhecido antes
# de confiar neste indicador (ver DOCUMENTACAO.md).
SQL_LOTES_SALDO = """
SELECT
    RTRIM(CT2.CT2_LOTE) AS LOTE,
    SUM(CT2.CT2_VALOR) AS SALDO,
    COUNT(*) AS QTDE_LANCAMENTOS,
    MAX(CT2.CT2_DATA) AS DATA
FROM {TABELA_CT2} CT2
WHERE CT2.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND CT2.CT2_DATA BETWEEN ? AND ?
  -- Ignora lançamentos sem lote (CT2_LOTE em branco): não fazem parte de
  -- um lote de contabilização propriamente dito, então não se aplicam à
  -- checagem de "lote deveria fechar em zero".
  AND RTRIM(CT2.CT2_LOTE) <> ''
GROUP BY CT2.CT2_LOTE
-- HAVING (não WHERE) porque o filtro depende do resultado agregado
-- (SUM por lote), que só existe depois do GROUP BY. O "?" aqui é a
-- tolerância/threshold de saldo (ex.: ignorar diferenças de centavos por
-- arredondamento).
HAVING ABS(SUM(CT2.CT2_VALOR)) > ?
ORDER BY ABS(SUM(CT2.CT2_VALOR)) DESC
"""


def sql_lotes_saldo_diferente_zero(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL dos lotes contábeis (CT2) cuja soma de CT2_VALOR não fecha em zero.

    Retorna só o prefixo de parâmetros (``filiais_params``, do IN de
    filial). Quem chamar deve completar a lista, na ordem dos "?" restantes
    do SQL, com ``[data_ini, data_fim, tolerancia]`` - a tolerância é o
    valor comparado no HAVING ABS(SUM(...)) > ? (ver ATENÇÃO no
    ``SQL_LOTES_SALDO`` sobre o sinal de CT2_DC ainda não validado).
    """
    filiais_sql, filiais_params = _in_clause("CT2.CT2_FILIAL", filiais)
    sql = SQL_LOTES_SALDO.format(
        TABELA_CT2=_tabela_conc(settings.TABELA_CT2),
        FILIAL=filiais_sql,
    )
    return sql, filiais_params
