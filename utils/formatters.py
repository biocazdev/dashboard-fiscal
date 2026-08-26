"""Formatação de valores para exibição no dashboard."""


def moeda(valor: float) -> str:
    """Formata um valor monetário no padrão brasileiro.

    Ex.: ``1250430.75`` -> ``R$ 1.250.430,75``
    """
    # Qualquer valor que não seja um número (None, string vazia vindo do
    # banco, etc.) vira 0,00 em vez de quebrar a tela.
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        valor = 0.0

    # Python formata número com separador de milhar "," e decimal ".";
    # o padrão brasileiro é o oposto. Formata primeiro no padrão inglês
    # (sempre com valor positivo - o sinal é tratado à parte logo abaixo)
    # e troca os separadores em 3 passos, usando "X" como marcador
    # temporário para não confundir o "," de milhar já convertido com o
    # "." decimal que ainda vai virar ",".
    texto = f"R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if valor < 0:
        texto = f"-{texto}"
    return texto


def quantidade(valor) -> str:
    """Formata uma quantidade inteira no padrão brasileiro.

    Ex.: ``15230`` -> ``15.230``
    """
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        valor = 0
    return f"{valor:,}".replace(",", ".")


def data_brasil(valor) -> str:
    """Formata uma data no padrão brasileiro (DD/MM/AAAA)."""
    try:
        return valor.strftime("%d/%m/%Y")
    except AttributeError:
        return str(valor)
