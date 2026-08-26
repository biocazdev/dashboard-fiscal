"""Serviço fiscal: executa consultas, transforma dados e calcula indicadores.

Regras de negócio da primeira entrega (seção 16 da especificação):
- SALDO_ICMS  = ICMS_SAIDA - ICMS_ENTRADA
- TICKET_MEDIO = VALOR_NF_SAIDA / QTD_NF_SAIDA (evitando divisão por zero)
- Datas do Protheus são gravadas como VARCHAR no formato YYYYMMDD.

``filial`` é aceito em todo o módulo como uma string (uma filial) OU uma
lista/tupla de strings (visão consolidada de várias filiais ao mesmo tempo -
ver ``_normalizar_filiais``).
"""

import logging
import time
from datetime import date, datetime
from typing import Any

import pandas as pd

from config import settings
from database import queries
from database.connection import (
    DatabaseConnectionError,
    adaptar_placeholders,
    get_connection,
)

logger = logging.getLogger(__name__)


class FiscalServiceError(Exception):
    """Erro genérico do serviço fiscal (mensagem amigável para a interface)."""


def _normalizar_filiais(filial: str | list[str] | tuple[str, ...]) -> list[str]:
    """Normaliza ``filial`` (string única ou lista/tupla) em uma lista.

    Aceita string única (uso tradicional, uma filial) ou uma coleção
    (visão consolidada multi-filial). Remove vazios e duplicatas mantendo
    a ordem.
    """
    if isinstance(filial, (list, tuple, set)):
        brutos = list(filial)
    else:
        brutos = [filial]
    vistos: list[str] = []
    for item in brutos:
        codigo = str(item).strip()
        if codigo and codigo not in vistos:
            vistos.append(codigo)
    return vistos


def _data_sql(data: date) -> str:
    """Converte uma data Python para o formato YYYYMMDD do Protheus."""
    return data.strftime("%Y%m%d")


def _parse_data_protheus(valor: Any) -> date | None:
    """Converte uma data lida do Protheus (YYYYMMDD) em objeto ``date``.

    Aceita também valores já em formato datetime/varchar ISO.
    """
    if valor is None or pd.isna(valor):
        return None
    texto = str(valor).strip()
    for formato in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _ler_sql(sql: str, params: list[Any], rotulo: str = "") -> pd.DataFrame:
    """Executa um SELECT, mede o tempo e garante o fechamento da conexão.

    A conexão é aberta apenas dentro desta função (nunca em cache).
    """
    inicio = time.perf_counter()
    connection = get_connection()
    try:
        # Todo o SQL deste projeto é escrito com placeholders "?" (estilo
        # pyodbc) - adaptar_placeholders() converte para "%s" quando o
        # driver ativo é o pymssql, que não entende "?" (ver
        # database/connection.py para o motivo completo).
        return pd.read_sql(adaptar_placeholders(sql), connection, params=params)
    finally:
        connection.close()
        duracao = time.perf_counter() - inicio
        logger.info(
            "Consulta [%s] executada em %.2fs | params=%s",
            rotulo or sql.strip().splitlines()[0][:60],
            duracao,
            params,
        )


def _as_float(valor: Any) -> float:
    """Converte um valor do banco para float com segurança."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _buscar_ibs_cbs(
    filiais: list[str],
    data_ini: str,
    data_fim: str,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> dict[str, float]:
    """Retorna IBS/CBS de entrada e saída gravados na tabela F2D.

    O Configurador de Tributos grava cada cálculo em F2D com um código de
    tributo (F2D_TRIB) e vincula ao item da nota via F2D_IDREL =
    D1_IDTRIB/D2_IDTRIB. Os valores são somados por código e mapeados para
    os cartões conforme o ``.env`` (COD_TRIB_IBS_* / COD_TRIB_CBS_*).

    Quando ``fornecedor`` é informado, as entradas (IBS/CBS de entrada)
    são filtradas pelo fornecedor. Quando ``cliente`` é informado, as
    saídas (IBS/CBS de saída) são filtradas pelo cliente.

    ``tipo_nfe``: "Entrada" consulta só entrada; "Saída" consulta só saída;
    None consulta ambos.

    Em caso de falha nesta consulta, retorna R$ 0,00 (degradação graciosa)
    para não derrubar o dashboard.
    """
    resultado = {
        "IBS_ENTRADA": 0.0,
        "CBS_ENTRADA": 0.0,
        "IBS_SAIDA": 0.0,
        "CBS_SAIDA": 0.0,
    }

    def _somar(sql: str, params: list[str], rotulo: str) -> dict[str, float]:
        # F2D é gravada por código de tributo (TRIB), já agregada por essa
        # coluna na query; aqui só transformamos as linhas (TRIB, VALOR) em
        # um dicionário para permitir buscar cada tributo pelo código
        # configurado no .env (COD_TRIB_IBS_*/COD_TRIB_CBS_*) logo abaixo.
        df = _ler_sql(sql, params, rotulo=rotulo)
        if df.empty:
            return {}
        return {
            str(row["TRIB"]).strip(): _as_float(row["VALOR"])
            for _, row in df.iterrows()
        }

    try:
        if tipo_nfe != "Saída":
            sql_e, params_filial_e = queries.sql_ibs_cbs_entrada(filiais, fornecedor)
            params_entrada = (
                params_filial_e
                + [settings.COD_TRIB_IBS_ENTRADA, settings.COD_TRIB_CBS_ENTRADA, data_ini, data_fim]
            )
            if fornecedor:
                params_entrada.append(fornecedor)
            entrada = _somar(sql_e, params_entrada, rotulo="ibs_cbs_entrada")
        else:
            entrada = {}
        if tipo_nfe != "Entrada":
            sql_s, params_filial_s = queries.sql_ibs_cbs_saida(filiais, cliente)
            params_saida = (
                params_filial_s
                + [settings.COD_TRIB_IBS_SAIDA, settings.COD_TRIB_CBS_SAIDA, data_ini, data_fim]
            )
            if cliente:
                params_saida.append(cliente)
            saida = _somar(sql_s, params_saida, rotulo="ibs_cbs_saida")
        else:
            saida = {}
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar IBS/CBS via F2D: %s", exc)
        return resultado

    resultado["IBS_ENTRADA"] = entrada.get(settings.COD_TRIB_IBS_ENTRADA, 0.0)
    resultado["CBS_ENTRADA"] = entrada.get(settings.COD_TRIB_CBS_ENTRADA, 0.0)
    resultado["IBS_SAIDA"] = saida.get(settings.COD_TRIB_IBS_SAIDA, 0.0)
    resultado["CBS_SAIDA"] = saida.get(settings.COD_TRIB_CBS_SAIDA, 0.0)
    return resultado


def _buscar_pis_cofins(
    filiais: list[str],
    data_ini: str,
    data_fim: str,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> dict[str, float]:
    """Retorna PIS/COFINS de entrada e saída (campos nativos de SD1/SD2).

    Diferente de IBS/CBS, PIS e COFINS não passam pelo F2D nesta instalação -
    são somados direto de SD1/SD2 (D1/D2_BASEPIS, VALPIS, BASECOF, VALCOF).

    Em caso de falha, retorna zeros (degradação graciosa).
    """
    resultado = {
        "BASE_PIS_ENTRADA": 0.0,
        "VALOR_PIS_ENTRADA": 0.0,
        "BASE_COFINS_ENTRADA": 0.0,
        "VALOR_COFINS_ENTRADA": 0.0,
        "BASE_PIS_SAIDA": 0.0,
        "VALOR_PIS_SAIDA": 0.0,
        "BASE_COFINS_SAIDA": 0.0,
        "VALOR_COFINS_SAIDA": 0.0,
    }
    try:
        if tipo_nfe != "Saída":
            sql_e, params_filial_e = queries.sql_pis_cofins_entrada(filiais, fornecedor)
            params_e = params_filial_e + [data_ini, data_fim]
            if fornecedor:
                params_e.append(fornecedor)
            df_e = _ler_sql(sql_e, params_e, rotulo="pis_cofins_entrada")
            if not df_e.empty:
                linha = df_e.iloc[0]
                resultado["BASE_PIS_ENTRADA"] = _as_float(linha["BASE_PIS"])
                resultado["VALOR_PIS_ENTRADA"] = _as_float(linha["VALOR_PIS"])
                resultado["BASE_COFINS_ENTRADA"] = _as_float(linha["BASE_COFINS"])
                resultado["VALOR_COFINS_ENTRADA"] = _as_float(linha["VALOR_COFINS"])
        if tipo_nfe != "Entrada":
            sql_s, params_filial_s = queries.sql_pis_cofins_saida(filiais, cliente)
            params_s = params_filial_s + [data_ini, data_fim]
            if cliente:
                params_s.append(cliente)
            df_s = _ler_sql(sql_s, params_s, rotulo="pis_cofins_saida")
            if not df_s.empty:
                linha = df_s.iloc[0]
                resultado["BASE_PIS_SAIDA"] = _as_float(linha["BASE_PIS"])
                resultado["VALOR_PIS_SAIDA"] = _as_float(linha["VALOR_PIS"])
                resultado["BASE_COFINS_SAIDA"] = _as_float(linha["BASE_COFINS"])
                resultado["VALOR_COFINS_SAIDA"] = _as_float(linha["VALOR_COFINS"])
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar PIS/COFINS: %s", exc)
        return resultado
    return resultado


def buscar_indicadores(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> dict[str, Any]:
    """Retorna todos os indicadores dos cards para a(s) filial(is) e período.

    Args:
        filial: código da filial (ex.: "010101") ou lista de códigos para
            a visão consolidada multi-filial.
        data_inicial: início do período (data de emissão).
        data_final: fim do período (data de emissão).
        fornecedor: código do fornecedor para filtrar as entradas (opcional).
        cliente: código do cliente para filtrar as saídas (opcional).
        tipo_nfe: "Entrada" ou "Saída" para filtrar; None = ambos.

    Returns:
        Dicionário com QTD_NF_ENTRADA, VALOR_NF_ENTRADA, ICMS_ENTRADA,
        IBS_ENTRADA, CBS_ENTRADA, QTD_NF_SAIDA, VALOR_NF_SAIDA, ICMS_SAIDA,
        IBS_SAIDA, CBS_SAIDA, SALDO_ICMS e TICKET_MEDIO.

    Raises:
        FiscalServiceError: em caso de erro de conexão ou de consulta.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        raise FiscalServiceError("Filial não informada.")

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial_e, params_status_e, params_filial_s, params_status_s = (
        queries.sql_indicadores(filiais, fornecedor, cliente, tipo_nfe)
    )
    # A ordem de montagem dos params abaixo precisa acompanhar exatamente a
    # ordem dos placeholders "?" no SQL retornado por queries.sql_indicadores:
    # primeiro os códigos de filial (IN), depois o período, depois o
    # fornecedor/cliente (só quando informado) e por fim os status de
    # cancelamento a excluir. Qualquer mudança de ordem aqui sem espelhar a
    # query quebra a consulta silenciosamente (params trocados de posição).
    params_entrada = params_filial_e + [data_ini, data_fim]
    if fornecedor:
        params_entrada.append(fornecedor)
    params_entrada += params_status_e
    params_saida = params_filial_s + [data_ini, data_fim]
    if cliente:
        params_saida.append(cliente)
    params_saida += params_status_s
    params = params_entrada + params_saida

    try:
        df = _ler_sql(sql, params, rotulo="indicadores")
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.exception(
            "Erro ao consultar indicadores (filiais=%s, periodo=%s a %s).",
            filiais,
            data_ini,
            data_fim,
        )
        raise FiscalServiceError(
            "Erro ao consultar os indicadores fiscais."
        ) from exc

    # Consultas agregadas (sem GROUP BY) sempre retornam uma linha.
    linha = df.iloc[0]

    valor_saida = _as_float(linha["VALOR_NF_SAIDA"])
    qtd_saida = _as_float(linha["QTD_NF_SAIDA"])
    icms_entrada = _as_float(linha["ICMS_ENTRADA"])
    icms_saida = _as_float(linha["ICMS_SAIDA"])

    # Regras de negócio da especificação (ver docstring do módulo):
    # saldo positivo = ICMS a recolher; negativo = crédito acumulado.
    saldo_icms = icms_saida - icms_entrada
    # Protege contra divisão por zero quando não há notas de saída no
    # período/filtro (ex.: filial só com entradas no intervalo escolhido).
    ticket_medio = valor_saida / qtd_saida if qtd_saida > 0 else 0.0

    ibs_cbs = _buscar_ibs_cbs(
        filiais, data_ini, data_fim, fornecedor, cliente, tipo_nfe
    )
    pis_cofins = _buscar_pis_cofins(
        filiais, data_ini, data_fim, fornecedor, cliente, tipo_nfe
    )

    return {
        "QTD_NF_ENTRADA": int(linha["QTD_NF_ENTRADA"]),
        "VALOR_NF_ENTRADA": _as_float(linha["VALOR_NF_ENTRADA"]),
        "ICMS_ENTRADA": icms_entrada,
        "IBS_ENTRADA": ibs_cbs["IBS_ENTRADA"],
        "CBS_ENTRADA": ibs_cbs["CBS_ENTRADA"],
        "PIS_ENTRADA": pis_cofins["VALOR_PIS_ENTRADA"],
        "COFINS_ENTRADA": pis_cofins["VALOR_COFINS_ENTRADA"],
        "QTD_NF_SAIDA": int(linha["QTD_NF_SAIDA"]),
        "VALOR_NF_SAIDA": valor_saida,
        "ICMS_SAIDA": icms_saida,
        "IBS_SAIDA": ibs_cbs["IBS_SAIDA"],
        "CBS_SAIDA": ibs_cbs["CBS_SAIDA"],
        "PIS_SAIDA": pis_cofins["VALOR_PIS_SAIDA"],
        "COFINS_SAIDA": pis_cofins["VALOR_COFINS_SAIDA"],
        "SALDO_ICMS": saldo_icms,
        "TICKET_MEDIO": ticket_medio,
    }


def _montar_lista_filiais(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Converte o DataFrame de filiais em pares (código, nome)."""
    filiais: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        codigo = str(row["FILIAL"]).strip()
        nome = row["NOME_FILIAL"]
        nome = str(nome).strip() if pd.notna(nome) else ""
        if codigo:
            filiais.append((codigo, nome))
    return filiais


def buscar_empresas() -> list[str]:
    """Retorna a lista de empresas disponíveis.

    Primeiro tenta a coluna M0_CODIGO da tabela SM0 configurada.
    Se o SM0 não existir/estiver acessível, deriva as empresas das
    filiais encontradas em SF1/SF2 (2 primeiros dígitos do código).
    """
    try:
        df = _ler_sql(queries.sql_empresas(), [], rotulo="empresas")
        empresas = [str(valor).strip() for valor in df["EMPRESA"]] if not df.empty else []
        if empresas:
            return empresas
    except Exception as exc:
        logger.warning("SM0 indisponível para empresas (%s).", exc)

    filiais = buscar_filiais()
    empresas = sorted({codigo[:2] for codigo, _ in filiais if len(codigo) >= 2})
    return empresas


def buscar_filiais(empresa: str | None = None) -> list[tuple[str, str]]:
    """Retorna as filiais disponíveis como pares (código, nome).

    Se ``empresa`` for informada, filtra as filiais daquela empresa.

    Primeiro tenta a tabela SM0 configurada; se ela não existir ou não
    estiver acessível, utiliza como fallback as filiais de SF1/SF2.
    """
    params = [empresa] if empresa else []
    try:
        df = _ler_sql(
            queries.sql_filiais(empresa),
            params,
            rotulo="filiais_sm0",
        )
        if not df.empty:
            return _montar_lista_filiais(df)
    except Exception as exc:
        logger.warning("SM0 indisponível para filiais (%s). Usando SF1/SF2.", exc)

    params_fallback = [f"{empresa}%"] if empresa else []
    df = _ler_sql(
        queries.sql_filiais_fallback(empresa),
        params_fallback,
        rotulo="filiais_sf",
    )
    return _montar_lista_filiais(df)


def buscar_periodo_disponivel(
    filial: str | list[str],
) -> tuple[date | None, date | None]:
    """Retorna o período (mínimo/máximo) de emissão disponível no banco.

    Considera as notas de entrada e saída da(s) filial(is), ignorando
    registros deletados logicamente. Retorna ``(None, None)`` quando não
    há dados.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return None, None

    sql, params = queries.sql_periodo_disponivel(filiais)
    try:
        df = _ler_sql(sql, params, rotulo="periodo_disponivel")
    except Exception as exc:
        logger.warning("Não foi possível carregar o período disponível (%s).", exc)
        return None, None

    if df.empty:
        return None, None

    linha = df.iloc[0]
    return _parse_data_protheus(linha["DATA_MIN"]), _parse_data_protheus(
        linha["DATA_MAX"]
    )


def _buscar_parceiros(
    filiais: list[str], sql_principal, sql_fallback, rotulo: str
) -> list[tuple[str, str]]:
    """Retorna os parceiros das filiais como pares (código, nome).

    Tenta primeiro o cadastro (SA2/SA1) com o nome; se ele não existir ou
    não estiver acessível, deriva apenas os códigos das notas (fallback).
    ``sql_principal``/``sql_fallback`` são funções que recebem ``filiais``
    e retornam ``(sql, params)``.
    """
    sql, params = sql_principal(filiais)
    try:
        df = _ler_sql(sql, params, rotulo=rotulo)
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Cadastro de parceiros indisponível (%s). Usando fallback.", exc)
        sql_fb, params_fb = sql_fallback(filiais)
        df = _ler_sql(sql_fb, params_fb, rotulo=f"{rotulo}_fallback")

    parceiros: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        codigo = str(row["CODIGO"]).strip()
        nome = row["NOME"]
        nome = str(nome).strip() if pd.notna(nome) else ""
        if codigo:
            parceiros.append((codigo, nome))
    return parceiros


def buscar_fornecedores(filial: str | list[str]) -> list[tuple[str, str]]:
    """Retorna os fornecedores (código, nome) com notas na(s) filial(is)."""
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return []
    return _buscar_parceiros(
        filiais,
        queries.sql_fornecedores,
        queries.sql_fornecedores_fallback,
        "fornecedores",
    )


def buscar_clientes(filial: str | list[str]) -> list[tuple[str, str]]:
    """Retorna os clientes (código, nome) com notas na(s) filial(is)."""
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return []
    return _buscar_parceiros(
        filiais,
        queries.sql_clientes,
        queries.sql_clientes_fallback,
        "clientes",
    )


def buscar_detalhamento(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> pd.DataFrame:
    """Retorna as notas (entradas e saídas) que compõem os indicadores.

    A coluna EMISSAO é convertida para ``date`` (formato Protheus YYYYMMDD)
    para exibição em DD/MM/AAAA na interface. A coluna PARCEIRO é enriquecida
    com a descrição do cadastro no formato "código - nome" (fornecedores nas
    entradas, clientes nas saídas).

    Quando ``fornecedor`` é informado, filtra as entradas; quando ``cliente``
    é informado, filtra as saídas.

    ``tipo_nfe``: "Entrada" mantém só entradas; "Saída" mantém só saídas;
    None mantém ambos.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial_e, params_status_e, params_filial_s, params_status_s = (
        queries.sql_detalhamento(filiais, fornecedor, cliente, tipo_nfe)
    )
    # Mesma ordem de params exigida por buscar_indicadores acima: filial,
    # período, parceiro (se houver) e status de cancelamento por último -
    # tem que casar com os placeholders do SQL de queries.sql_detalhamento.
    params_entrada = params_filial_e + [data_ini, data_fim]
    if fornecedor:
        params_entrada.append(fornecedor)
    params_entrada += params_status_e
    params_saida = params_filial_s + [data_ini, data_fim]
    if cliente:
        params_saida.append(cliente)
    params_saida += params_status_s
    params = params_entrada + params_saida

    df = _ler_sql(sql, params, rotulo="detalhamento")

    if df.empty:
        return df

    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["PARCEIRO"] = _rotular_parceiros(df, filiais)
    return df


def _rotular_parceiros(df: pd.DataFrame, filial: str | list[str]) -> list[str]:
    """Transforma PARCEIRO em "código - nome" usando o cadastro (SA2/SA1).

    Fornecedores (entradas) vêm de SA2 e clientes (saídas) de SA1.
    Sem descrição no cadastro, mantém apenas o código.
    """
    fornecedores = dict(buscar_fornecedores(filial))
    clientes = dict(buscar_clientes(filial))

    def _rotular(codigo: Any, tipo: str) -> str:
        cod = str(codigo).strip()
        mapa = fornecedores if tipo == "Entrada" else clientes
        nome = mapa.get(cod, "")
        if nome:
            return f"{cod} - {nome}"
        return cod

    return [
        _rotular(row["PARCEIRO"], str(row["TIPO"]).strip())
        for _, row in df.iterrows()
    ]


def buscar_cfop(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> pd.DataFrame:
    """Retorna a quebra por CFOP (entrada e saída) no período/filial(is).

    Colunas: TIPO, CFOP, QTD_NOTAS, QTD_ITENS, VALOR_TOTAL. Usa os campos
    configuráveis CAMPO_CFOP_ENTRADA/SAIDA (nesta instalação: D1_CF/D2_CF -
    ver settings.py). Em caso de falha, retorna DataFrame vazio (degradação
    graciosa) para não derrubar o dashboard.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    partes: list[pd.DataFrame] = []
    try:
        if tipo_nfe != "Saída":
            sql_e, params_filial_e = queries.sql_cfop_entrada(filiais, fornecedor)
            params_e = params_filial_e + [data_ini, data_fim]
            if fornecedor:
                params_e.append(fornecedor)
            df_e = _ler_sql(sql_e, params_e, rotulo="cfop_entrada")
            if not df_e.empty:
                df_e = df_e.copy()
                df_e.insert(0, "TIPO", "Entrada")
                partes.append(df_e)
        if tipo_nfe != "Entrada":
            sql_s, params_filial_s = queries.sql_cfop_saida(filiais, cliente)
            params_s = params_filial_s + [data_ini, data_fim]
            if cliente:
                params_s.append(cliente)
            df_s = _ler_sql(sql_s, params_s, rotulo="cfop_saida")
            if not df_s.empty:
                df_s = df_s.copy()
                df_s.insert(0, "TIPO", "Saída")
                partes.append(df_s)
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar CFOP: %s", exc)
        return pd.DataFrame()

    if not partes:
        return pd.DataFrame()

    df = pd.concat(partes, ignore_index=True)
    # As consultas de entrada e saída retornam CFOP/quantidades com tipos do
    # driver ODBC que podem variar (Decimal, str, None) entre SF1 e SF2;
    # normalizamos para tipos Python previsíveis antes de exibir na tela.
    # QTD_* passa por float antes de int porque o driver pode devolver
    # Decimal, que int() não converte diretamente em todas as versões.
    df["CFOP"] = df["CFOP"].astype(str).str.strip()
    for coluna in ("QTD_NOTAS", "QTD_ITENS"):
        df[coluna] = df[coluna].map(_as_float).astype(int)
    df["VALOR_TOTAL"] = df["VALOR_TOTAL"].map(_as_float)
    # Maiores valores primeiro: é o que interessa ao contador ao revisar CFOP.
    return df.sort_values("VALOR_TOTAL", ascending=False).reset_index(drop=True)


def _mes_anterior(ano: int, mes: int, n: int) -> tuple[int, int]:
    """Retorna ``(ano, mes)`` deslocado ``n`` meses para trás (n pode ser 0)."""
    # Trata (ano, mes) como um índice contínuo de meses (base 0 = janeiro do
    # ano 0) para poder subtrair "n" meses com aritmética inteira simples,
    # sem precisar tratar virada de ano/mês manualmente com ifs.
    total = ano * 12 + (mes - 1) - n
    return total // 12, total % 12 + 1


def janela_evolucao_mensal(data_final: date, meses: int) -> tuple[date, date]:
    """Retorna ``(data_inicial, data_final)`` da janela de ``meses`` meses.

    Mesma janela usada por ``buscar_evolucao_mensal`` - use este helper para
    consultar outras séries mensais (ex.:
    ``conciliacao_service.evolucao_mensal_conciliacao``) no mesmo intervalo.
    """
    ano_ini, mes_ini = _mes_anterior(data_final.year, data_final.month, max(meses, 1) - 1)
    return date(ano_ini, mes_ini, 1), data_final


def _serie_por_anomes(df: pd.DataFrame, coluna_valor: str) -> dict[str, float]:
    """Converte um DataFrame com coluna ANOMES em ``{anomes: valor}``."""
    if df is None or df.empty:
        return {}
    return {
        str(row["ANOMES"]).strip(): _as_float(row[coluna_valor]) for _, row in df.iterrows()
    }


def _serie_ibs_cbs_por_anomes(df: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Converte o resultado de IBS/CBS mensal em ``{(anomes, trib): valor}``."""
    if df is None or df.empty:
        return {}
    return {
        (str(row["ANOMES"]).strip(), str(row["TRIB"]).strip()): _as_float(row["VALOR"])
        for _, row in df.iterrows()
    }


def buscar_evolucao_mensal(
    filial: str | list[str],
    data_final: date,
    meses: int = 12,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
) -> pd.DataFrame:
    """Retorna a evolução mês a mês dos últimos ``meses`` meses até ``data_final``.

    Serve de base para o comparativo mês a mês / ano a ano: cada linha é um
    mês (mesmo quando não há nenhum documento nele - a série fica completa,
    sem buracos, para o gráfico). Colunas: ANOMES ("AAAAMM"), MES (date, dia
    1 do mês), QTD_NF_ENTRADA, VALOR_NF_ENTRADA, ICMS_ENTRADA, IBS_ENTRADA,
    CBS_ENTRADA, PIS_ENTRADA, COFINS_ENTRADA e os equivalentes de saída.

    Em caso de falha, retorna DataFrame vazio (degradação graciosa).
    """
    filiais = _normalizar_filiais(filial)
    if not filiais or meses < 1:
        return pd.DataFrame()

    ano_ini, mes_ini = _mes_anterior(data_final.year, data_final.month, meses - 1)
    data_ini_sql = date(ano_ini, mes_ini, 1).strftime("%Y%m%d")
    data_fim_sql = _data_sql(data_final)

    # Gera a lista de "AAAAMM" mês a mês (sem usar pandas.date_range para não
    # depender de fuso/calendário) - vira o esqueleto fixo da série abaixo.
    anomeses: list[str] = []
    ano, mes = ano_ini, mes_ini
    for _ in range(meses):
        anomeses.append(f"{ano:04d}{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    # "base" é um esqueleto com todos os meses da janela, zerado. As
    # consultas SQL abaixo só trazem os meses que têm movimento (GROUP BY
    # ANOMES); em vez de fazer merge (que reordenaria/duplicaria linhas em
    # casos de tipos diferentes), preenchemos cada coluna via dicionário
    # {anomes: valor} e .map(), garantindo que o gráfico sempre mostre todos
    # os meses da janela, mesmo os sem nenhuma nota (ver docstring acima).
    base = pd.DataFrame({"ANOMES": anomeses})
    for coluna in (
        "QTD_NF_ENTRADA", "VALOR_NF_ENTRADA", "ICMS_ENTRADA",
        "QTD_NF_SAIDA", "VALOR_NF_SAIDA", "ICMS_SAIDA",
        "IBS_ENTRADA", "CBS_ENTRADA", "IBS_SAIDA", "CBS_SAIDA",
        "PIS_ENTRADA", "COFINS_ENTRADA", "PIS_SAIDA", "COFINS_SAIDA",
    ):
        base[coluna] = 0.0

    try:
        if tipo_nfe != "Saída":
            sql_e, params_filial_e, params_status_e = queries.sql_evolucao_mensal_entrada(
                filiais, fornecedor
            )
            params_e = params_filial_e + [data_ini_sql, data_fim_sql]
            if fornecedor:
                params_e.append(fornecedor)
            params_e += params_status_e
            df_e = _ler_sql(sql_e, params_e, rotulo="evolucao_mensal_entrada")
            qtd_e = _serie_por_anomes(df_e, "QTD_NF_ENTRADA")
            valor_e = _serie_por_anomes(df_e, "VALOR_NF_ENTRADA")
            icms_e = _serie_por_anomes(df_e, "ICMS_ENTRADA")
            base["QTD_NF_ENTRADA"] = base["ANOMES"].map(lambda a: qtd_e.get(a, 0.0))
            base["VALOR_NF_ENTRADA"] = base["ANOMES"].map(lambda a: valor_e.get(a, 0.0))
            base["ICMS_ENTRADA"] = base["ANOMES"].map(lambda a: icms_e.get(a, 0.0))

            sql_ibs_e, params_ibs_e = queries.sql_ibs_cbs_mensal_entrada(filiais, fornecedor)
            params_ibs_e_full = params_ibs_e + [
                settings.COD_TRIB_IBS_ENTRADA, settings.COD_TRIB_CBS_ENTRADA,
                data_ini_sql, data_fim_sql,
            ]
            if fornecedor:
                params_ibs_e_full.append(fornecedor)
            df_ibs_e = _ler_sql(sql_ibs_e, params_ibs_e_full, rotulo="ibs_cbs_mensal_entrada")
            ibs_cbs_e = _serie_ibs_cbs_por_anomes(df_ibs_e)
            base["IBS_ENTRADA"] = base["ANOMES"].map(
                lambda a: ibs_cbs_e.get((a, settings.COD_TRIB_IBS_ENTRADA), 0.0)
            )
            base["CBS_ENTRADA"] = base["ANOMES"].map(
                lambda a: ibs_cbs_e.get((a, settings.COD_TRIB_CBS_ENTRADA), 0.0)
            )

            sql_pc_e, params_pc_e = queries.sql_pis_cofins_mensal_entrada(filiais, fornecedor)
            params_pc_e_full = params_pc_e + [data_ini_sql, data_fim_sql]
            if fornecedor:
                params_pc_e_full.append(fornecedor)
            df_pc_e = _ler_sql(sql_pc_e, params_pc_e_full, rotulo="pis_cofins_mensal_entrada")
            pis_e = _serie_por_anomes(df_pc_e, "VALOR_PIS")
            cofins_e = _serie_por_anomes(df_pc_e, "VALOR_COFINS")
            base["PIS_ENTRADA"] = base["ANOMES"].map(lambda a: pis_e.get(a, 0.0))
            base["COFINS_ENTRADA"] = base["ANOMES"].map(lambda a: cofins_e.get(a, 0.0))

        if tipo_nfe != "Entrada":
            sql_s, params_filial_s, params_status_s = queries.sql_evolucao_mensal_saida(
                filiais, cliente
            )
            params_s = params_filial_s + [data_ini_sql, data_fim_sql]
            if cliente:
                params_s.append(cliente)
            params_s += params_status_s
            df_s = _ler_sql(sql_s, params_s, rotulo="evolucao_mensal_saida")
            qtd_s = _serie_por_anomes(df_s, "QTD_NF_SAIDA")
            valor_s = _serie_por_anomes(df_s, "VALOR_NF_SAIDA")
            icms_s = _serie_por_anomes(df_s, "ICMS_SAIDA")
            base["QTD_NF_SAIDA"] = base["ANOMES"].map(lambda a: qtd_s.get(a, 0.0))
            base["VALOR_NF_SAIDA"] = base["ANOMES"].map(lambda a: valor_s.get(a, 0.0))
            base["ICMS_SAIDA"] = base["ANOMES"].map(lambda a: icms_s.get(a, 0.0))

            sql_ibs_s, params_ibs_s = queries.sql_ibs_cbs_mensal_saida(filiais, cliente)
            params_ibs_s_full = params_ibs_s + [
                settings.COD_TRIB_IBS_SAIDA, settings.COD_TRIB_CBS_SAIDA,
                data_ini_sql, data_fim_sql,
            ]
            if cliente:
                params_ibs_s_full.append(cliente)
            df_ibs_s = _ler_sql(sql_ibs_s, params_ibs_s_full, rotulo="ibs_cbs_mensal_saida")
            ibs_cbs_s = _serie_ibs_cbs_por_anomes(df_ibs_s)
            base["IBS_SAIDA"] = base["ANOMES"].map(
                lambda a: ibs_cbs_s.get((a, settings.COD_TRIB_IBS_SAIDA), 0.0)
            )
            base["CBS_SAIDA"] = base["ANOMES"].map(
                lambda a: ibs_cbs_s.get((a, settings.COD_TRIB_CBS_SAIDA), 0.0)
            )

            sql_pc_s, params_pc_s = queries.sql_pis_cofins_mensal_saida(filiais, cliente)
            params_pc_s_full = params_pc_s + [data_ini_sql, data_fim_sql]
            if cliente:
                params_pc_s_full.append(cliente)
            df_pc_s = _ler_sql(sql_pc_s, params_pc_s_full, rotulo="pis_cofins_mensal_saida")
            pis_s = _serie_por_anomes(df_pc_s, "VALOR_PIS")
            cofins_s = _serie_por_anomes(df_pc_s, "VALOR_COFINS")
            base["PIS_SAIDA"] = base["ANOMES"].map(lambda a: pis_s.get(a, 0.0))
            base["COFINS_SAIDA"] = base["ANOMES"].map(lambda a: cofins_s.get(a, 0.0))
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar a evolução mensal: %s", exc)
        return pd.DataFrame()

    base["MES"] = base["ANOMES"].map(lambda a: date(int(a[:4]), int(a[4:6]), 1))
    return base.sort_values("MES").reset_index(drop=True)


def buscar_status_documentos(
    filial: str | list[str], data_inicial: date, data_final: date
) -> pd.DataFrame:
    """Retorna a distribuição de F1_STATUS/F2_STATUS no período/filial(is).

    Serve para ajudar a identificar o valor que representa "cancelado"
    nesta instalação (ver STATUS_CANCELADO_ENTRADA/SAIDA em settings.py) -
    exibido no checklist de qualidade dos dados. Colunas: TIPO, STATUS, QTD.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame()

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    partes: list[pd.DataFrame] = []
    try:
        sql_e, params_filial_e = queries.sql_status_entrada(filiais)
        df_e = _ler_sql(sql_e, params_filial_e + [data_ini, data_fim], rotulo="status_entrada")
        if not df_e.empty:
            df_e = df_e.copy()
            df_e.insert(0, "TIPO", "Entrada")
            partes.append(df_e)

        sql_s, params_filial_s = queries.sql_status_saida(filiais)
        df_s = _ler_sql(sql_s, params_filial_s + [data_ini, data_fim], rotulo="status_saida")
        if not df_s.empty:
            df_s = df_s.copy()
            df_s.insert(0, "TIPO", "Saída")
            partes.append(df_s)
    except Exception as exc:
        logger.warning("Erro ao consultar status das notas: %s", exc)
        return pd.DataFrame()

    if not partes:
        return pd.DataFrame()

    df = pd.concat(partes, ignore_index=True)
    # Status em branco é um valor real no Protheus (nem sempre preenchido) -
    # trocamos por um rótulo explícito para não confundir com "sem dados"
    # ao exibir a distribuição na tela de qualidade dos dados.
    df["STATUS"] = df["STATUS"].astype(str).str.strip().replace("", "(em branco)")
    return df
