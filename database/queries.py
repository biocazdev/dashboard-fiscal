"""Consultas SQL do dashboard fiscal.

Regras desta camada:
- Nenhum SQL é montado no ``app.py``.
- Valores vindos do usuário (filial, datas) são sempre enviados via parâmetros.
- Os nomes das tabelas físicas são configuráveis e validados antes de serem
  interpolados no SQL (vêm de configuração, nunca da interface).
- ``filial`` sempre chega aqui como uma lista de códigos (visão consolidada
  multi-filial). Uma seleção de uma única filial é apenas uma lista de 1
  elemento - o SQL usa ``IN (...)`` em vez de ``= ?`` para os dois casos.
- Convenção geral de parâmetros: quando uma função ``sql_*`` retorna só
  ``(sql, params)``, ``params`` cobre apenas o filtro de filial (a parte
  mais variável) - datas de período e o valor de fornecedor/cliente
  (quando informado) são de responsabilidade do chamador, sempre nesta
  ordem: filial, datas, fornecedor/cliente. Quando a função também trata
  o filtro de status cancelado, ela retorna uma tupla maior e o docstring
  correspondente explicita a ordem completa - esse é o único caso em que
  os parâmetros não seguem só a convenção acima.

Campos confirmados nesta primeira entrega (seção 4 da especificação):
    SF1: F1_FILIAL, F1_EMISSAO, F1_FORNECE, F1_LOJA, F1_VALBRUT,
         F1_VALICM, D_E_L_E_T_
    SF2: F2_FILIAL, F2_EMISSAO, F2_CLIENTE, F2_LOJA, F2_VALBRUT,
         F2_VALICM, D_E_L_E_T_
    SA1/SA2: A1_COD/A2_COD, A1_LOJA/A2_LOJA, A1_NOME/A2_NOME (descrição
    de clientes/fornecedores; filial do cadastro = 4 primeiros dígitos da
    filial da nota). Se o cadastro não existir, fallback para só o código.
    IBS/CBS (reforma tributária): gravados em F2D (tributos calculados),
    vinculados ao item via F2D_IDREL = D1_IDTRIB/D2_IDTRIB. Códigos dos
    tributos configuráveis no .env (COD_TRIB_IBS_ENTRADA/SAIDA, ...).

Grupo B (21/08/2026 - ver DOCUMENTACAO.md):
    CFOP: não existe D1_CFOP/D2_CFOP nesta instalação. Confirmado em
    D1_CF/D2_CF (configurável via CAMPO_CFOP_ENTRADA/SAIDA).
    PIS/COFINS: campos nativos de SD1/SD2 (não passam pelo F2D). COFINS
    truncado para "COF": D1/D2_BASECOF, D1/D2_VALCOF, D1/D2_ALQCOF.
    Notas canceladas: F1_STATUS/F2_STATUS existem, mas o valor que indica
    cancelamento ainda não foi confirmado nesta base (sem exemplo real).
    Filtro opcional via STATUS_CANCELADO_ENTRADA/SAIDA (desligado por
    padrão) - NÃO utilizar D_E_L_E_T_ para identificar cancelamento.

Retenções (25/08/2026 - ver DOCUMENTACAO.md):
    Aba "Retenções" (Reinf R-4020) - lê SE2010 (contas a pagar), não SF1/SF2.
    Valor retido: E2_IRRF/E2_PIS/E2_COFINS/E2_CSLL (NÃO usar
    E2_VRETIRF/E2_VRETPIS/E2_VRETCOF/E2_VRETCSL - ficaram zerados em todos
    os títulos testados). "Cod. R" (natureza de rendimento) não existe em
    nenhuma tabela do banco - mapeamento manual opcional via
    RETENCAO_NATUREZA_CODRET (settings.py).

Validação Retenções x Financeiro (25/08/2026, REDESENHADA no mesmo dia -
ver DOCUMENTACAO.md e settings.py/TABELA_FINANCEIRO):
    Aba "Retenções x Financeiro" - confere se cada tributo retido em um
    título já foi gerado no Financeiro. Confirmado ao vivo pelo cliente:
    o Protheus grava a retenção como um SEGUNDO título na própria SE2010
    (mesmo FILIAL+PREFIXO+NÚMERO do original, E2_TIPO='TX', E2_NATUREZ =
    código do tributo), com baixa própria e independente da baixa do
    título original - não é um movimento em SEF010.

TODO (seção 42 da especificação):
    - SM0 (M0_CODIGO/M0_CODFIL/M0_FANTASIA/M0_NOME): validar no dicionário SX3
      da instalação antes de implantar.
    - D1_TOTAL/D2_TOTAL (valor do item, usado na quebra por CFOP): nome
      padrão TOTVS, não validado explicitamente nesta instalação - conferir
      antes de confiar no valor somado por CFOP.
    - CAMPO_CNPJ_FORNECEDOR (A2_CGC, retenções): nome padrão TOTVS, ainda não
      validado explicitamente nesta instalação (a SA2 não foi consultada
      durante a investigação das retenções) - conferir antes de confiar no
      CNPJ exibido na aba Retenções.
"""

import re

from config import settings

# Nomes de tabela devem conter apenas letras, números e underline.
# Isso evita injeção de SQL mesmo vindo de configuração.
_TABELA_VALIDA = re.compile(r"^[A-Za-z0-9_]+$")


def _tabela(nome: str) -> str:
    """Valida o nome da tabela física antes de interpolar no SQL."""
    if not _TABELA_VALIDA.fullmatch(nome):
        raise ValueError(f"Nome de tabela inválido: {nome!r}")
    return nome


def _campo(nome: str) -> str:
    """Valida o nome de uma coluna configurável antes de interpolar no SQL.

    Usado para campos configuráveis via .env que variam entre instalações
    (ex.: CAMPO_CFOP_ENTRADA/SAIDA) - mesma validação de ``_tabela``.
    """
    if not _TABELA_VALIDA.fullmatch(nome):
        raise ValueError(f"Nome de campo inválido: {nome!r}")
    return nome


def _in_clause(coluna: str, valores: list[str]) -> tuple[str, list[str]]:
    """Monta ``coluna IN (?, ?, ...)`` a partir de uma lista de filiais.

    Usado para permitir a visão consolidada (mais de uma filial ao mesmo
    tempo). ``valores`` nunca deve chegar vazio - quem chama garante isso
    (o app exige ao menos uma filial selecionada).
    """
    placeholders = ", ".join("?" for _ in valores)
    return f"{coluna} IN ({placeholders})", list(valores)


def _filtro_status_excluido(coluna: str, valores_csv: str) -> tuple[str, list[str]]:
    """Monta um filtro opcional ``AND coluna NOT IN (?, ...)``.

    ``valores_csv`` vem de STATUS_CANCELADO_ENTRADA/SAIDA (.env), separados
    por vírgula. Vazio (padrão) = sem filtro, nenhuma mudança de comportamento.
    """
    valores = [v.strip() for v in valores_csv.split(",") if v.strip()]
    if not valores:
        return "", []
    placeholders = ", ".join("?" for _ in valores)
    return f"AND {coluna} NOT IN ({placeholders})", valores


# ---------------------------------------------------------------------------
# Cards de indicadores (seções 7, 8 e 9 da especificação)
# ---------------------------------------------------------------------------
# Estrutura com CTEs + CROSS JOIN para evitar múltiplos subselects.
# Cada CTE aplica D_E_L_E_T_ = '' (exclusão lógica) e os filtros de
# filial e período via parâmetros (?).
SQL_INDICADORES = """
WITH ENTRADAS AS (
    SELECT
        COUNT(*)                             AS QTD_NF_ENTRADA,
        ISNULL(SUM(F1_VALBRUT), 0)           AS VALOR_NF_ENTRADA,
        ISNULL(SUM(F1_VALICM), 0)            AS ICMS_ENTRADA
    FROM {TABELA_NF_ENTRADA}
    WHERE D_E_L_E_T_ = ''
      AND {FILIAL_ENTRADA}
      AND F1_EMISSAO BETWEEN ? AND ?
      {FILTRO_FORNECEDOR}
      {FILTRO_STATUS_E}
      {FILTRO_TIPO_E}
),
SAIDAS AS (
    SELECT
        COUNT(*)                             AS QTD_NF_SAIDA,
        ISNULL(SUM(F2_VALBRUT), 0)           AS VALOR_NF_SAIDA,
        ISNULL(SUM(F2_VALICM), 0)            AS ICMS_SAIDA
    FROM {TABELA_NF_SAIDA}
    WHERE D_E_L_E_T_ = ''
      AND {FILIAL_SAIDA}
      AND F2_EMISSAO BETWEEN ? AND ?
      {FILTRO_CLIENTE}
      {FILTRO_STATUS_S}
      {FILTRO_TIPO_S}
)
-- CROSS JOIN é seguro aqui porque ENTRADAS e SAIDAS são agregações sem
-- GROUP BY - cada CTE sempre retorna exatamente 1 linha, então o produto
-- cartesiano também resulta em 1 linha só, combinando os dois lados.
SELECT *
FROM ENTRADAS
CROSS JOIN SAIDAS;
"""

# ---------------------------------------------------------------------------
# IBS/CBS (reforma tributária) - valores calculados pelo Configurador de
# Tributos e gravados em F2D, vinculados ao item da nota por
# F2D.F2D_IDREL = D1_IDTRIB / D2_IDTRIB.
# Cada linha de F2D traz F2D_TRIB (código do tributo), F2D_BASE, F2D_ALIQ
# e F2D_VALOR. A agregação retorna uma linha por código de tributo.
# ---------------------------------------------------------------------------
SQL_IBS_CBS_SAIDA = """
SELECT
    F2D_TRIB                            AS TRIB,
    ISNULL(SUM(F2D_BASE), 0)            AS BASE,
    ISNULL(SUM(F2D_VALOR), 0)           AS VALOR
FROM {TABELA_F2D}
INNER JOIN {TABELA_ITEM_SAIDA}
    ON F2D_FILIAL = D2_FILIAL
   AND F2D_IDREL  = D2_IDTRIB
   AND F2D_TABELA = 'SD2'
INNER JOIN {TABELA_NF_SAIDA}
    ON D2_FILIAL  = F2_FILIAL
   AND D2_DOC     = F2_DOC
   AND D2_SERIE   = F2_SERIE
   AND D2_EMISSAO = F2_EMISSAO
WHERE {TABELA_F2D}.D_E_L_E_T_ = ''
  AND {TABELA_ITEM_SAIDA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_SAIDA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  -- F2D é compartilhada por vários tributos calculados pelo Configurador;
  -- os dois "?" aqui são sempre o código do IBS e o do CBS de saída
  -- (COD_TRIB_IBS_SAIDA / COD_TRIB_CBS_SAIDA), passados pelo chamador -
  -- sem esse filtro a soma incluiria outros tributos gravados na mesma tabela.
  AND F2D_TRIB IN (?, ?)
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
GROUP BY F2D_TRIB
"""

SQL_IBS_CBS_ENTRADA = """
SELECT
    F2D_TRIB                            AS TRIB,
    ISNULL(SUM(F2D_BASE), 0)            AS BASE,
    ISNULL(SUM(F2D_VALOR), 0)           AS VALOR
FROM {TABELA_F2D}
INNER JOIN {TABELA_ITEM_ENTRADA}
    ON F2D_FILIAL = D1_FILIAL
   AND F2D_IDREL  = D1_IDTRIB
   AND F2D_TABELA = 'SD1'
INNER JOIN {TABELA_NF_ENTRADA}
    ON D1_FILIAL  = F1_FILIAL
   AND D1_DOC     = F1_DOC
   AND D1_SERIE   = F1_SERIE
   AND D1_EMISSAO = F1_EMISSAO
WHERE {TABELA_F2D}.D_E_L_E_T_ = ''
  AND {TABELA_ITEM_ENTRADA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_ENTRADA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  -- Mesma lógica da versão de saída acima: os dois "?" são o código do
  -- IBS e o do CBS de entrada (COD_TRIB_IBS_ENTRADA / COD_TRIB_CBS_ENTRADA).
  AND F2D_TRIB IN (?, ?)
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
GROUP BY F2D_TRIB
"""


def sql_indicadores(
    filiais: list[str],
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """Retorna o SQL dos cards + filiais/status (na ordem: entrada, saída).

    Quando ``fornecedor`` é informado, adiciona o filtro no bloco de
    entradas (SF1) via parâmetro. Quando ``cliente`` é informado, adiciona
    o filtro no bloco de saídas (SF2) via parâmetro.

    ``tipo_nfe``: "Entrada" mantém só entradas; "Saída" mantém só saídas;
    None mantém ambos.

    O filtro de notas canceladas (STATUS_CANCELADO_ENTRADA/SAIDA) só entra
    no SQL quando configurado no .env - vazio (padrão) não muda a consulta.

    Retorna ``(sql, params_filial_e, params_status_e, params_filial_s,
    params_status_s)``. O chamador monta os parâmetros na ordem em que os
    placeholders aparecem no SQL: filial, datas, fornecedor/cliente, status.
    """
    filiais_e, params_filial_e = _in_clause("F1_FILIAL", filiais)
    filiais_s, params_filial_s = _in_clause("F2_FILIAL", filiais)
    filtro_fornecedor = "AND F1_FORNECE = ?" if fornecedor else ""
    filtro_cliente = "AND F2_CLIENTE = ?" if cliente else ""
    filtro_status_e, params_status_e = _filtro_status_excluido(
        "F1_STATUS", settings.STATUS_CANCELADO_ENTRADA
    )
    filtro_status_s, params_status_s = _filtro_status_excluido(
        "F2_STATUS", settings.STATUS_CANCELADO_SAIDA
    )
    # "AND 1=0" zera a CTE do lado não selecionado sem mudar a estrutura do
    # SQL (mesmas colunas, só COUNT/SUM voltando 0) - mantém o CROSS JOIN
    # funcionando igual nos três casos (Entrada/Saída/ambos).
    filtro_tipo_e = "AND 1=0" if tipo_nfe == "Saída" else ""
    filtro_tipo_s = "AND 1=0" if tipo_nfe == "Entrada" else ""
    sql = SQL_INDICADORES.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL_ENTRADA=filiais_e,
        FILIAL_SAIDA=filiais_s,
        FILTRO_FORNECEDOR=filtro_fornecedor,
        FILTRO_CLIENTE=filtro_cliente,
        FILTRO_STATUS_E=filtro_status_e,
        FILTRO_STATUS_S=filtro_status_s,
        FILTRO_TIPO_E=filtro_tipo_e,
        FILTRO_TIPO_S=filtro_tipo_s,
    )
    return sql, params_filial_e, params_status_e, params_filial_s, params_status_s


def sql_ibs_cbs_entrada(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL dos valores IBS/CBS de entrada (via F2D -> SD1 -> SF1) + filiais.

    Quando ``fornecedor`` é informado, adiciona o filtro em SF1.

    Retorna ``(sql, params_filial)``. Os placeholders "?" no SQL aparecem
    na ordem: filial (IN), código do tributo IBS de entrada, código do
    tributo CBS de entrada, datas (BETWEEN) e, por último, fornecedor
    (opcional) - o chamador monta a lista final como ``params_filial +
    [COD_TRIB_IBS_ENTRADA, COD_TRIB_CBS_ENTRADA, data_ini, data_fim] +
    ([fornecedor] se informado)``.
    """
    filiais_sql, params_filial = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_IBS_CBS_ENTRADA.format(
        TABELA_F2D=_tabela(settings.TABELA_F2D),
        TABELA_ITEM_ENTRADA=_tabela(settings.TABELA_ITEM_ENTRADA),
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params_filial


def sql_ibs_cbs_saida(filiais: list[str], cliente: str | None = None) -> tuple[str, list[str]]:
    """SQL dos valores IBS/CBS de saída (via F2D -> SD2 -> SF2) + filiais.

    Quando ``cliente`` é informado, adiciona o filtro em SF2.

    Retorna ``(sql, params_filial)``. Mesma ordem de placeholders de
    ``sql_ibs_cbs_entrada`` (filial, tributo IBS, tributo CBS, datas,
    parceiro): ``params_filial + [COD_TRIB_IBS_SAIDA, COD_TRIB_CBS_SAIDA,
    data_ini, data_fim] + ([cliente] se informado)``.
    """
    filiais_sql, params_filial = _in_clause("F2_FILIAL", filiais)
    filtro_cliente = "AND F2_CLIENTE = ?" if cliente else ""
    sql = SQL_IBS_CBS_SAIDA.format(
        TABELA_F2D=_tabela(settings.TABELA_F2D),
        TABELA_ITEM_SAIDA=_tabela(settings.TABELA_ITEM_SAIDA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro_cliente,
    )
    return sql, params_filial


# ---------------------------------------------------------------------------
# Empresas e filiais (seções 30 e 31 da especificação)
# ---------------------------------------------------------------------------
# SM0 é o cadastro de empresas/filiais do Protheus: M0_CODIGO identifica a
# empresa (grupo) e M0_CODFIL identifica cada filial dentro dela - é
# M0_CODFIL que casa com F1_FILIAL/F2_FILIAL das notas fiscais.
SQL_EMPRESAS = """
SELECT DISTINCT M0_CODIGO AS EMPRESA
FROM {TABELA_EMPRESAS}
WHERE D_E_L_E_T_ = ''
  AND RTRIM(M0_CODIGO) <> ''
ORDER BY M0_CODIGO;
"""

SQL_FILIAIS = """
SELECT M0_CODFIL AS FILIAL,
       ISNULL(
           NULLIF(RTRIM(M0_FANTASIA), ''),
           NULLIF(RTRIM(M0_NOME), '')
       ) AS NOME_FILIAL
FROM {TABELA_EMPRESAS}
WHERE D_E_L_E_T_ = ''
  AND RTRIM(M0_CODFIL) <> ''
ORDER BY M0_CODFIL;
"""

SQL_FILIAIS_POR_EMPRESA = """
SELECT M0_CODFIL AS FILIAL,
       ISNULL(
           NULLIF(RTRIM(M0_FANTASIA), ''),
           NULLIF(RTRIM(M0_NOME), '')
       ) AS NOME_FILIAL
FROM {TABELA_EMPRESAS}
WHERE D_E_L_E_T_ = ''
  AND RTRIM(M0_CODFIL) <> ''
  AND M0_CODIGO = ?
ORDER BY M0_CODFIL;
"""
# Nome de exibição da filial: prioriza o nome fantasia (M0_FANTASIA) e só
# cai para a razão social (M0_NOME) quando o fantasia estiver vazio -
# NULLIF converte string vazia em NULL para o ISNULL conseguir "passar
# para o próximo" candidato.


def sql_empresas() -> str:
    """Retorna o SQL para listar as empresas disponíveis."""
    return SQL_EMPRESAS.format(TABELA_EMPRESAS=_tabela(settings.TABELA_EMPRESAS))


# ---------------------------------------------------------------------------
# Fallback de filiais (quando SM0 não existe ou não é acessível)
# ---------------------------------------------------------------------------
# Deriva as filiais existentes diretamente das notas (SF1/SF2).
SQL_FILIAIS_FALLBACK = """
SELECT DISTINCT T.FILIAL,
       T.FILIAL AS NOME_FILIAL
FROM (
    -- UNION (não UNION ALL) já deduplica as filiais entre entrada e saída
    -- aqui dentro; sem cadastro SM0 não há nome amigável, então o próprio
    -- código da filial é usado como NOME_FILIAL.
    SELECT F1_FILIAL AS FILIAL FROM {TABELA_NF_ENTRADA} WHERE D_E_L_E_T_ = ''
    UNION
    SELECT F2_FILIAL AS FILIAL FROM {TABELA_NF_SAIDA} WHERE D_E_L_E_T_ = ''
) T
WHERE RTRIM(T.FILIAL) <> ''
ORDER BY T.FILIAL
"""

SQL_FILIAIS_FALLBACK_POR_EMPRESA = """
SELECT DISTINCT T.FILIAL,
       T.FILIAL AS NOME_FILIAL
FROM (
    SELECT F1_FILIAL AS FILIAL FROM {TABELA_NF_ENTRADA} WHERE D_E_L_E_T_ = ''
    UNION
    SELECT F2_FILIAL AS FILIAL FROM {TABELA_NF_SAIDA} WHERE D_E_L_E_T_ = ''
) T
WHERE RTRIM(T.FILIAL) <> ''
  AND T.FILIAL LIKE ?
ORDER BY T.FILIAL
"""


def sql_filiais(empresa: str | None = None) -> str:
    """Retorna o SQL para listar filiais (filtradas por empresa se informada)."""
    tabela = _tabela(settings.TABELA_EMPRESAS)
    if empresa:
        return SQL_FILIAIS_POR_EMPRESA.format(TABELA_EMPRESAS=tabela)
    return SQL_FILIAIS.format(TABELA_EMPRESAS=tabela)


def sql_filiais_fallback(empresa: str | None = None) -> str:
    """SQL alternativo que deriva filiais de SF1/SF2 quando SM0 não existe."""
    if empresa:
        return SQL_FILIAIS_FALLBACK_POR_EMPRESA.format(
            TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
            TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        )
    return SQL_FILIAIS_FALLBACK.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
    )


# ---------------------------------------------------------------------------
# Período disponível no banco (datas mínima e máxima de emissão)
# ---------------------------------------------------------------------------
SQL_PERIODO_DISPONIVEL = """
SELECT MIN(D.DATA_EMISSAO) AS DATA_MIN,
       MAX(D.DATA_EMISSAO) AS DATA_MAX
FROM (
    -- UNION ALL (sem dedup) é suficiente e mais barato aqui: o MIN/MAX
    -- externo não se importa com datas repetidas entre entrada e saída.
    SELECT F1_EMISSAO AS DATA_EMISSAO
    FROM {TABELA_NF_ENTRADA}
    WHERE D_E_L_E_T_ = '' AND {FILIAL_ENTRADA}
    UNION ALL
    SELECT F2_EMISSAO AS DATA_EMISSAO
    FROM {TABELA_NF_SAIDA}
    WHERE D_E_L_E_T_ = '' AND {FILIAL_SAIDA}
) D
WHERE RTRIM(D.DATA_EMISSAO) <> ''
"""


def sql_periodo_disponivel(filiais: list[str]) -> tuple[str, list[str]]:
    """Retorna o SQL do período (min/max) de emissão para as filiais + params."""
    filiais_e, params_e = _in_clause("F1_FILIAL", filiais)
    filiais_s, params_s = _in_clause("F2_FILIAL", filiais)
    sql = SQL_PERIODO_DISPONIVEL.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL_ENTRADA=filiais_e,
        FILIAL_SAIDA=filiais_s,
    )
    return sql, params_e + params_s


# ---------------------------------------------------------------------------
# Detalhamento das notas que compõem os indicadores (seção 23)
# ---------------------------------------------------------------------------
# Mesmos filtros de SQL_INDICADORES (filial, período, fornecedor/cliente,
# status cancelado, tipo), mas linha a linha em vez de agregado - é o
# "drill-down" usado quando o usuário clica em um card. Os dois SQLs
# precisam ficar em sincronia: se um filtro mudar aqui, o card e o
# detalhamento podem divergir.
SQL_DETALHAMENTO = """
SELECT
    'Entrada' AS TIPO,
    F1_DOC AS DOC,
    F1_SERIE AS SERIE,
    F1_EMISSAO AS EMISSAO,
    F1_FORNECE AS PARCEIRO,
    F1_LOJA AS LOJA_PARCEIRO,
    F1_VALBRUT AS VALOR,
    F1_VALICM AS ICMS
FROM {TABELA_NF_ENTRADA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL_ENTRADA}
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
  {FILTRO_STATUS_E}
  {FILTRO_TIPO_E}

UNION ALL

SELECT
    'Saida' AS TIPO,
    F2_DOC AS DOC,
    F2_SERIE AS SERIE,
    F2_EMISSAO AS EMISSAO,
    F2_CLIENTE AS PARCEIRO,
    F2_LOJA AS LOJA_PARCEIRO,
    F2_VALBRUT AS VALOR,
    F2_VALICM AS ICMS
FROM {TABELA_NF_SAIDA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL_SAIDA}
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
  {FILTRO_STATUS_S}
  {FILTRO_TIPO_S}

ORDER BY EMISSAO, TIPO, DOC
"""


def sql_detalhamento(
    filiais: list[str],
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """Retorna o SQL do detalhamento das notas + filiais/status.

    Quando ``fornecedor`` é informado, filtra também as entradas (SF1);
    quando ``cliente`` é informado, filtra também as saídas (SF2).

    ``tipo_nfe``: "Entrada" mantém só entradas; "Saída" mantém só saídas;
    None mantém ambos.

    O filtro de notas canceladas só entra no SQL quando configurado no
    .env (STATUS_CANCELADO_ENTRADA/SAIDA) - vazio (padrão) não muda a
    consulta. Retorna ``(sql, params_filial_e, params_status_e,
    params_filial_s, params_status_s)`` - mesma ordem de ``sql_indicadores``.
    """
    filiais_e, params_filial_e = _in_clause("F1_FILIAL", filiais)
    filiais_s, params_filial_s = _in_clause("F2_FILIAL", filiais)
    filtro_fornecedor = "AND F1_FORNECE = ?" if fornecedor else ""
    filtro_cliente = "AND F2_CLIENTE = ?" if cliente else ""
    filtro_status_e, params_status_e = _filtro_status_excluido(
        "F1_STATUS", settings.STATUS_CANCELADO_ENTRADA
    )
    filtro_status_s, params_status_s = _filtro_status_excluido(
        "F2_STATUS", settings.STATUS_CANCELADO_SAIDA
    )
    filtro_tipo_e = "AND 1=0" if tipo_nfe == "Saída" else ""
    filtro_tipo_s = "AND 1=0" if tipo_nfe == "Entrada" else ""
    sql = SQL_DETALHAMENTO.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL_ENTRADA=filiais_e,
        FILIAL_SAIDA=filiais_s,
        FILTRO_FORNECEDOR=filtro_fornecedor,
        FILTRO_CLIENTE=filtro_cliente,
        FILTRO_STATUS_E=filtro_status_e,
        FILTRO_STATUS_S=filtro_status_s,
        FILTRO_TIPO_E=filtro_tipo_e,
        FILTRO_TIPO_S=filtro_tipo_s,
    )
    return sql, params_filial_e, params_status_e, params_filial_s, params_status_s


# ---------------------------------------------------------------------------
# Parceiros: fornecedores (entradas) e clientes (saídas)
# ---------------------------------------------------------------------------
# A descrição vem do cadastro (SA2/SA1). A filial do cadastro corresponde
# aos 4 primeiros dígitos da filial da nota (ex.: '010101' -> '0101').
# Se o cadastro não existir, o serviço faz fallback para apenas os códigos.
SQL_FORNECEDORES = """
SELECT DISTINCT
    SF1.F1_FORNECE AS CODIGO,
    ISNULL(RTRIM(A2.A2_NOME), '') AS NOME
FROM {TABELA_NF_ENTRADA} SF1
LEFT JOIN {TABELA_FORNECEDORES} A2
    ON RTRIM(A2.A2_FILIAL) = LEFT(RTRIM(SF1.F1_FILIAL), 4)
   AND RTRIM(A2.A2_COD) = RTRIM(SF1.F1_FORNECE)
   AND RTRIM(A2.A2_LOJA) = RTRIM(SF1.F1_LOJA)
   AND A2.D_E_L_E_T_ = ''
WHERE SF1.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND RTRIM(SF1.F1_FORNECE) <> ''
ORDER BY SF1.F1_FORNECE
"""

SQL_FORNECEDORES_FALLBACK = """
SELECT DISTINCT F1_FORNECE AS CODIGO,
       '' AS NOME
FROM {TABELA_NF_ENTRADA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND RTRIM(F1_FORNECE) <> ''
ORDER BY F1_FORNECE
"""

SQL_CLIENTES = """
SELECT DISTINCT
    SF2.F2_CLIENTE AS CODIGO,
    ISNULL(RTRIM(A1.A1_NOME), '') AS NOME
FROM {TABELA_NF_SAIDA} SF2
LEFT JOIN {TABELA_CLIENTES} A1
    ON RTRIM(A1.A1_FILIAL) = LEFT(RTRIM(SF2.F2_FILIAL), 4)
   AND RTRIM(A1.A1_COD) = RTRIM(SF2.F2_CLIENTE)
   AND RTRIM(A1.A1_LOJA) = RTRIM(SF2.F2_LOJA)
   AND A1.D_E_L_E_T_ = ''
WHERE SF2.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND RTRIM(SF2.F2_CLIENTE) <> ''
ORDER BY SF2.F2_CLIENTE
"""

SQL_CLIENTES_FALLBACK = """
SELECT DISTINCT F2_CLIENTE AS CODIGO,
       '' AS NOME
FROM {TABELA_NF_SAIDA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND RTRIM(F2_CLIENTE) <> ''
ORDER BY F2_CLIENTE
"""


def sql_fornecedores(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL dos fornecedores presentes nas notas de entrada das filiais + params."""
    filiais_sql, params = _in_clause("SF1.F1_FILIAL", filiais)
    sql = SQL_FORNECEDORES.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        TABELA_FORNECEDORES=_tabela(settings.TABELA_FORNECEDORES),
        FILIAL=filiais_sql,
    )
    return sql, params


def sql_fornecedores_fallback(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL alternativo de fornecedores (apenas códigos) sem o cadastro SA2."""
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    sql = SQL_FORNECEDORES_FALLBACK.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
    )
    return sql, params


def sql_clientes(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL dos clientes presentes nas notas de saída das filiais + params."""
    filiais_sql, params = _in_clause("SF2.F2_FILIAL", filiais)
    sql = SQL_CLIENTES.format(
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        TABELA_CLIENTES=_tabela(settings.TABELA_CLIENTES),
        FILIAL=filiais_sql,
    )
    return sql, params


def sql_clientes_fallback(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL alternativo de clientes (apenas códigos) sem o cadastro SA1."""
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    sql = SQL_CLIENTES_FALLBACK.format(
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
    )
    return sql, params


# ---------------------------------------------------------------------------
# CFOP (Grupo B - "Apuração fiscal")
# ---------------------------------------------------------------------------
# O campo de CFOP é configurável (CAMPO_CFOP_ENTRADA/SAIDA) porque nem toda
# instalação usa o nome padrão D1_CFOP/D2_CFOP - nesta (Biocaz) é D1_CF/D2_CF
# (ver settings.py e DOCUMENTACAO.md). D1_TOTAL/D2_TOTAL (valor do item) é o
# nome padrão TOTVS, ainda não validado explicitamente nesta instalação.
SQL_CFOP_SAIDA = """
SELECT
    {CAMPO_CFOP}                                                    AS CFOP,
    -- O JOIN com o item (SD2) é 1:N por nota - COUNT(*) conta itens, então
    -- QTD_NOTAS precisa de DISTINCT sobre a chave da nota concatenada
    -- (filial+doc+série) para não contar a mesma nota várias vezes.
    COUNT(DISTINCT D2_FILIAL + '|' + D2_DOC + '|' + D2_SERIE)       AS QTD_NOTAS,
    COUNT(*)                                                        AS QTD_ITENS,
    ISNULL(SUM(D2_TOTAL), 0)                                        AS VALOR_TOTAL
FROM {TABELA_ITEM_SAIDA}
INNER JOIN {TABELA_NF_SAIDA}
    ON D2_FILIAL  = F2_FILIAL
   AND D2_DOC     = F2_DOC
   AND D2_SERIE   = F2_SERIE
   AND D2_EMISSAO = F2_EMISSAO
WHERE {TABELA_ITEM_SAIDA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_SAIDA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
GROUP BY {CAMPO_CFOP}
ORDER BY VALOR_TOTAL DESC
"""

SQL_CFOP_ENTRADA = """
SELECT
    {CAMPO_CFOP}                                                    AS CFOP,
    -- Mesmo raciocínio da versão de saída: DISTINCT sobre a chave da nota
    -- concatenada evita contar a nota mais de uma vez por causa do JOIN 1:N
    -- com os itens (SD1).
    COUNT(DISTINCT D1_FILIAL + '|' + D1_DOC + '|' + D1_SERIE)       AS QTD_NOTAS,
    COUNT(*)                                                        AS QTD_ITENS,
    ISNULL(SUM(D1_TOTAL), 0)                                        AS VALOR_TOTAL
FROM {TABELA_ITEM_ENTRADA}
INNER JOIN {TABELA_NF_ENTRADA}
    ON D1_FILIAL  = F1_FILIAL
   AND D1_DOC     = F1_DOC
   AND D1_SERIE   = F1_SERIE
   AND D1_EMISSAO = F1_EMISSAO
WHERE {TABELA_ITEM_ENTRADA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_ENTRADA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
GROUP BY {CAMPO_CFOP}
ORDER BY VALOR_TOTAL DESC
"""


def sql_cfop_saida(filiais: list[str], cliente: str | None = None) -> tuple[str, list[str]]:
    """SQL da quebra de CFOP de saída (via SD2 -> SF2) + filiais."""
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    filtro = "AND F2_CLIENTE = ?" if cliente else ""
    sql = SQL_CFOP_SAIDA.format(
        CAMPO_CFOP=_campo(settings.CAMPO_CFOP_SAIDA),
        TABELA_ITEM_SAIDA=_tabela(settings.TABELA_ITEM_SAIDA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro,
    )
    return sql, params


def sql_cfop_entrada(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL da quebra de CFOP de entrada (via SD1 -> SF1) + filiais."""
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_CFOP_ENTRADA.format(
        CAMPO_CFOP=_campo(settings.CAMPO_CFOP_ENTRADA),
        TABELA_ITEM_ENTRADA=_tabela(settings.TABELA_ITEM_ENTRADA),
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params


# ---------------------------------------------------------------------------
# PIS/COFINS (Grupo B) - campos nativos de SD1/SD2, não passam pelo F2D.
# COFINS truncado para "COF" nesta instalação: D1/D2_BASECOF, D1/D2_VALCOF,
# D1/D2_ALQCOF (confirmado em 21/08/2026, junto com D1/D2_BASEPIS/VALPIS/ALQPIS).
# ---------------------------------------------------------------------------
SQL_PIS_COFINS_SAIDA = """
SELECT
    ISNULL(SUM(D2_BASEPIS), 0)  AS BASE_PIS,
    ISNULL(SUM(D2_VALPIS), 0)   AS VALOR_PIS,
    ISNULL(SUM(D2_BASECOF), 0)  AS BASE_COFINS,
    ISNULL(SUM(D2_VALCOF), 0)   AS VALOR_COFINS
FROM {TABELA_ITEM_SAIDA}
INNER JOIN {TABELA_NF_SAIDA}
    ON D2_FILIAL  = F2_FILIAL
   AND D2_DOC     = F2_DOC
   AND D2_SERIE   = F2_SERIE
   AND D2_EMISSAO = F2_EMISSAO
WHERE {TABELA_ITEM_SAIDA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_SAIDA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
"""

SQL_PIS_COFINS_ENTRADA = """
SELECT
    ISNULL(SUM(D1_BASEPIS), 0)  AS BASE_PIS,
    ISNULL(SUM(D1_VALPIS), 0)   AS VALOR_PIS,
    ISNULL(SUM(D1_BASECOF), 0)  AS BASE_COFINS,
    ISNULL(SUM(D1_VALCOF), 0)   AS VALOR_COFINS
FROM {TABELA_ITEM_ENTRADA}
INNER JOIN {TABELA_NF_ENTRADA}
    ON D1_FILIAL  = F1_FILIAL
   AND D1_DOC     = F1_DOC
   AND D1_SERIE   = F1_SERIE
   AND D1_EMISSAO = F1_EMISSAO
WHERE {TABELA_ITEM_ENTRADA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_ENTRADA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
"""


def sql_pis_cofins_saida(filiais: list[str], cliente: str | None = None) -> tuple[str, list[str]]:
    """SQL de PIS/COFINS de saída (via SD2 -> SF2) + filiais."""
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    filtro = "AND F2_CLIENTE = ?" if cliente else ""
    sql = SQL_PIS_COFINS_SAIDA.format(
        TABELA_ITEM_SAIDA=_tabela(settings.TABELA_ITEM_SAIDA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro,
    )
    return sql, params


def sql_pis_cofins_entrada(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL de PIS/COFINS de entrada (via SD1 -> SF1) + filiais."""
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_PIS_COFINS_ENTRADA.format(
        TABELA_ITEM_ENTRADA=_tabela(settings.TABELA_ITEM_ENTRADA),
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params


# ---------------------------------------------------------------------------
# Diagnóstico de status (Grupo B) - ajuda a identificar o valor real de
# "cancelado" em F1_STATUS/F2_STATUS nesta instalação (ver
# STATUS_CANCELADO_ENTRADA/SAIDA em settings.py).
# ---------------------------------------------------------------------------
SQL_STATUS_ENTRADA = """
SELECT F1_STATUS AS STATUS, COUNT(*) AS QTD
FROM {TABELA_NF_ENTRADA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1_EMISSAO BETWEEN ? AND ?
GROUP BY F1_STATUS
ORDER BY QTD DESC
"""

SQL_STATUS_SAIDA = """
SELECT F2_STATUS AS STATUS, COUNT(*) AS QTD
FROM {TABELA_NF_SAIDA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2_EMISSAO BETWEEN ? AND ?
GROUP BY F2_STATUS
ORDER BY QTD DESC
"""


def sql_status_entrada(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL da distribuição de F1_STATUS no período + filiais."""
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    sql = SQL_STATUS_ENTRADA.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
    )
    return sql, params


def sql_status_saida(filiais: list[str]) -> tuple[str, list[str]]:
    """SQL da distribuição de F2_STATUS no período + filiais."""
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    sql = SQL_STATUS_SAIDA.format(
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
    )
    return sql, params


# ---------------------------------------------------------------------------
# Evolução mensal (comparativo mês a mês / ano a ano)
# ---------------------------------------------------------------------------
# Agrupa por ano+mês da emissão (LEFT(..., 6) sobre o formato YYYYMMDD do
# Protheus) em vez de por dia, para montar a série histórica.
SQL_EVOLUCAO_MENSAL_ENTRADA = """
SELECT
    LEFT(F1_EMISSAO, 6)                  AS ANOMES,
    COUNT(*)                             AS QTD_NF_ENTRADA,
    ISNULL(SUM(F1_VALBRUT), 0)           AS VALOR_NF_ENTRADA,
    ISNULL(SUM(F1_VALICM), 0)            AS ICMS_ENTRADA
FROM {TABELA_NF_ENTRADA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
  {FILTRO_STATUS_E}
GROUP BY LEFT(F1_EMISSAO, 6)
ORDER BY ANOMES
"""

SQL_EVOLUCAO_MENSAL_SAIDA = """
SELECT
    LEFT(F2_EMISSAO, 6)                  AS ANOMES,
    COUNT(*)                             AS QTD_NF_SAIDA,
    ISNULL(SUM(F2_VALBRUT), 0)           AS VALOR_NF_SAIDA,
    ISNULL(SUM(F2_VALICM), 0)            AS ICMS_SAIDA
FROM {TABELA_NF_SAIDA}
WHERE D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
  {FILTRO_STATUS_S}
GROUP BY LEFT(F2_EMISSAO, 6)
ORDER BY ANOMES
"""


def sql_evolucao_mensal_entrada(
    filiais: list[str], fornecedor: str | None = None
) -> tuple[str, list[str], list[str]]:
    """SQL da evolução mensal de entradas + (params_filial, params_status).

    Retorna ``(sql, params_filial, params_status)``. Os placeholders "?" no
    SQL aparecem nesta ordem: filial (IN), datas (BETWEEN), fornecedor
    (opcional) e status excluído (NOT IN, opcional) - o chamador deve montar
    a lista final de parâmetros como ``params_filial + [data_ini, data_fim]
    + ([fornecedor] se informado) + params_status``.
    """
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    filtro_status, params_status = _filtro_status_excluido(
        "F1_STATUS", settings.STATUS_CANCELADO_ENTRADA
    )
    sql = SQL_EVOLUCAO_MENSAL_ENTRADA.format(
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
        FILTRO_STATUS_E=filtro_status,
    )
    return sql, params, params_status


def sql_evolucao_mensal_saida(
    filiais: list[str], cliente: str | None = None
) -> tuple[str, list[str], list[str]]:
    """SQL da evolução mensal de saídas + (params_filial, params_status).

    Mesma ordem de placeholders/parâmetros de ``sql_evolucao_mensal_entrada``,
    trocando fornecedor por cliente: ``params_filial + [data_ini, data_fim]
    + ([cliente] se informado) + params_status``.
    """
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    filtro = "AND F2_CLIENTE = ?" if cliente else ""
    filtro_status, params_status = _filtro_status_excluido(
        "F2_STATUS", settings.STATUS_CANCELADO_SAIDA
    )
    sql = SQL_EVOLUCAO_MENSAL_SAIDA.format(
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro,
        FILTRO_STATUS_S=filtro_status,
    )
    return sql, params, params_status


# ---------------------------------------------------------------------------
# Evolução mensal de IBS/CBS - mesma ideia de LEFT(..., 6) das consultas de
# evolução mensal acima, mas agrupando também por F2D_TRIB (o resultado traz
# uma linha por mês x código de tributo; quem chama separa IBS de CBS pelo
# valor de TRIB).
# ---------------------------------------------------------------------------
SQL_IBS_CBS_MENSAL_SAIDA = """
SELECT
    LEFT(F2_EMISSAO, 6)                 AS ANOMES,
    F2D_TRIB                            AS TRIB,
    ISNULL(SUM(F2D_VALOR), 0)           AS VALOR
FROM {TABELA_F2D}
INNER JOIN {TABELA_ITEM_SAIDA}
    ON F2D_FILIAL = D2_FILIAL
   AND F2D_IDREL  = D2_IDTRIB
   AND F2D_TABELA = 'SD2'
INNER JOIN {TABELA_NF_SAIDA}
    ON D2_FILIAL  = F2_FILIAL
   AND D2_DOC     = F2_DOC
   AND D2_SERIE   = F2_SERIE
   AND D2_EMISSAO = F2_EMISSAO
WHERE {TABELA_F2D}.D_E_L_E_T_ = ''
  AND {TABELA_ITEM_SAIDA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_SAIDA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2D_TRIB IN (?, ?)
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
GROUP BY LEFT(F2_EMISSAO, 6), F2D_TRIB
ORDER BY ANOMES
"""

SQL_IBS_CBS_MENSAL_ENTRADA = """
SELECT
    LEFT(F1_EMISSAO, 6)                 AS ANOMES,
    F2D_TRIB                            AS TRIB,
    ISNULL(SUM(F2D_VALOR), 0)           AS VALOR
FROM {TABELA_F2D}
INNER JOIN {TABELA_ITEM_ENTRADA}
    ON F2D_FILIAL = D1_FILIAL
   AND F2D_IDREL  = D1_IDTRIB
   AND F2D_TABELA = 'SD1'
INNER JOIN {TABELA_NF_ENTRADA}
    ON D1_FILIAL  = F1_FILIAL
   AND D1_DOC     = F1_DOC
   AND D1_SERIE   = F1_SERIE
   AND D1_EMISSAO = F1_EMISSAO
WHERE {TABELA_F2D}.D_E_L_E_T_ = ''
  AND {TABELA_ITEM_ENTRADA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_ENTRADA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2D_TRIB IN (?, ?)
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
GROUP BY LEFT(F1_EMISSAO, 6), F2D_TRIB
ORDER BY ANOMES
"""


def sql_ibs_cbs_mensal_entrada(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL da evolução mensal de IBS/CBS de entrada + filiais.

    Retorna ``(sql, params_filial)`` - mesma ordem de placeholders de
    ``sql_ibs_cbs_entrada``: ``params_filial + [COD_TRIB_IBS_ENTRADA,
    COD_TRIB_CBS_ENTRADA, data_ini, data_fim] + ([fornecedor] se informado)``.
    """
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_IBS_CBS_MENSAL_ENTRADA.format(
        TABELA_F2D=_tabela(settings.TABELA_F2D),
        TABELA_ITEM_ENTRADA=_tabela(settings.TABELA_ITEM_ENTRADA),
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params


def sql_ibs_cbs_mensal_saida(filiais: list[str], cliente: str | None = None) -> tuple[str, list[str]]:
    """SQL da evolução mensal de IBS/CBS de saída + filiais.

    Retorna ``(sql, params_filial)`` - mesma ordem de placeholders de
    ``sql_ibs_cbs_saida``: ``params_filial + [COD_TRIB_IBS_SAIDA,
    COD_TRIB_CBS_SAIDA, data_ini, data_fim] + ([cliente] se informado)``.
    """
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    filtro = "AND F2_CLIENTE = ?" if cliente else ""
    sql = SQL_IBS_CBS_MENSAL_SAIDA.format(
        TABELA_F2D=_tabela(settings.TABELA_F2D),
        TABELA_ITEM_SAIDA=_tabela(settings.TABELA_ITEM_SAIDA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro,
    )
    return sql, params


# ---------------------------------------------------------------------------
# Evolução mensal de PIS/COFINS - campos nativos de SD1/SD2 (mesma ressalva
# de nomenclatura da seção "PIS/COFINS" acima: COFINS truncado para "COF").
# ---------------------------------------------------------------------------
SQL_PIS_COFINS_MENSAL_SAIDA = """
SELECT
    LEFT(F2_EMISSAO, 6)         AS ANOMES,
    ISNULL(SUM(D2_VALPIS), 0)   AS VALOR_PIS,
    ISNULL(SUM(D2_VALCOF), 0)   AS VALOR_COFINS
FROM {TABELA_ITEM_SAIDA}
INNER JOIN {TABELA_NF_SAIDA}
    ON D2_FILIAL  = F2_FILIAL
   AND D2_DOC     = F2_DOC
   AND D2_SERIE   = F2_SERIE
   AND D2_EMISSAO = F2_EMISSAO
WHERE {TABELA_ITEM_SAIDA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_SAIDA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F2_EMISSAO BETWEEN ? AND ?
  {FILTRO_CLIENTE}
GROUP BY LEFT(F2_EMISSAO, 6)
ORDER BY ANOMES
"""

SQL_PIS_COFINS_MENSAL_ENTRADA = """
SELECT
    LEFT(F1_EMISSAO, 6)         AS ANOMES,
    ISNULL(SUM(D1_VALPIS), 0)   AS VALOR_PIS,
    ISNULL(SUM(D1_VALCOF), 0)   AS VALOR_COFINS
FROM {TABELA_ITEM_ENTRADA}
INNER JOIN {TABELA_NF_ENTRADA}
    ON D1_FILIAL  = F1_FILIAL
   AND D1_DOC     = F1_DOC
   AND D1_SERIE   = F1_SERIE
   AND D1_EMISSAO = F1_EMISSAO
WHERE {TABELA_ITEM_ENTRADA}.D_E_L_E_T_ = ''
  AND {TABELA_NF_ENTRADA}.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND F1_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
GROUP BY LEFT(F1_EMISSAO, 6)
ORDER BY ANOMES
"""


def sql_pis_cofins_mensal_entrada(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL da evolução mensal de PIS/COFINS de entrada + filiais."""
    filiais_sql, params = _in_clause("F1_FILIAL", filiais)
    filtro = "AND F1_FORNECE = ?" if fornecedor else ""
    sql = SQL_PIS_COFINS_MENSAL_ENTRADA.format(
        TABELA_ITEM_ENTRADA=_tabela(settings.TABELA_ITEM_ENTRADA),
        TABELA_NF_ENTRADA=_tabela(settings.TABELA_NF_ENTRADA),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params


def sql_pis_cofins_mensal_saida(filiais: list[str], cliente: str | None = None) -> tuple[str, list[str]]:
    """SQL da evolução mensal de PIS/COFINS de saída + filiais."""
    filiais_sql, params = _in_clause("F2_FILIAL", filiais)
    filtro = "AND F2_CLIENTE = ?" if cliente else ""
    sql = SQL_PIS_COFINS_MENSAL_SAIDA.format(
        TABELA_ITEM_SAIDA=_tabela(settings.TABELA_ITEM_SAIDA),
        TABELA_NF_SAIDA=_tabela(settings.TABELA_NF_SAIDA),
        FILIAL=filiais_sql,
        FILTRO_CLIENTE=filtro,
    )
    return sql, params


# ---------------------------------------------------------------------------
# Retenções (IR/PIS/COFINS/CSLL) - Contas a Pagar (SE2)
# ---------------------------------------------------------------------------
# Diferente do resto do dashboard, esta consulta lê os TÍTULOS de contas a
# pagar (SE2), não as notas fiscais - ver settings.py (TABELA_CP) para o
# histórico completo da investigação. A SE2010 não tem campo de loja
# (E2_LOJA não existe nesta instalação), então o vínculo com o cadastro de
# fornecedores (SA2) usa só o código (A2_COD = E2_FORNECE) via OUTER APPLY
# com TOP 1 - evita duplicar a linha do título quando o fornecedor tem mais
# de uma loja cadastrada (o preço é: se houver CNPJs diferentes por loja,
# fica o da primeira loja encontrada).
SQL_RETENCOES = """
SELECT
    SE2.E2_FILIAL                                                AS FILIAL,
    -- Prefixo+número+parcela é a chave "legível" do título no Protheus
    -- (o mesmo título pode ter várias parcelas, cada uma com E2_PARCELA
    -- diferente) - concatenado aqui só para exibição na grade.
    RTRIM(SE2.E2_PREFIXO) + RTRIM(SE2.E2_NUM) + '-' + RTRIM(SE2.E2_PARCELA) AS DOCUMENTO,
    SE2.E2_FORNECE                                               AS FORNECEDOR,
    RTRIM(SE2.E2_NOMFOR)                                         AS NOME_FORNECEDOR,
    SA2.CNPJ                                                     AS CNPJ,
    SE2.E2_NATUREZ                                                AS NATUREZA,
    SE2.E2_EMISSAO                                               AS EMISSAO,
    SE2.E2_VENCTO                                                AS VENCIMENTO,
    SE2.E2_BAIXA                                                 AS BAIXA,
    ISNULL(SE2.E2_BASEIRF, 0)                                    AS BASE_IR,
    ISNULL(SE2.E2_IRRF, 0)                                       AS VALOR_IR,
    ISNULL(SE2.E2_BASEPIS, 0)                                    AS BASE_PIS,
    ISNULL(SE2.E2_PIS, 0)                                        AS VALOR_PIS,
    ISNULL(SE2.E2_BASECOF, 0)                                    AS BASE_COFINS,
    ISNULL(SE2.E2_COFINS, 0)                                     AS VALOR_COFINS,
    ISNULL(SE2.E2_BASECSL, 0)                                    AS BASE_CSLL,
    ISNULL(SE2.E2_CSLL, 0)                                       AS VALOR_CSLL
FROM {TABELA_CP} SE2
OUTER APPLY (
    SELECT TOP 1 RTRIM(A2.{CAMPO_CNPJ}) AS CNPJ
    FROM {TABELA_FORNECEDORES} A2
    WHERE A2.D_E_L_E_T_ = ''
      AND RTRIM(A2.A2_FILIAL) = LEFT(RTRIM(SE2.E2_FILIAL), 4)
      AND RTRIM(A2.A2_COD) = RTRIM(SE2.E2_FORNECE)
) SA2
WHERE SE2.D_E_L_E_T_ = ''
  AND {FILIAL}
  AND SE2.E2_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
  -- A aba "Retenções" só quer títulos que de fato tiveram alguma retenção -
  -- a maioria dos títulos de SE2010 não tem nenhum tributo retido, então
  -- esse filtro evita trazer o contas a pagar inteiro do período.
  AND (
        ISNULL(SE2.E2_IRRF, 0) <> 0
     OR ISNULL(SE2.E2_PIS, 0) <> 0
     OR ISNULL(SE2.E2_COFINS, 0) <> 0
     OR ISNULL(SE2.E2_CSLL, 0) <> 0
  )
ORDER BY SE2.E2_EMISSAO, SE2.E2_FORNECE, DOCUMENTO
"""


def sql_retencoes(filiais: list[str], fornecedor: str | None = None) -> tuple[str, list[str]]:
    """SQL dos títulos de contas a pagar com retenção (IR/PIS/COFINS/CSLL) + filiais.

    Quando ``fornecedor`` é informado, filtra pelo código do fornecedor
    (E2_FORNECE). Só retorna títulos com pelo menos uma retenção diferente
    de zero (IR, PIS, COFINS ou CSLL).
    """
    filiais_sql, params = _in_clause("SE2.E2_FILIAL", filiais)
    filtro = "AND SE2.E2_FORNECE = ?" if fornecedor else ""
    sql = SQL_RETENCOES.format(
        TABELA_CP=_tabela(settings.TABELA_CP),
        TABELA_FORNECEDORES=_tabela(settings.TABELA_FORNECEDORES),
        CAMPO_CNPJ=_campo(settings.CAMPO_CNPJ_FORNECEDOR),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params


# ---------------------------------------------------------------------------
# Validação Retenções x Financeiro (SE2 x SE2, título original x título(s)
# de taxa gerados) - ver settings.py (TABELA_FINANCEIRO) para o racional
# completo da descoberta de 25/08/2026 que motivou este redesenho, e para
# o SEGUNDO padrão (títulos "TG", vinculados só pelo texto do Histórico)
# descoberto no mesmo dia.
# ---------------------------------------------------------------------------
SQL_VALIDACAO_FINANCEIRO_RETENCOES = """
SELECT
    SE2.E2_FILIAL                                                AS FILIAL,
    RTRIM(SE2.E2_PREFIXO) + RTRIM(SE2.E2_NUM) + '-' + RTRIM(SE2.E2_PARCELA) AS DOCUMENTO,
    SE2.E2_FORNECE                                               AS FORNECEDOR,
    RTRIM(SE2.E2_NOMFOR)                                         AS NOME_FORNECEDOR,
    SE2.E2_EMISSAO                                               AS EMISSAO,
    SE2.E2_VENCTO                                                AS VENCIMENTO,
    SE2.E2_BAIXA                                                 AS BAIXA,
    ISNULL(SE2.E2_VALOR, 0)                                      AS VALOR_TITULO,
    -- ISS exposto também em coluna própria (além de entrar no somatório
    -- abaixo) porque foi pedido explicitamente para aparecer separado na
    -- tela, não só diluído no total - ver ressalva sobre E2_ISS logo
    -- abaixo (nome de campo ainda não confirmado ao vivo).
    ISNULL(SE2.E2_ISS, 0)                                        AS VALOR_ISS,
    -- Total retido do título original, somando os tributos - comparado
    -- com VALOR_GERADO_FINANCEIRO abaixo para checar se o que foi retido
    -- na nota bate com o que de fato virou título(s) de taxa na SE2010.
    -- E2_ISS incluído em 26/08/2026 a pedido do cliente (ver settings.py -
    -- TABELA_FINANCEIRO - para a ressalva: nome de campo AINDA NÃO
    -- confirmado ao vivo nesta instalação, diferente dos outros 4 campos).
    ISNULL(SE2.E2_IRRF, 0) + ISNULL(SE2.E2_PIS, 0)
        + ISNULL(SE2.E2_COFINS, 0) + ISNULL(SE2.E2_CSLL, 0)
        + ISNULL(SE2.E2_ISS, 0)                                  AS VALOR_RETIDO,
    ISNULL(TX.QTD_TITULOS_RETENCAO, 0)                           AS QTD_TITULOS_RETENCAO,
    ISNULL(TX.VALOR_GERADO_FINANCEIRO, 0)                        AS VALOR_GERADO_FINANCEIRO,
    ISNULL(TX.QTD_BAIXADOS, 0)                                   AS QTD_BAIXADOS,
    TX.DATA_ULTIMA_BAIXA                                         AS DATA_ULTIMA_BAIXA
FROM {TABELA_CP} SE2
-- OUTER APPLY (em vez de LEFT JOIN) porque a subconsulta agrega (COUNT/SUM)
-- sobre um UNION ALL correlacionado ao título externo (SE2) - precisa ser
-- reavaliada linha a linha. OUTER preserva o título original mesmo quando
-- nenhum título de taxa é encontrado (QTD_TITULOS_RETENCAO fica 0/NULL).
OUTER APPLY (
    SELECT
        -- Quantos títulos de taxa (de qualquer um dos dois padrões) foram
        -- encontrados para este título original - o esperado é 1 por
        -- tributo retido, mas nada impede duplicidade nos dados reais.
        COUNT(*)                                       AS QTD_TITULOS_RETENCAO,
        SUM(ISNULL(T.E2_VALOR, 0))                     AS VALOR_GERADO_FINANCEIRO,
        -- Conta quantos desses títulos de taxa já têm E2_BAIXA preenchido
        -- (ou seja, já foram baixados/pagos) - permite distinguir retenção
        -- gerada mas ainda em aberto de retenção já quitada.
        SUM(
            CASE WHEN T.E2_BAIXA IS NOT NULL AND T.E2_BAIXA <> ''
                 THEN 1 ELSE 0 END
        )                                               AS QTD_BAIXADOS,
        MAX(T.E2_BAIXA)                                  AS DATA_ULTIMA_BAIXA
    FROM (
        -- Padrão A: título "irmão" com o MESMO FILIAL+PREFIXO+NÚMERO do
        -- título original, E2_TIPO='TX' e o tributo em E2_NATUREZ.
        SELECT TX2.E2_VALOR, TX2.E2_BAIXA
        FROM {TABELA_CP} TX2
        WHERE TX2.D_E_L_E_T_ = ''
          AND TX2.E2_TIPO = 'TX'
          AND RTRIM(TX2.E2_FILIAL) = RTRIM(SE2.E2_FILIAL)
          AND RTRIM(TX2.E2_PREFIXO) = RTRIM(SE2.E2_PREFIXO)
          AND RTRIM(TX2.E2_NUM) = RTRIM(SE2.E2_NUM)
          AND RTRIM(TX2.E2_NATUREZ) IN ('IRF', 'PIS', 'COF', 'CSL', 'ISS')

        UNION ALL

        -- Padrão B: título com numeração PRÓPRIA (ex.: "TG0000002"), sem
        -- nenhum campo estruturado ligando de volta ao título original -
        -- o único vínculo encontrado é o texto do Histórico, no formato
        -- "<lote> - NF: <número> / <série>" (ex.: "E00081 - NF: 58 /
        -- NFS"). Aqui o tributo já vem direto em E2_TIPO.
        SELECT TX3.E2_VALOR, TX3.E2_BAIXA
        FROM {TABELA_CP} TX3
        WHERE TX3.D_E_L_E_T_ = ''
          AND TX3.E2_TIPO IN ('IRF', 'PIS', 'COF', 'CSL', 'ISS')
          AND RTRIM(TX3.E2_FILIAL) = RTRIM(SE2.E2_FILIAL)
          -- Os dois CHARINDEX abaixo são guarda: só tenta fazer o parsing
          -- do histórico se ele realmente contiver "NF: " seguido de " / "
          -- depois - evita erro de SUBSTRING com índice negativo em
          -- históricos que não seguem o padrão esperado.
          AND CHARINDEX('NF: ', TX3.E2_HIST) > 0
          AND CHARINDEX(' / ', TX3.E2_HIST, CHARINDEX('NF: ', TX3.E2_HIST)) > 0
          -- Extrai o número da nota: o trecho entre "NF: " e " / ".
          -- RTRIM(LTRIM(...)) remove os espaços que sobram do formato livre
          -- do histórico antes de comparar com E2_NUM.
          AND RTRIM(LTRIM(SUBSTRING(
                TX3.E2_HIST,
                CHARINDEX('NF: ', TX3.E2_HIST) + 4,
                CHARINDEX(' / ', TX3.E2_HIST, CHARINDEX('NF: ', TX3.E2_HIST))
                    - (CHARINDEX('NF: ', TX3.E2_HIST) + 4)
              ))) = RTRIM(SE2.E2_NUM)
          -- Extrai a série da nota: tudo depois de " / " até o fim da
          -- string. Comparado com E2_PREFIXO porque, nesta instalação, o
          -- que aparece depois da barra no histórico é a série da nota
          -- (ex.: "NFS"), que corresponde ao prefixo do título original.
          AND RTRIM(LTRIM(SUBSTRING(
                TX3.E2_HIST,
                CHARINDEX(' / ', TX3.E2_HIST, CHARINDEX('NF: ', TX3.E2_HIST)) + 3,
                LEN(TX3.E2_HIST)
              ))) = RTRIM(SE2.E2_PREFIXO)
    ) T
) TX
WHERE SE2.D_E_L_E_T_ = ''
  -- Exclui os próprios títulos de retenção (Padrão A) da lista de
  -- "originais" - sem isso, um título TX apareceria também como se fosse
  -- um título principal com sua própria retenção.
  AND SE2.E2_TIPO <> 'TX'
  AND {FILIAL}
  AND SE2.E2_EMISSAO BETWEEN ? AND ?
  {FILTRO_FORNECEDOR}
  AND (
        ISNULL(SE2.E2_IRRF, 0) <> 0
     OR ISNULL(SE2.E2_PIS, 0) <> 0
     OR ISNULL(SE2.E2_COFINS, 0) <> 0
     OR ISNULL(SE2.E2_CSLL, 0) <> 0
     OR ISNULL(SE2.E2_ISS, 0) <> 0
  )
ORDER BY SE2.E2_EMISSAO, SE2.E2_FORNECE, DOCUMENTO
"""


def sql_validacao_financeiro_retencoes(
    filiais: list[str], fornecedor: str | None = None
) -> tuple[str, list[str]]:
    """SQL da validação Retenções x Financeiro (título original x título(s) de taxa).

    Para cada título de contas a pagar com retenção (mesmo filtro de
    ``sql_retencoes``), traz o valor do título, o total retido e o que foi
    localizado na própria SE2010 como título(s) de taxa gerados para ele,
    cobrindo os DOIS padrões encontrados nesta instalação (ver
    settings.py - TABELA_FINANCEIRO - para o racional completo):

    - Padrão A: título "irmão" com o MESMO FILIAL+PREFIXO+NÚMERO do
      original, E2_TIPO='TX', tributo em E2_NATUREZ.
    - Padrão B: título com numeração própria (ex.: "TG0000002"),
      E2_TIPO já é o código do tributo, vinculado ao original só pelo
      texto do Histórico ("... NF: <número> / <série>") - não há nenhum
      campo estruturado de vínculo nesta instalação (E2_ORIGEM só grava
      a rotina que gerou o título, ex. "MATA100"; E2_DOCHAB e
      E2_NFELETR vêm em branco).

    Cobre IR/PIS/COFINS/CSLL e, desde 26/08/2026, também ISS Retido
    (E2_NATUREZ/E2_TIPO='ISS', valor em E2_ISS no título original) - a
    pedido do cliente. IMPORTANTE: diferente dos outros 4 tributos, o
    nome de campo E2_ISS/E2_NATUREZ='ISS' segue apenas a convenção padrão
    do dicionário Protheus - AINDA NÃO foi confirmado ao vivo nesta
    instalação (ver settings.py, seção TABELA_FINANCEIRO). Se a coluna
    "Valor Retido" não bater com o ISS reconhecido pelo cliente, o nome
    do campo é o primeiro lugar a conferir.
    """
    filiais_sql, params = _in_clause("SE2.E2_FILIAL", filiais)
    filtro = "AND SE2.E2_FORNECE = ?" if fornecedor else ""
    sql = SQL_VALIDACAO_FINANCEIRO_RETENCOES.format(
        TABELA_CP=_tabela(settings.TABELA_CP),
        FILIAL=filiais_sql,
        FILTRO_FORNECEDOR=filtro,
    )
    return sql, params
