"""Configuração de logging da aplicação.

Os logs são gravados em ``logs/dashboard.log`` com rotação automática.

Regras de segurança (seção 34 da especificação):
- NUNCA registrar senhas ou connection string completa.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# BASE_DIR é a raiz do projeto (uma pasta acima de utils/), calculada a
# partir do caminho deste arquivo - assim o log sempre vai para
# <raiz-do-projeto>/logs/dashboard.log, não importa de onde o Streamlit
# foi iniciado (cwd pode variar conforme o .bat/terminal usado).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "dashboard.log")

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configurar_logger(nivel: int = logging.INFO) -> None:
    """Configura o logger raiz da aplicação (idempotente).

    "Idempotente" aqui quer dizer: pode ser chamada várias vezes (o
    Streamlit re-executa o script inteiro a cada interação do usuário)
    sem duplicar handlers - se um ``RotatingFileHandler`` já estiver
    registrado no logger raiz, a função simplesmente retorna sem
    adicionar outro (senão cada mensagem de log seria escrita 2x, 3x...
    uma vez por handler acumulado).
    """
    os.makedirs(LOGS_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(nivel)

    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            return

    # Rotação automática: quando dashboard.log passa de 5 MB, ele vira
    # dashboard.log.1 e um arquivo novo é iniciado; mantém no máximo 3
    # arquivos antigos (backupCount) para não crescer sem limite.
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
