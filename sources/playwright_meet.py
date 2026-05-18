"""
Entra em uma reunião Google Meet via link usando Playwright,
grava o áudio do sistema (WASAPI loopback) e retorna o caminho do WAV.
"""

import asyncio
import threading
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wavfile
import sounddevice as sd
from playwright.async_api import async_playwright

SAMPLE_RATE = 16000
PROFILE_DIR = Path.home() / ".playwright_meet_profile"


def _encontrar_stereo_mix() -> int | None:
    """Retorna o índice do dispositivo Stereo Mix / Mixagem Estéreo, se disponível."""
    for i, d in enumerate(sd.query_devices()):
        nome = d["name"].lower()
        if d["max_input_channels"] > 0 and any(
            k in nome for k in ["stereo mix", "mixagem", "what u hear", "wave out"]
        ):
            return i
    return None


def _gravar_loopback(chunks: list, parar: threading.Event) -> None:
    device = None
    kwargs: dict = {}

    # Tenta WASAPI loopback primeiro
    try:
        kwargs = {"extra_settings": sd.WasapiSettings(loopback=True)}
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", **kwargs) as s:
            s.read(1)  # teste rápido
        print("  Gravando via WASAPI loopback.")
    except Exception:
        kwargs = {}
        device = _encontrar_stereo_mix()
        if device is not None:
            print(f"  Gravando via Stereo Mix (dispositivo {device}).")
        else:
            print("  AVISO: Nenhum dispositivo loopback encontrado. O audio pode nao ser capturado.")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=device,
            **kwargs,
        ) as stream:
            while not parar.is_set():
                data, _ = stream.read(1024)
                chunks.append(data.copy())
    except Exception as e:
        print(f"\n  [Audio] Erro na gravacao: {e}")


async def _tentar_entrar(page) -> bool:
    """Clica nos botões de entrada do Meet automaticamente."""
    await page.wait_for_load_state("domcontentloaded", timeout=20000)

    # Desliga microfone antes de entrar
    for seletor in [
        '[aria-label*="microfone"]',
        '[aria-label*="Microphone"]',
        '[data-is-muted="false"][data-tooltip*="microfone"]',
    ]:
        try:
            btn = page.locator(seletor).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                break
        except Exception:
            pass

    # Desliga câmera antes de entrar
    for seletor in [
        '[aria-label*="camera"]',
        '[aria-label*="Camera"]',
        '[aria-label*="camara"]',
    ]:
        try:
            btn = page.locator(seletor).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                break
        except Exception:
            pass

    # Clica em "Participar" / "Join now"
    seletores_join = [
        'button:has-text("Participar agora")',
        'button:has-text("Join now")',
        'button:has-text("Pedir para participar")',
        'button:has-text("Ask to join")',
        'button:has-text("Entrar")',
    ]
    for seletor in seletores_join:
        try:
            btn = page.locator(seletor).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("  Entrou na reuniao automaticamente.")
                return True
        except Exception:
            continue

    return False


async def entrar_e_gravar(url: str, downloads_dir: str | Path) -> Path:
    """
    Abre o Meet pelo link, grava o audio do sistema e retorna o caminho do WAV.
    Na primeira execucao abre o login do Google — feito uma vez so.
    """
    downloads_dir = Path(downloads_dir)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[np.ndarray] = []
    parar = threading.Event()
    thread_audio = threading.Thread(
        target=_gravar_loopback, args=(chunks, parar), daemon=True
    )

    async with async_playwright() as p:
        print("  Abrindo Chrome...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel="chrome",
            args=[
                "--use-fake-ui-for-media-stream",
                "--disable-blink-features=AutomationControlled",
            ],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url)

        print("  Aguardando tela do Meet...")
        entrou = await _tentar_entrar(page)

        if not entrou:
            print("\n  Nao foi possivel entrar automaticamente.")
            print("  Entre na reuniao manualmente no navegador e pressione ENTER aqui.")
            await asyncio.get_event_loop().run_in_executor(None, input)

        print("\n  [GRAVANDO] Pressione ENTER quando a reuniao terminar para salvar e transcrever.")
        thread_audio.start()

        await asyncio.get_event_loop().run_in_executor(None, input)

        parar.set()
        thread_audio.join(timeout=3)
        await context.close()

    if not chunks:
        raise RuntimeError("Nenhum audio foi capturado. Verifique as configuracoes de audio do Windows.")

    audio = np.concatenate(chunks, axis=0)
    caminho_wav = downloads_dir / "meet_gravacao.wav"
    wavfile.write(str(caminho_wav), SAMPLE_RATE, audio)

    duracao = len(audio) / SAMPLE_RATE
    print(f"  Audio salvo: {caminho_wav} ({duracao:.1f}s)")
    return caminho_wav
