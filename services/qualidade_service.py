"""Checklist de qualidade dos dados fiscais (Grupo D).

Verificações simples que ajudam a pegar problema de digitação/parametrização
no Protheus antes de virar dor de cabeça no fechamento contábil. Todas
operam sobre o DataFrame de detalhamento já consultado (não fazem SQL
adicional) - exceto a checagem de lotes CT2, que fica em
``conciliacao_service.lotes_saldo_diferente_zero``.
"""

import pandas as pd


def notas_duplicadas(detalhe: pd.DataFrame) -> pd.DataFrame:
    """Notas fiscais que aparecem mais de uma vez (mesma filial+tipo+doc+série).

    Em condições normais não deveria acontecer (chave natural da nota) -
    quando acontece, geralmente indica nota digitada duas vezes, filial
    trocada ou série divergente por erro de digitação.
    """
    if detalhe is None or detalhe.empty:
        return pd.DataFrame()

    # Chave natural da nota fiscal: mesmo tipo+número+série não deveria se
    # repetir. FILIAL não entra na chave de propósito - duas filiais com o
    # mesmo TIPO/DOC/SERIE também seria digitação estranha, então a
    # verificação é propositalmente mais ampla que o dashboard normal.
    chave = ["TIPO", "DOC", "SERIE"]
    contagem = detalhe.groupby(chave).size().reset_index(name="QTDE")
    duplicadas = contagem[contagem["QTDE"] > 1]
    if duplicadas.empty:
        return pd.DataFrame()

    # merge (inner) traz de volta todas as linhas originais que batem com
    # alguma combinação duplicada - não só uma linha por grupo - para o
    # contador poder ver e comparar as ocorrências lado a lado.
    return detalhe.merge(duplicadas[chave], on=chave, how="inner").sort_values(
        chave
    )


def notas_valor_invalido(detalhe: pd.DataFrame) -> pd.DataFrame:
    """Notas com valor zerado ou negativo - normalmente erro de digitação.

    Não distingue entrada/saída nem cancelamento - qualquer VALOR <= 0 no
    detalhamento já filtrado (mesmo recorte de filial/período da tela que
    chamou) é reportado, ficando a critério do contador avaliar se é um
    caso legítimo (ex.: nota de ajuste) ou erro.
    """
    if detalhe is None or detalhe.empty:
        return pd.DataFrame()
    return detalhe[detalhe["VALOR"] <= 0]


def resumo_qualidade(detalhe: pd.DataFrame) -> dict[str, int]:
    """Contagem rápida para os cartões do checklist de qualidade.

    Recebe o mesmo ``detalhe`` (DataFrame já filtrado) usado pelas duas
    funções acima e reexecuta as duas checagens só para contar - retorna
    ``{"duplicadas": int, "valor_invalido": int}``. ``detalhe is None`` é
    tratado à parte aqui (em vez de deixar as funções chamadas lidarem com
    isso) só para deixar explícito que o resultado nesse caso é sempre
    zero, sem custo de chamar as funções.
    """
    return {
        "duplicadas": len(notas_duplicadas(detalhe)) if detalhe is not None else 0,
        "valor_invalido": len(notas_valor_invalido(detalhe)) if detalhe is not None else 0,
    }
