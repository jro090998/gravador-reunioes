import subprocess
import tempfile
from pathlib import Path

import whisper

import config

_modelo_cache = None


def _carregar_modelo():
    global _modelo_cache
    if _modelo_cache is None:
        print(f"  Carregando modelo Whisper '{config.WHISPER_MODEL}'...")
        _modelo_cache = whisper.load_model(config.WHISPER_MODEL)
        print("  Modelo carregado.")
    return _modelo_cache


def _extrair_audio(caminho_video: Path) -> Path:
    """Extrai áudio de arquivo de vídeo usando ffmpeg."""
    sufixo = caminho_video.suffix.lower()
    tipos_audio = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

    if sufixo in tipos_audio:
        return caminho_video

    destino = caminho_video.with_suffix(".wav")
    if destino.exists():
        return destino

    print(f"  Extraindo áudio de '{caminho_video.name}'...")
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(caminho_video),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{resultado.stderr}")

    return destino


def transcrever(caminho_arquivo: Path) -> str:
    """Transcreve um arquivo de áudio/vídeo usando Whisper local."""
    modelo = _carregar_modelo()
    audio = _extrair_audio(caminho_arquivo)

    idioma = config.WHISPER_LANGUAGE if config.WHISPER_LANGUAGE != "auto" else None

    print(f"  Transcrevendo '{caminho_arquivo.name}'...")
    resultado = modelo.transcribe(
        str(audio),
        language=idioma,
        verbose=False,
        fp16=False,
    )

    # Remove o WAV temporário se foi extraído de vídeo
    if audio != caminho_arquivo and audio.exists():
        audio.unlink()

    return resultado["text"].strip()
