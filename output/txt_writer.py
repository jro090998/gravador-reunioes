from pathlib import Path
from datetime import datetime

import config


def salvar(nome_arquivo: str, texto: str) -> Path:
    """Salva a transcrição em um arquivo TXT."""
    pasta = Path(config.OUTPUT_DIR)
    pasta.mkdir(parents=True, exist_ok=True)

    # Remove extensão original e adiciona .txt
    stem = Path(nome_arquivo).stem
    # Sanitiza nome do arquivo
    for char in r'\/:*?"<>|':
        stem = stem.replace(char, "_")

    destino = pasta / f"{stem}.txt"

    # Evita sobrescrever: adiciona timestamp se já existir
    if destino.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = pasta / f"{stem}_{ts}.txt"

    cabecalho = (
        f"Arquivo: {nome_arquivo}\n"
        f"Transcrito em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"{'=' * 60}\n\n"
    )

    destino.write_text(cabecalho + texto, encoding="utf-8")
    return destino
