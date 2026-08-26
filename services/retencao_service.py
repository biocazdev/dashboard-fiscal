"""Serviço de Retenções (IR/PIS/COFINS/CSLL) - Contas a Pagar (SE2010).

Aba "Retenções" do dashboard - equivalente ao relatório Reinf R-4020
("Pagamentos/Créditos a beneficiário PJ") que o contador já gera fora do
sistema. Diferente do resto do dashboard (que lê notas fiscais - SF1/SF2),
esta aba lê os TÍTULOS de contas a pagar (SE2), onde ficam as retenções
sobre pagamentos a fornecedores PJ.

Investigação concluída em 25/08/2026 (Biocaz - ver DOCUMENTACAO.md):
    Valor retido: E2_IRRF/E2_PIS/E2_COFINS/E2_CSLL - validado recalculando
    as alíquotas padrão (1,5% IR, 0,65% PIS, 3% COFINS, 1% CSLL) contra 2
    títulos reais e batendo exatamente. NÃO usar
    E2_VRETIRF/E2_VRETPIS/E2_VRETCOF/E2_VRETCSL - ficaram zerados em todos
    os 85 títulos testados nesta instalação. COFINS truncado para "COF"
    (mesmo padrão de SD1/SD2).

    "Cod. R" (código de natureza de rendimento do Reinf, ex.: 15014): NÃO
    existe em nenhuma tabela acessível pelo banco - nem no título
    (E2_CODRET veio em branco) nem no cadastro de natureza financeira
    (SED010: ED_CODRET/ED_NATREN/ED_GRPNAT/ED_INDRET vieram em branco nas 38
    naturezas cadastradas). Provavelmente calculado só pelo Gerador
    EFD-Reinf na hora de gerar o evento oficial. Mapeamento manual e
    opcional via RETENCAO_NATUREZA_CODRET (settings.py) - sem mapeamento
    configurado, a coluna "Cod. R" fica em branco.

    Sem E2_LOJA na SE2010 (não existe nesta instalação) - o vínculo com o
    cadastro de fornecedores (SA2) para trazer o CNPJ usa só o código
    (A2_COD = E2_FORNECE), sem o componente de loja usado no resto do
    dashboard (SF1/SF2 -> SA2/SA1).

Aba "Retenções x Financeiro" (25/08/2026, REDESENHADA DUAS VEZES no mesmo
dia após testes ao vivo do cliente - ver DOCUMENTACAO.md e settings.py -
TABELA_FINANCEIRO - para o histórico completo):
    Confere se cada tributo retido em um título (SE2010) já foi "gerado no
    Financeiro". A hipótese inicial (comparar com SEF010 pela baixa do
    próprio título) estava errada: o Protheus grava o valor retido como um
    OUTRO TÍTULO na própria SE2010, mas por DOIS padrões diferentes
    encontrados nesta instalação:

    - Padrão A: título "irmão" com o MESMO FILIAL+PREFIXO+NÚMERO do
      original, E2_TIPO='TX' (o original é 'VL'), E2_NATUREZ = código do
      tributo (IRF/PIS/COF/CSL), E2_FORNECE = credor da guia (ex.:
      "UNIAO"). Confirmado com o título 000000002-1 (fornecedor 000004,
      E2_IRRF=300): título irmão E2_NUM=000000002/E2_TIPO=TX/
      E2_NATUREZ=IRF/E2_VALOR=300, já baixado (E2_BAIXA=20260825) mesmo
      com o título original ainda em aberto.
    - Padrão B: título com numeração PRÓPRIA (prefixo "TG", ex.:
      "TG0000002"), E2_TIPO já é o código do tributo direto, SEM nenhum
      campo estruturado de vínculo com o título original - só o texto do
      Histórico ("E00081 - NF: 58 / NFS") relaciona ao número/série da NF.
      Confirmado com o título NFS58-01 (fornecedor 000316): os 4 valores
      retidos (E2_IRRF=184,62/E2_PIS=80/E2_COFINS=369,24/E2_CSLL=123,08)
      batem exatamente com TG0000002/TG0000004/TG0000005/TG0000003.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

from config import settings
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
    "FILIAL", "DOCUMENTO", "FORNECEDOR", "NOME_FORNECEDOR", "CNPJ",
    "NATUREZA", "COD_R", "EMISSAO", "VENCIMENTO", "BAIXA",
    "BASE_IR", "VALOR_IR", "BASE_PIS", "VALOR_PIS",
    "BASE_COFINS", "VALOR_COFINS", "BASE_CSLL", "VALOR_CSLL",
    "VALOR_TOTAL_RETIDO",
]

_COLUNAS_VAZIO_VALIDACAO = [
    "FILIAL", "DOCUMENTO", "FORNECEDOR", "NOME_FORNECEDOR",
    "EMISSAO", "VENCIMENTO", "BAIXA",
    "VALOR_TITULO", "VALOR_RETIDO", "VALOR_LIQUIDO_ESPERADO",
    "QTD_TITULOS_RETENCAO", "VALOR_GERADO_FINANCEIRO", "QTD_BAIXADOS",
    "DATA_ULTIMA_BAIXA", "DIFERENCA", "STATUS",
]

_STATUS_NAO_GERADO = "🔴 Não gerado"
_STATUS_DIVERGENTE = "🟡 Divergente"
_STATUS_AGUARDANDO_BAIXA = "🔵 Aguardando baixa"
_STATUS_OK = "🟢 OK"


def _tolerancia() -> Decimal:
    """Tolerância de diferença para considerar o valor financeiro conferido.

    Mesma tolerância usada na Conciliação Fiscal x Contábil
    (``TOLERANCIA_CONCILIACAO``), para manter o mesmo critério no dashboard.
    """
    try:
        return Decimal(settings.TOLERANCIA_CONCILIACAO)
    except InvalidOperation:
        return Decimal("0.05")


def _status_financeiro(
    qtd_titulos_retencao: int, diferenca: float, qtd_baixados: int
) -> str:
    """Classifica o status da validação Retenções x Financeiro.

    ``qtd_titulos_retencao`` é a quantidade de títulos "irmãos" de taxa
    (E2_TIPO='TX') localizados na SE2010 para o mesmo título original
    (mesmo FILIAL+PREFIXO+NÚMERO). Nenhum encontrado = a retenção não foi
    gerada no Financeiro (problema real). Encontrado(s) mas com soma
    divergente do total retido = problema de valor. Encontrado(s), valor
    batendo, mas ainda sem baixa = normal (só ainda não foi pago - não é
    tratado como problema). Só é "OK" quando os títulos de taxa existem,
    o valor bate e já foram todos baixados.
    """
    if not qtd_titulos_retencao:
        return _STATUS_NAO_GERADO
    if abs(Decimal(str(diferenca))) > _tolerancia():
        return _STATUS_DIVERGENTE
    if qtd_baixados < qtd_titulos_retencao:
        return _STATUS_AGUARDANDO_BAIXA
    return _STATUS_OK


def _mapa_codret() -> dict[str, str]:
    """Mapa E2_NATUREZ -> "Cod. R", a partir de ``RETENCAO_NATUREZA_CODRET``.

    Mesmo padrão de ``conciliacao_service._rotulos_origem``
    (CT2_ORIGEM_ROTULOS). Vazio (padrão) = mapa vazio, coluna "Cod. R" fica
    em branco para todas as linhas.
    """
    mapa: dict[str, str] = {}
    for par in settings.RETENCAO_NATUREZA_CODRET.split(","):
        if ":" not in par:
            continue
        natureza, _, codigo = par.partition(":")
        natureza = natureza.strip()
        codigo = codigo.strip()
        if natureza and codigo:
            mapa[natureza] = codigo
    return mapa


def buscar_retencoes(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
) -> pd.DataFrame:
    """Retorna os títulos de contas a pagar com retenção de IR/PIS/COFINS/CSLL.

    O período filtra pela data de emissão do título (E2_EMISSAO), na mesma
    linha do resto do dashboard - o evento Reinf oficial usa a data do
    pagamento, então o total aqui pode não bater 100% com o relatório
    oficial se houver títulos pagos em mês diferente do de emissão.

    Colunas: FILIAL, DOCUMENTO, FORNECEDOR, NOME_FORNECEDOR, CNPJ, NATUREZA,
    COD_R, EMISSAO, VENCIMENTO, BAIXA, BASE_IR, VALOR_IR, BASE_PIS,
    VALOR_PIS, BASE_COFINS, VALOR_COFINS, BASE_CSLL, VALOR_CSLL,
    VALOR_TOTAL_RETIDO.

    Em caso de falha, retorna DataFrame vazio (degradação graciosa) para
    não derrubar o dashboard.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial = queries.sql_retencoes(filiais, fornecedor)
    params = params_filial + [data_ini, data_fim]
    if fornecedor:
        params.append(fornecedor)

    try:
        df = _ler_sql(sql, params, rotulo="retencoes")
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar retenções (SE2010): %s", exc)
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    if df.empty:
        return pd.DataFrame(columns=_COLUNAS_VAZIO)

    df = df.copy()
    mapa = _mapa_codret()
    # E2_NATUREZ é campo de largura fixa no Protheus - vem com espaços à
    # direita, por isso o strip antes de usar como chave do mapa manual.
    df["NATUREZA"] = df["NATUREZA"].astype(str).str.strip()
    # Sem mapeamento configurado para a natureza, "Cod. R" fica em branco
    # (ver docstring do módulo - o Protheus não guarda esse código em
    # nenhuma tabela acessível nesta instalação).
    df["COD_R"] = df["NATUREZA"].map(lambda n: mapa.get(n, ""))

    # Bases e valores retidos vêm do SQL Server como Decimal/str - converte
    # para float para permitir soma/formatação no pandas sem surpresas de
    # tipo.
    for coluna in (
        "BASE_IR", "VALOR_IR", "BASE_PIS", "VALOR_PIS",
        "BASE_COFINS", "VALOR_COFINS", "BASE_CSLL", "VALOR_CSLL",
    ):
        df[coluna] = df[coluna].map(_as_float)
    # Total retido = soma dos 4 tributos (não existe campo único no
    # Protheus para isso).
    df["VALOR_TOTAL_RETIDO"] = (
        df["VALOR_IR"] + df["VALOR_PIS"] + df["VALOR_COFINS"] + df["VALOR_CSLL"]
    )

    # Datas do Protheus vêm no formato "YYYYMMDD" (ou vazias); BAIXA pode
    # ser None quando o título ainda está em aberto.
    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["VENCIMENTO"] = df["VENCIMENTO"].map(_parse_data_protheus)
    df["BAIXA"] = df["BAIXA"].map(_parse_data_protheus)
    # CNPJ/NOME_FORNECEDOR podem vir NULL (join com SA2 pelo código, sem
    # loja - ver docstring do módulo) - fillna evita "None" aparecendo na
    # tela.
    df["CNPJ"] = df["CNPJ"].fillna("").astype(str).str.strip()
    df["NOME_FORNECEDOR"] = df["NOME_FORNECEDOR"].fillna("").astype(str).str.strip()
    df["FORNECEDOR"] = df["FORNECEDOR"].astype(str).str.strip()

    # Ordena por emissão e depois fornecedor para uma leitura cronológica
    # estável na tela (mesmo critério usado nas outras abas do dashboard).
    return df.sort_values(["EMISSAO", "FORNECEDOR"]).reset_index(drop=True)


def buscar_validacao_financeiro(
    filial: str | list[str],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
) -> pd.DataFrame:
    """Valida se cada retenção de um título já foi gerada no Financeiro.

    Mesmo filtro de título da aba "Retenções" (SE2010, com pelo menos uma
    retenção de IR/PIS/COFINS/CSLL diferente de zero). Para cada título,
    procura na própria SE2010 o(s) título(s) "irmão(s)" de taxa
    (E2_TIPO='TX', mesmo FILIAL+PREFIXO+NÚMERO, E2_NATUREZ em
    IRF/PIS/COF/CSL) e soma o que foi encontrado/baixado.

    Colunas: FILIAL, DOCUMENTO, FORNECEDOR, NOME_FORNECEDOR, EMISSAO,
    VENCIMENTO, BAIXA (do título original, informativo),
    VALOR_TITULO, VALOR_RETIDO, VALOR_LIQUIDO_ESPERADO,
    QTD_TITULOS_RETENCAO, VALOR_GERADO_FINANCEIRO, QTD_BAIXADOS,
    DATA_ULTIMA_BAIXA, DIFERENCA, STATUS
    ("🔴 Não gerado" / "🟡 Divergente" / "🔵 Aguardando baixa" / "🟢 OK").

    Em caso de falha, retorna DataFrame vazio (degradação graciosa) para
    não derrubar o dashboard.
    """
    filiais = _normalizar_filiais(filial)
    if not filiais:
        return pd.DataFrame(columns=_COLUNAS_VAZIO_VALIDACAO)

    data_ini = _data_sql(data_inicial)
    data_fim = _data_sql(data_final)

    sql, params_filial = queries.sql_validacao_financeiro_retencoes(filiais, fornecedor)
    params = params_filial + [data_ini, data_fim]
    if fornecedor:
        params.append(fornecedor)

    try:
        df = _ler_sql(sql, params, rotulo="validacao_financeiro_retencoes")
    except DatabaseConnectionError:
        raise
    except Exception as exc:
        logger.warning("Erro ao consultar validação Retenções x Financeiro: %s", exc)
        return pd.DataFrame(columns=_COLUNAS_VAZIO_VALIDACAO)

    if df.empty:
        return pd.DataFrame(columns=_COLUNAS_VAZIO_VALIDACAO)

    df = df.copy()
    for coluna in ("VALOR_TITULO", "VALOR_RETIDO", "VALOR_GERADO_FINANCEIRO"):
        df[coluna] = df[coluna].map(_as_float)
    # Contagens (COUNT do SQL) podem vir None quando não há nenhum título
    # "irmão" de taxa - trata como 0 em vez de deixar NaN no DataFrame.
    df["QTD_TITULOS_RETENCAO"] = df["QTD_TITULOS_RETENCAO"].map(
        lambda v: int(v) if v is not None else 0
    )
    df["QTD_BAIXADOS"] = df["QTD_BAIXADOS"].map(lambda v: int(v) if v is not None else 0)
    # Líquido esperado = valor do título menos o que foi retido (o que o
    # fornecedor efetivamente deveria receber).
    df["VALOR_LIQUIDO_ESPERADO"] = df["VALOR_TITULO"] - df["VALOR_RETIDO"]
    # Diferença = retido no título original menos o que foi de fato gerado
    # como título de taxa no Financeiro; usada por _status_financeiro para
    # classificar a linha.
    df["DIFERENCA"] = df["VALOR_RETIDO"] - df["VALOR_GERADO_FINANCEIRO"]

    df["EMISSAO"] = df["EMISSAO"].map(_parse_data_protheus)
    df["VENCIMENTO"] = df["VENCIMENTO"].map(_parse_data_protheus)
    df["BAIXA"] = df["BAIXA"].map(_parse_data_protheus)
    df["DATA_ULTIMA_BAIXA"] = df["DATA_ULTIMA_BAIXA"].map(_parse_data_protheus)

    # STATUS: nenhum título "TX" localizado = não gerado; localizado(s) mas
    # valor divergente = divergente; localizado(s) e valor batendo mas nem
    # todos baixados = aguardando baixa (normal); tudo baixado = OK.
    df["STATUS"] = df.apply(
        lambda r: _status_financeiro(
            r["QTD_TITULOS_RETENCAO"], r["DIFERENCA"], r["QTD_BAIXADOS"]
        ),
        axis=1,
    )

    df["NOME_FORNECEDOR"] = df["NOME_FORNECEDOR"].fillna("").astype(str).str.strip()
    df["FORNECEDOR"] = df["FORNECEDOR"].astype(str).str.strip()

    return df.sort_values(["EMISSAO", "FORNECEDOR"]).reset_index(drop=True)
