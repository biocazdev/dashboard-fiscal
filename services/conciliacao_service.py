"""Serviço de conciliação Fiscal x Contábil (CT2).

Compara os documentos fiscais (SF1/SF2) com os lançamentos contábeis (CT2)
aplicando a regra em níveis:

    Nível 1 - vínculo exato                         -> CONCILIADO
    Nível 2 - documento localizado com valor diferente -> DIVERGENTE
    Nível 3 - documento fiscal sem lançamento       -> NAO_CONTABILIZADO
    Nível 4 - lançamento sem documento fiscal       -> SEM_ORIGEM_FISCAL

A comparação de valores usa Decimal com tolerância configurável
(``TOLERANCIA_CONCILIACAO``), nunca igualdade de ponto flutuante.

``filial`` é aceito como uma string (uma filial) ou uma lista/tupla de
strings (visão consolidada multi-filial).

Importante: a base está em implantação (CT2 praticamente vazio). A chave de
ligação e o filtro de CT2_DC são configuráveis no .env e devem ser validados
após o GO LIVE (ver DOCUMENTACAO.md).
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from config import settings
from database import conciliacao_queries
from database.connection import DatabaseConnectionError, get_connection
from services.fiscal_service import (
    _as_float,
    _data_sql,
    _ler_sql,
    _normalizar_filiais,
    _parse_data_protheus,
    buscar_clientes,
    buscar_fornecedores,
)

logger = logging.getLogger(__name__)


class StatusConciliacao:
    """Códigos internos dos 4 níveis de conciliação (ver docstring do módulo).

    Usados como valores da coluna STATUS nos DataFrames retornados por este
    módulo - nunca exibidos crus na tela (ver ``rotulo_status`` para o texto
    amigável com ícone).
    """

    CONCILIADO = "CONCILIADO"
    NAO_CONTABILIZADO = "NAO_CONTABILIZADO"
    DIVERGENTE = "DIVERGENTE"
    SEM_ORIGEM_FISCAL = "SEM_ORIGEM_FISCAL"


_STATUS_ROTULO = {
    StatusConciliacao.CONCILIADO: "✅ Conciliado",
    StatusConciliacao.NAO_CONTABILIZADO: "❌ Não contabilizado",
    StatusConciliacao.DIVERGENTE: "⚠️ Divergente",
    StatusConciliacao.SEM_ORIGEM_FISCAL: "🔍 Sem origem fiscal",
}


def rotulo_status(status: str) -> str:
    """Rótulo amigável (com ícone) para o status de conciliação."""
    return _STATUS_ROTULO.get(status, status)


def _tolerancia() -> Decimal:
    """Tolerância de diferença para considerar um documento conciliado."""
    try:
        return Decimal(settings.TOLERANCIA_CONCILIACAO)
    except InvalidOperation:
        return Decimal("0.05")


def _status_conciliacao(row) -> str:
    """Classifica o status de um documento a partir da linha de conciliação."""
    if not row["TEM_LANCAMENTO"]:
        return StatusConciliacao.NAO_CONTABILIZADO

    # Conversão via str() antes de Decimal (nunca Decimal(float) direto):
    # o valor pode chegar como float do driver ODBC, e Decimal(float) herda
    # os erros de arredondamento binário do float; passar por str evita isso.
    fiscal = Decimal(str(row["VALOR_FISCAL"] or 0))
    contabil = Decimal(str(row["VALOR_CONTABIL"] or 0))
    # Nunca comparar valores monetários por igualdade exata: pequenas
    # diferenças de centavos (arredondamento entre o fiscal e o contábil)
    # são normais e não devem virar falso "divergente" - daí a tolerância
    # configurável em vez de "fiscal == contabil".
    if abs(fiscal - contabil) <= _tolerancia():
        return StatusConciliacao.CONCILIADO
    return StatusConciliacao.DIVERGENTE


def _rotular_parceiros(df: pd.DataFrame, filiais: list[str]) -> list[str]:
    """Converte a coluna PARCEIRO em "código - nome" (SA2 fornecedores, SA1 clientes)."""
    fornecedores = dict(buscar_fornecedores(filiais))
    clientes = dict(buscar_clientes(filiais))

    def _rotular(codigo: Any, tipo: str) -> str:
        cod = str(codigo).strip()
        mapa = fornecedores if str(tipo).strip() == "Entrada" else clientes
        nome = mapa.get(cod, "")
        return f"{cod} - {nome}" if nome else cod

    return [
        _rotular(row["PARCEIRO"], str(row["TIPO"]).strip())
        for _, row in df.iterrows()
    ]


def _rotular_parceiro_desconhecido(codigo: Any, filiais: list[str]) -> str:
    """Resolve o nome de um parceiro cujo tipo (cliente/fornecedor) não é
    conhecido de antemão - caso dos lançamentos "sem origem fiscal", onde
    CT2_CODPAR pode ser tanto um cliente quanto um fornecedor.

    Tenta o cadastro de clientes (SA1) e de fornecedores (SA2); usa o
    primeiro nome encontrado. Sem nome em nenhum dos dois, mantém o código.
    """
    cod = str(codigo).strip()
    if not cod:
        return ""
    fornecedores = dict(buscar_fornecedores(filiais))
    clientes = dict(buscar_clientes(filiais))
    nome = clientes.get(cod) or fornecedores.get(cod) or ""
    return f"{cod} - {nome}" if nome else cod


def _rotulos_origem() -> dict[str, str]:
    """Mapa CT2_ORIGEM -> rótulo legível, a partir de ``CT2_ORIGEM_ROTULOS``."""
    mapa: dict[str, str] = {}
    for par in settings.CT2_ORIGEM_ROTULOS.split(","):
        if ":" not in par:
            continue
        codigo, _, rotulo = par.partition(":")
        codigo = codigo.strip()
        rotulo = rotulo.strip()
        if codigo and rotulo:
            mapa[codigo] = rotulo
    return mapa


def rotulo_origem(codigo: Any) -> str:
    """Rótulo legível para um código de CT2_ORIGEM (ex.: "SE1" -> "Contas a Receber").

    Sem rótulo configurado em ``CT2_ORIGEM_ROTULOS``, retorna o código cru.
    """
    cod = str(codigo).strip()
    return _rotulos_origem().get(cod, cod)


def status_configuracao() -> dict[str, Any]:
    """Retorna o estado atual da configuração de conciliação (para exibição).

    Não consulta o banco - só reflete o que está no ``.env`` no momento,
    para o contador/TI conferir sem precisar abrir o arquivo.
    """
    return {
        "chave_documento": (
            "CT2_KEY (posições 7-15 = documento, 16-18 = série)"
            if settings.CT2_DOC_VIA_KEY
            else "CT2_DOC"
        ),
        "ct2_doc_via_key": settings.CT2_DOC_VIA_KEY,
        "ct2_rotina_saida": settings.CT2_ROTINA_SAIDA or "(qualquer rotina)",
        "ct2_rotina_entrada": settings.CT2_ROTINA_ENTRADA or "(qualquer rotina)",
        "exigir_parceiro": settings.CT2_EXIGIR_PARCEIRO,
        "ct2_origem_entrada": settings.CT2_ORIGEM_ENTRADA or "(qualquer origem)",
        "ct2_origem_saida": settings.CT2_ORIGEM_SAIDA or "(qualquer origem)",
        "ct2_filtro_dc": settings.CT2_FILTRO_DC or "(todas as linhas)",
        "tolerancia": str(_tolerancia()),
        "campo_cfop_entrada": settings.CAMPO_CFOP_ENTRADA,
        "campo_cfop_saida": settings.CAMPO_CFOP_SAIDA,
        "status_cancelado_entrada": settings.STATUS_CANCELADO_ENTRADA or "(nenhum - filtro desligado)",
        "status_cancelado_saida": settings.STATUS_CANCELADO_SAIDA or "(nenhum - filtro desligado)",
    }


def conciliar(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
) -> pd.DataFrame:
    """Concilia os documentos fiscais da(s) filial(is)/período com a CT2.

    Quando ``fornecedor`` é informado, apenas as entradas desse fornecedor
    são conciliadas; quando ``cliente`` é informado, apenas as saídas desse
    cliente.

    Returns:
        DataFrame com colunas: TIPO, FILIAL, DOC, SERIE, EMISSAO (date),
        PARCEIRO (código - nome), VALOR_FISCAL, TEM_LANCAMENTO,
        VALOR_CONTABIL, LOTE, DATA_CONTABIL, DIFERENCA, STATUS e
        IDADE_DIAS (dias desde a emissão até hoje).

    Raises:
        DatabaseConnectionError: em caso de falha de conexão.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql_saida, prefixo_saida = conciliacao_queries.sql_conciliacao_saida(filiais, cliente)
    params_saida = prefixo_saida + [data_ini, data_fim]
    if cliente:
        params_saida.append(cliente)
    df_saida = _ler_sql(
        sql_saida,
        params_saida,
        rotulo="conciliacao_saida",
    )

    sql_entrada, prefixo_entrada = conciliacao_queries.sql_conciliacao_entrada(
        filiais, fornecedor
    )
    params_entrada = prefixo_entrada + [data_ini, data_fim]
    if fornecedor:
        params_entrada.append(fornecedor)
    df_entrada = _ler_sql(
        sql_entrada,
        params_entrada,
        rotulo="conciliacao_entrada",
    )

    if df_entrada.empty and df_saida.empty:
        return pd.DataFrame()

    df = pd.concat([df_entrada, df_saida], ignore_index=True)

    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["DATA_CONTABIL"] = df["DATA_CONTABIL"].map(_parse_data_protheus)
    df["VALOR_CONTABIL"] = df["VALOR_CONTABIL"].map(_as_float)
    df["VALOR_FISCAL"] = df["VALOR_FISCAL"].map(_as_float)
    # DIFERENCA aqui é só para exibição/ordenação na tela (soma em resumo()
    # usa a mesma coluna); a classificação em si usa Decimal com tolerância
    # em _status_conciliacao, não esta subtração em float.
    df["DIFERENCA"] = df["VALOR_FISCAL"] - df["VALOR_CONTABIL"]
    # axis=1: classifica linha a linha porque a regra depende de várias
    # colunas da mesma linha (TEM_LANCAMENTO, VALOR_FISCAL, VALOR_CONTABIL).
    df["STATUS"] = df.apply(_status_conciliacao, axis=1)
    df["PARCEIRO"] = _rotular_parceiros(df, filiais)
    # Idade em dias corridos até hoje - usada na tela para priorizar
    # documentos pendentes há mais tempo. None quando EMISSAO não foi
    # reconhecida (data inválida/nula vinda do banco).
    hoje = date.today()
    df["IDADE_DIAS"] = df["EMISSAO"].map(
        lambda d: (hoje - d).days if d else None
    )
    return df


def evolucao_mensal_conciliacao(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
) -> pd.DataFrame:
    """Percentual conciliado por mês (para o comparativo de evolução mensal).

    Reaproveita ``conciliar()`` com o período completo já mais amplo (ver
    ``fiscal_service.buscar_evolucao_mensal``) e agrupa por mês de emissão -
    não precisa de uma consulta SQL nova.

    Returns:
        DataFrame com colunas ANOMES ("AAAAMM"), TOTAL, CONCILIADOS,
        PCT_CONCILIADO. Meses sem documento não aparecem (o chamador decide
        como preencher os buracos ao juntar com a série completa de meses).
    """
    df = conciliar(filial, data_inicial, data_final, fornecedor, cliente)
    if df.empty:
        return pd.DataFrame(columns=["ANOMES", "TOTAL", "CONCILIADOS", "PCT_CONCILIADO"])

    df = df.dropna(subset=["EMISSAO"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["ANOMES", "TOTAL", "CONCILIADOS", "PCT_CONCILIADO"])

    df["ANOMES"] = df["EMISSAO"].map(lambda d: f"{d.year:04d}{d.month:02d}")
    linhas = []
    # Agrupa por mês de emissão e conta quantos documentos do mês já estão
    # CONCILIADOS (nao_contabilizado e divergente contam como "não fechado"
    # para fins deste percentual). Divergente entra no denominador (TOTAL)
    # mas não no numerador (CONCILIADOS) - só bate 100% quando concilia de
    # fato, não basta ter lançamento.
    for anomes, grupo in df.groupby("ANOMES"):
        total = len(grupo)
        conciliados = int((grupo["STATUS"] == StatusConciliacao.CONCILIADO).sum())
        linhas.append(
            {
                "ANOMES": anomes,
                "TOTAL": total,
                "CONCILIADOS": conciliados,
                "PCT_CONCILIADO": (conciliados / total) if total else 0.0,
            }
        )
    return pd.DataFrame(linhas).sort_values("ANOMES").reset_index(drop=True)


def sem_origem_fiscal(
    filial: str | list[str], data_inicial: date, data_final: date
) -> pd.DataFrame:
    """Retorna os lançamentos contábeis sem documento fiscal correspondente.

    Nível 4 da conciliação (visão inversa). Pode revelar lançamento manual,
    integração diferente ou erro de parametrização.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_antes, params_depois = conciliacao_queries.sql_sem_origem_fiscal(filiais)
    df = _ler_sql(
        sql,
        params_antes + [data_ini, data_fim] + params_depois,
        rotulo="conciliacao_sem_origem",
    )

    if df.empty:
        return df

    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["VALOR_CONTABIL"] = df["VALOR_CONTABIL"].map(_as_float)
    # Não existe nota fiscal para este lançamento (é justamente o caso
    # "sem origem fiscal"), então VALOR_FISCAL é sempre zero e a diferença
    # é o próprio valor contábil com sinal invertido (tudo é "sobra").
    df["VALOR_FISCAL"] = 0.0
    df["DIFERENCA"] = -df["VALOR_CONTABIL"]
    df["STATUS"] = StatusConciliacao.SEM_ORIGEM_FISCAL
    df["ORIGEM_ROTULO"] = df["ORIGEM"].map(rotulo_origem) if "ORIGEM" in df.columns else ""
    # Aqui não dá para saber de antemão se CT2_CODPAR é cliente ou
    # fornecedor (não há nota fiscal para indicar o tipo) - por isso usa o
    # resolvedor que tenta os dois cadastros (ver _rotular_parceiro_desconhecido).
    df["PARCEIRO"] = df["PARCEIRO"].fillna("").map(
        lambda cod: _rotular_parceiro_desconhecido(cod, filiais)
    )
    # Alinha o schema com o DataFrame de conciliar() (mesmas colunas) para a
    # tela poder concatenar/exibir os dois resultados de forma uniforme.
    # Campos que não existem para "sem origem fiscal" recebem valores
    # neutros: SERIE/DATA_CONTABIL vazios, TEM_LANCAMENTO=1 (é um
    # lançamento, só que sem nota) e QTDE_LANCAMENTOS=1 (um lançamento cada).
    df["SERIE"] = ""
    df["DATA_CONTABIL"] = ""
    df["TEM_LANCAMENTO"] = 1
    df["QTDE_LANCAMENTOS"] = 1
    hoje = date.today()
    df["IDADE_DIAS"] = df["EMISSAO"].map(
        lambda d: (hoje - d).days if d else None
    )
    return df


def lotes_saldo_diferente_zero(
    filial: str | list[str], data_inicial: date, data_final: date
) -> pd.DataFrame:
    """Lotes contábeis (CT2) cuja soma de CT2_VALOR não fecha em zero.

    Checagem de qualidade dos dados (Grupo D). Ver aviso na query sobre a
    convenção de sinal de CT2_DC ainda não validada nesta instalação.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)
    sql, params_filial = conciliacao_queries.sql_lotes_saldo_diferente_zero(filiais)
    # A mesma tolerância usada para classificar documentos (CONCILIADO x
    # DIVERGENTE) também é aplicada aqui: um lote cuja soma fica dentro da
    # tolerância de arredondamento não é considerado "fora do zero".
    params = params_filial + [data_ini, data_fim, str(_tolerancia())]
    try:
        df = _ler_sql(sql, params, rotulo="lotes_saldo")
    except Exception as exc:
        logger.warning("Não foi possível verificar saldo dos lotes CT2 (%s).", exc)
        return pd.DataFrame()
    if not df.empty:
        df["SALDO"] = df["SALDO"].map(_as_float)
    return df


def tempo_medio_contabilizacao(df: pd.DataFrame) -> float | None:
    """Média de dias entre a emissão da nota e a data de contabilização.

    Considera apenas documentos com lançamento (Conciliado/Divergente).
    Retorna ``None`` quando não há dados suficientes.
    """
    if df is None or df.empty:
        return None
    com_lancamento = df[
        df["STATUS"].isin([StatusConciliacao.CONCILIADO, StatusConciliacao.DIVERGENTE])
    ]
    if com_lancamento.empty:
        return None
    dias = []
    for _, row in com_lancamento.iterrows():
        emissao = row.get("EMISSAO")
        contab = row.get("DATA_CONTABIL")
        # hasattr(contab, "toordinal") filtra os casos em que DATA_CONTABIL
        # não é uma data de verdade - por exemplo "" (string vazia), como
        # sem_origem_fiscal() usa para preencher essa coluna quando não se
        # aplica. Só soma quando emissão e contabilização são datas válidas.
        if emissao and contab and hasattr(contab, "toordinal"):
            dias.append((contab - emissao).days)
    if not dias:
        return None
    return sum(dias) / len(dias)


def resumo(df: pd.DataFrame) -> dict[str, Any]:
    """Agrega os totais da conciliação para os cartões da tela."""
    if df is None or df.empty:
        return {
            "total": 0,
            "conciliados": 0,
            "nao_contabilizados": 0,
            "divergentes": 0,
            "pct_conciliado": 0.0,
            "valor_fiscal": 0.0,
            "valor_contabil": 0.0,
            "diferenca": 0.0,
            "pend_docs": 0,
            "pend_valor": 0.0,
        }

    conciliados = int((df["STATUS"] == StatusConciliacao.CONCILIADO).sum())
    nao_contabilizados = int(
        (df["STATUS"] == StatusConciliacao.NAO_CONTABILIZADO).sum()
    )
    divergentes = int((df["STATUS"] == StatusConciliacao.DIVERGENTE).sum())
    total = len(df)

    # valor_fiscal/valor_contabil/diferenca só somam documentos que têm
    # lançamento contábil (conciliados ou divergentes) - "não contabilizado"
    # não tem VALOR_CONTABIL real (não há lançamento) e entraria como zero
    # de qualquer forma, mas fica explícito no filtro em vez de depender disso.
    com_lancamento = df["STATUS"].isin(
        [StatusConciliacao.CONCILIADO, StatusConciliacao.DIVERGENTE]
    )
    # "Pendência" = ainda precisa de ação do contador: falta lançar
    # (NAO_CONTABILIZADO) ou lançou com valor diferente do fiscal
    # (DIVERGENTE). Documentos "sem origem fiscal" não entram aqui porque
    # este resumo é sobre a base fiscal (SF1/SF2), não sobre a CT2.
    pendencia = df["STATUS"].isin(
        [StatusConciliacao.NAO_CONTABILIZADO, StatusConciliacao.DIVERGENTE]
    )

    return {
        "total": total,
        "conciliados": conciliados,
        "nao_contabilizados": nao_contabilizados,
        "divergentes": divergentes,
        "pct_conciliado": (conciliados / total) if total else 0.0,
        "valor_fiscal": float(df.loc[com_lancamento, "VALOR_FISCAL"].sum()),
        "valor_contabil": float(df.loc[com_lancamento, "VALOR_CONTABIL"].sum()),
        "diferenca": float(df.loc[com_lancamento, "DIFERENCA"].sum()),
        "pend_docs": int(pendencia.sum()),
        "pend_valor": float(df.loc[pendencia, "VALOR_FISCAL"].sum()),
        "tempo_medio_dias": tempo_medio_contabilizacao(df),
    }


def resumo_por_periodo(df: pd.DataFrame) -> pd.DataFrame:
    """Conta os status por data de emissão (para a análise por período).

    Returns:
        DataFrame indexado pela data de emissão com uma coluna por status.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                StatusConciliacao.CONCILIADO,
                StatusConciliacao.NAO_CONTABILIZADO,
                StatusConciliacao.DIVERGENTE,
            ]
        )

    # value_counts().unstack() transforma (EMISSAO, STATUS) em uma tabela
    # dinâmica: uma linha por data, uma coluna por status, com a contagem.
    # fill_value=0 evita NaN nas combinações data/status sem ocorrência.
    pivot = (
        df.groupby("EMISSAO")["STATUS"]
        .value_counts()
        .unstack(fill_value=0)
    )
    # Nem todo status aparece necessariamente no período filtrado (ex.: sem
    # nenhum divergente); garante as 3 colunas sempre presentes para o
    # gráfico de barras empilhadas não quebrar ao acessar uma coluna ausente.
    for col in (
        StatusConciliacao.CONCILIADO,
        StatusConciliacao.NAO_CONTABILIZADO,
        StatusConciliacao.DIVERGENTE,
    ):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot[
        [
            StatusConciliacao.CONCILIADO,
            StatusConciliacao.NAO_CONTABILIZADO,
            StatusConciliacao.DIVERGENTE,
        ]
    ].sort_index()
    return pivot
