"""Serviço de CT-e (Conhecimento de Transporte Eletrônico).

Aba "🚚 CT-e" do dashboard - pedida pelo cliente em 27/08/2026 ("preciso
também de informações de CT-e").

IMPORTANTE - leia isto antes de mexer neste módulo: ao contrário de todas
as outras abas do dashboard, esta foi construída com a tabela de origem
VAZIA (0 linhas) nesta instalação - nada aqui foi validado contra um CT-e
real. O cliente pediu para montar mesmo assim, para a aba já funcionar
quando o Protheus passar a registrar CT-e. Assim que houver o primeiro
CT-e lançado, reconferir cada campo abaixo contra o dado real (o mesmo
processo já feito para Retenções e ISS Retido, ver DOCUMENTACAO.md).

Investigação (27/08/2026, ver settings.py - TABELA_CTE - para o histórico
completo com todas as tabelas descartadas):
    Este Protheus NÃO usa o módulo de Transporte (TMS/GTMS) - as tabelas
    "óbvias" (DT6 = cabeçalho do CT-e, DTC = vínculo com a NF-e) existem só
    no dicionário de dados, nunca foram criadas fisicamente neste banco.
    As tabelas CT0-CTZ (que existem) são todas do módulo Contábil, sem
    nenhuma relação com CT-e - inclusive a "CTE010", que apesar do nome é
    "Amarração Moeda x Calendário" (coincidência de sigla).

    A fonte usada é a C20 (config TABELA_CTE), que pelos nomes dos campos é
    o registro genérico de documento fiscal do gerador de SPED Fiscal do
    Protheus (formato do Registro C100 do leiaute SPED - serve para
    qualquer modelo de documento: NF-e, CT-e, NFS-e etc.). Por isso o CT-e
    é isolado pelo campo C20_TPCTE ("Tipo do CT-e") não vazio, e não por um
    modelo/tabela dedicados.

    Vínculo com a NF-e transportada (pedido explicitamente pelo cliente):
    aposta em C20_CHVREF ("Chave Doc Referenciado Ele") - ainda não
    confirmado se essa chave sempre aponta para a NF-e transportada (pode
    também apontar para outro CT-e, em casos de redespacho/subcontratação).

    Impostos do frete (ICMS/ISS, também pedido pelo cliente): NÃO
    encontrado nenhum campo de ICMS na C20. Os únicos campos parecidos
    encontrados (C20_VLABMT/C20_VLABSU) são de abatimento de ISS e
    provavelmente pertencem a outro tipo de documento na mesma tabela
    (NFS-e) - CT-e é tributado por ICMS, não ISS. Ficam expostos mesmo
    assim (com essa ressalva), mas o ICMS do frete propriamente dito ainda
    não foi localizado em nenhuma tabela desta base.
"""

import logging
from datetime import date

import pandas as pd

from database import queries
from database.connection import DatabaseConnectionError
from services.fiscal_service import (
    _as_float,
    _data_sql,
    _ler_sql,
    _normalizar_filiais,
    _parse_data_protheus,
)

logger = logging.getLogger(__name__)

_COLUNAS_VAZIO = [
    "FILIAL", "SERIE", "NUMERO", "EMISSAO",
    "TRANSPORTADORA", "TRANSPORTADORA_LOJA", "TRANSPORTADORA_NOME", "CNPJ",
    "SITUACAO", "TIPO_CTE", "MODAL",
    "CHAVE_CTE", "CHAVE_NFE_REFERENCIADA", "PROTOCOLO_SEFAZ",
    "DATA_CANCELAMENTO",
    "VALOR_DOCUMENTO", "VALOR_FRETE", "VALOR_SEGURO",
    "VALOR_ABATIMENTO_ISS_MATERIAIS", "VALOR_ABATIMENTO_ISS_SUBEMPREITADA",
]


def buscar_ctes(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
) -> pd.DataFrame:
    """Retorna os CT-e (Conhecimento de Transporte Eletrônico) do período.

    O período filtra pela data de emissão do documento (C20_DTDOC).
    ``fornecedor``, quando informado, filtra pelo código da transportadora
    (C20_CLIFOR - mesmo espaço de código do SA2/A2_COD usado no resto do
    dashboard).

    Colunas: FILIAL, SERIE, NUMERO, EMISSAO, TRANSPORTADORA,
    TRANSPORTADORA_LOJA, TRANSPORTADORA_NOME, CNPJ, SITUACAO, TIPO_CTE,
    MODAL, CHAVE_CTE, CHAVE_NFE_REFERENCIADA, PROTOCOLO_SEFAZ,
    DATA_CANCELAMENTO, VALOR_DOCUMENTO, VALOR_FRETE, VALOR_SEGURO,
    VALOR_ABATIMENTO_ISS_MATERIAIS, VALOR_ABATIMENTO_ISS_SUBEMPREITADA.

    Nesta instalação a tabela de origem está vazia (0 linhas) - um
    DataFrame vazio aqui é o comportamento normal e esperado até que o
    Protheus passe a registrar CT-e, não necessariamente um erro. Em caso
    de falha de consulta, também retorna DataFrame vazio (degradação
    graciosa) para não derrubar o dashboard.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial = queries.sql_ctes(filiais, fornecedor)
    params = params_filial + [data_ini, data_fim]
    if fornecedor:
        params.append(fornecedor)

    try:
        df = _ler_sql(sql, params, rotulo="ctes")
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar CT-e (%s): %s", "C20", exc)
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    if df.empty:
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    df = df.copy()
    for coluna in (
        "VALOR_DOCUMENTO", "VALOR_FRETE", "VALOR_SEGURO",
        "VALOR_ABATIMENTO_ISS_MATERIAIS", "VALOR_ABATIMENTO_ISS_SUBEMPREITADA",
    ):
        df[coluna] = df[coluna].map(_as_float)

    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["DATA_CANCELAMENTO"] = df["DATA_CANCELAMENTO"].map(_parse_data_protheus)

    for coluna in ("TRANSPORTADORA_NOME", "CNPJ", "SITUACAO", "CHAVE_NFE_REFERENCIADA"):
        df[coluna] = df[coluna].fillna("").astype(str).str.strip()
    df["TRANSPORTADORA"] = df["TRANSPORTADORA"].astype(str).str.strip()

    return df.sort_values(["EMISSAO", "TRANSPORTADORA"]).reset_index(drop=True)
