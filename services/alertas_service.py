"""Alertas visuais (semáforo) do dashboard.

Não consulta o banco diretamente - recebe os dados já calculados
(indicadores, resumo da conciliação, checklist de qualidade) e devolve uma
lista de alertas para exibir no topo da tela. Todos os limites são
configuráveis via ``.env`` (ver ``config/settings.py``, seção "Alertas
visuais") porque o que é "normal" varia de empresa para empresa - por
exemplo, esta base está em implantação e pode ter % de conciliação baixo
por um bom tempo sem que isso seja realmente um problema.
"""

from typing import Any

import pandas as pd

from config import settings
from services.conciliacao_service import StatusConciliacao
from utils.formatters import moeda

NIVEL_ATENCAO = "atencao"
NIVEL_CRITICO = "critico"


def _pct_conciliacao(resumo: dict[str, Any] | None) -> list[dict[str, str]]:
    """Avisa quando o % de conciliação está abaixo do limite configurado.

    ``resumo`` é o dict de resumo já calculado pela aba de Conciliação
    Fiscal x Contábil (não recalcula nada aqui). Sem resumo, ou período sem
    nenhum documento (``total`` zero/ausente), não há o que avisar.
    """
    if not resumo or not resumo.get("total"):
        return []
    pct = resumo.get("pct_conciliado", 0.0)
    limite = settings.ALERTA_PCT_CONCILIACAO_MIN
    if pct < limite:
        return [
            {
                "nivel": NIVEL_ATENCAO,
                "mensagem": (
                    f"Conciliação em {pct:.0%}, abaixo do limite configurado "
                    f"({limite:.0%}). Veja a aba Conciliação Fiscal x Contábil."
                ),
            }
        ]
    return []


def _pendencias_antigas(df_conciliacao: pd.DataFrame | None) -> list[dict[str, str]]:
    """Avisa quando há pendências mais antigas que o limite configurado."""
    if df_conciliacao is None or df_conciliacao.empty or "IDADE_DIAS" not in df_conciliacao.columns:
        return []
    limite = settings.ALERTA_IDADE_PENDENCIA_DIAS
    # Só "pendência" de fato: documento ainda não contabilizado ou com
    # valor divergente entre fiscal e contábil. Status OK/conciliado não
    # entra na contagem, mesmo que antigo.
    pendentes = df_conciliacao[
        df_conciliacao["STATUS"].isin(
            [StatusConciliacao.NAO_CONTABILIZADO, StatusConciliacao.DIVERGENTE]
        )
    ]
    # fillna(0) evita que uma idade ausente (NaN) seja tratada como "muito
    # antiga" por engano na comparação >= limite.
    antigas = pendentes[pendentes["IDADE_DIAS"].fillna(0) >= limite]
    if not antigas.empty:
        return [
            {
                "nivel": NIVEL_ATENCAO,
                "mensagem": (
                    f"{len(antigas)} documento(s) pendente(s) de contabilização "
                    f"há {limite}+ dias."
                ),
            }
        ]
    return []


def _saldo_icms(indicadores: dict[str, Any] | None) -> list[dict[str, str]]:
    """Avisa quando o Saldo de ICMS vira crédito ou passa de um valor configurado.

    Saldo negativo aqui significa crédito acumulado de ICMS (débito menor
    que crédito) - não é necessariamente um erro, mas pode indicar que a
    empresa está acumulando crédito sem compensar, por isso é só nível
    "atenção". Já ultrapassar o limite absoluto configurado
    (``ALERTA_SALDO_ICMS_MAX``) é tratado como "crítico" - foge do padrão
    esperado para o negócio, para mais ou para menos.
    """
    if not indicadores:
        return []
    saldo = indicadores.get("SALDO_ICMS", 0.0)
    alertas: list[dict[str, str]] = []
    if settings.ALERTA_SALDO_ICMS_CREDITO and saldo < 0:
        alertas.append(
            {
                "nivel": NIVEL_ATENCAO,
                "mensagem": f"Saldo de ICMS negativo (crédito acumulado): {moeda(saldo)}.",
            }
        )
    if settings.ALERTA_SALDO_ICMS_MAX:
        # ALERTA_SALDO_ICMS_MAX vem do .env como string - conversão pode
        # falhar se mal configurado; nesse caso simplesmente não aplica o
        # limite (não derruba o dashboard por um valor de config inválido).
        try:
            limite = float(settings.ALERTA_SALDO_ICMS_MAX)
        except ValueError:
            limite = None
        # abs() porque o limite é sobre a magnitude do saldo (débito ou
        # crédito), não sobre o sinal.
        if limite is not None and abs(saldo) > limite:
            alertas.append(
                {
                    "nivel": NIVEL_CRITICO,
                    "mensagem": (
                        f"Saldo de ICMS ({moeda(saldo)}) fora do padrão configurado "
                        f"(limite {moeda(limite)})."
                    ),
                }
            )
    return alertas


def _qualidade_dados(qtd_duplicadas: int, qtd_invalidas: int) -> list[dict[str, str]]:
    """Avisa quando o checklist de qualidade encontra problemas no período.

    Recebe as contagens já apuradas por ``qualidade_service`` - não
    recalcula nada, só decide se vira alerta. Ambos os casos são nível
    "atenção" (não impedem o uso do dashboard, mas merecem checagem manual
    do contador).
    """
    alertas: list[dict[str, str]] = []
    if qtd_duplicadas:
        alertas.append(
            {
                "nivel": NIVEL_ATENCAO,
                "mensagem": f"{qtd_duplicadas} nota(s) duplicada(s) encontrada(s) no período.",
            }
        )
    if qtd_invalidas:
        alertas.append(
            {
                "nivel": NIVEL_ATENCAO,
                "mensagem": f"{qtd_invalidas} nota(s) com valor zerado ou negativo no período.",
            }
        )
    return alertas


def montar_alertas(
    indicadores: dict[str, Any] | None = None,
    resumo_conciliacao: dict[str, Any] | None = None,
    df_conciliacao: pd.DataFrame | None = None,
    qtd_duplicadas: int = 0,
    qtd_invalidas: int = 0,
) -> list[dict[str, str]]:
    """Monta a lista de alertas visuais a partir dos dados já calculados.

    Não faz nenhuma consulta nova ao banco - reaproveita o que a tela já
    calculou (indicadores, resumo/DataFrame da conciliação, contagens do
    checklist de qualidade). Cada alerta é um dict
    ``{"nivel": "atencao"|"critico", "mensagem": str}``. Todos os limites
    são configuráveis no ``.env`` (ver settings.py).
    """
    # Cada _xxx() é independente e pode devolver 0, 1 ou mais alertas -
    # a ordem aqui também é a ordem de exibição na tela.
    alertas: list[dict[str, str]] = []
    alertas += _pct_conciliacao(resumo_conciliacao)
    alertas += _pendencias_antigas(df_conciliacao)
    alertas += _saldo_icms(indicadores)
    alertas += _qualidade_dados(qtd_duplicadas, qtd_invalidas)
    return alertas
