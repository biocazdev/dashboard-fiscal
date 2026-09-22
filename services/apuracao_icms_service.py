"""Serviço de Apuração de ICMS por CFOP.

Aba "🧮 Apuração de ICMS" do dashboard - pedida em 22/09/2026, para
replicar a tela nativa do Protheus (Apuração de ICMS: sub-abas
ICMS-Entradas / ICMS-Saídas / ST-Entradas / ST-Saídas / Apuração-ICMS /
Apuração-ST).

IMPORTANTE - leia isto antes de mexer neste módulo: só as colunas
confirmadas por SQL contra o banco real foram implementadas. Ver
DOCUMENTACAO.md para o histórico completo da investigação (4 rodadas).

Confirmado:
    - Valor Contábil: D1_TOTAL / D2_TOTAL (mesmo campo já usado em
      ``sql_cfop_entrada/saida``).
    - Base de Cálculo: D1_BASEICM / D2_BASEICM.
    - Imposto Creditado (entrada) / Debitado (saída): D1_VALICM / D2_VALICM.

NÃO implementado (pendente):
    - "Isentas" e "Outras" da tela nativa: não existe campo próprio em
      SD1/SD2 para isso, e a hipótese testada (TES -> SF4010.F4_LFICM,
      classificação T/I/O/Não/Zerado do SPED) não se confirmou - o campo
      está em branco para quase todos os TES cadastrados nesta base. Não
      adivinhado para não exibir um valor fiscal errado.
    - ICMS-ST (sub-abas ST-Entradas/ST-Saídas/Apuração-ST): os campos
      candidatos testados (D1/D2_BRICMS, D1_RETENCA, D1_VRETSUB,
      D1/D2_ICMSRET) vieram todos zerados na amostra - não há como
      confirmar se são os campos certos sem uma operação real de ICMS-ST
      nesta base. Mesma situação já vivida com CT-e (tabela existe mas
      sem dado real pra validar contra).
    - "Apuração-ICMS"/"Apuração-ST" (telas de resumo consolidado com saldo
      anterior): a SF4010 encontrada na investigação é o cadastro de TES
      (configuração por tipo de operação), não uma tabela de apuração
      pronta com saldo acumulado - não há fonte identificada para o saldo
      anterior. O resumo aqui é calculado (débito - crédito do período),
      sem saldo anterior.
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
)

logger = logging.getLogger(__name__)

_COLUNAS = ["CFOP", "QTD_NOTAS", "QTD_ITENS", "VALOR_CONTABIL", "BASE_ICMS", "VALOR_ICMS"]


def _buscar(
    sql_func,
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    parceiro: str | None,
    rotulo: str,
) -> pd.DataFrame:
    """Lógica comum às buscas de entrada/saída (evita duplicar o try/except)."""
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame(columns=_COLUNAS)

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial = sql_func(filiais, parceiro)
    params = params_filial + [data_ini, data_fim]
    if parceiro:
        params.append(parceiro)

    try:
        df = _ler_sql(sql, params, rotulo=rotulo)
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar apuração de ICMS (%s): %s", rotulo, exc)
        return pd.DataFrame(columns=_COLUNAS)

    if df.empty:
        return pd.DataFrame(columns=_COLUNAS)

    df = df.copy()
    df["CFOP"] = df["CFOP"].astype(str).str.strip()
    for coluna in ("QTD_NOTAS", "QTD_ITENS"):
        df[coluna] = df[coluna].map(_as_float).astype(int)
    for coluna in ("VALOR_CONTABIL", "BASE_ICMS", "VALOR_ICMS"):
        df[coluna] = df[coluna].map(_as_float)

    return df.sort_values("VALOR_CONTABIL", ascending=False).reset_index(drop=True)


def buscar_apuracao_icms_saida(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    cliente: str | None = None,
) -> pd.DataFrame:
    """Apuração de ICMS de saída por CFOP (aba nativa "ICMS-Saídas").

    Colunas: CFOP, QTD_NOTAS, QTD_ITENS, VALOR_CONTABIL, BASE_ICMS,
    VALOR_ICMS (débito). Em caso de falha, retorna DataFrame vazio
    (degradação graciosa) para não derrubar o dashboard.
    """
    return _buscar(
        queries.sql_apuracao_icms_saida, filial, data_inicial, data_final, cliente,
        rotulo="apuracao_icms_saida",
    )


def buscar_apuracao_icms_entrada(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
) -> pd.DataFrame:
    """Apuração de ICMS de entrada por CFOP (aba nativa "ICMS-Entradas").

    Colunas: CFOP, QTD_NOTAS, QTD_ITENS, VALOR_CONTABIL, BASE_ICMS,
    VALOR_ICMS (crédito). Em caso de falha, retorna DataFrame vazio
    (degradação graciosa) para não derrubar o dashboard.
    """
    return _buscar(
        queries.sql_apuracao_icms_entrada, filial, data_inicial, data_final, fornecedor,
        rotulo="apuracao_icms_entrada",
    )
