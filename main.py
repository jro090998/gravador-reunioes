"""
Conversor de Gravações de Reuniões → Transcrição TXT
Suporta: Google Meet (via Google Drive) e Zoho Meetings
Transcrição: Whisper local (offline)
"""

import sys
from pathlib import Path

import config
from transcriber import whisper_local
from output import txt_writer


def _formatar_tamanho(bytes_: str | int | None) -> str:
    if not bytes_:
        return "?"
    b = int(bytes_)
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _menu_selecao(gravacoes: list[dict]) -> list[dict]:
    """Exibe lista de gravações e permite o usuário selecionar quais transcrever."""
    print("\nGravações disponíveis:")
    print("-" * 70)
    for i, g in enumerate(gravacoes, 1):
        tamanho = _formatar_tamanho(g.get("size"))
        data = (g.get("createdTime") or "")[:10]
        print(f"  [{i:2}] {g['name'][:50]:<50} {tamanho:>8}  {data}")
    print("-" * 70)

    print("\nDigite os números das gravações para transcrever (ex: 1,3,5)")
    print("Ou pressione ENTER para transcrever TODAS:")
    entrada = input("> ").strip()

    if not entrada:
        return gravacoes

    selecionados = []
    for parte in entrada.split(","):
        parte = parte.strip()
        if parte.isdigit():
            idx = int(parte) - 1
            if 0 <= idx < len(gravacoes):
                selecionados.append(gravacoes[idx])
            else:
                print(f"  Número inválido ignorado: {parte}")
    return selecionados


def _processar(arquivo_local: Path, nome_original: str) -> None:
    print(f"\n>>> Processando: {nome_original}")
    texto = whisper_local.transcrever(arquivo_local)

    destino = txt_writer.salvar(nome_original, texto)
    print(f"  Transcrição salva: {destino}")


def modo_google_meet():
    from sources import google_drive
    print("\n[Google Meet / Google Drive]")
    print("Buscando gravações...")
    gravacoes = google_drive.listar_gravacoes()

    if not gravacoes:
        print("Nenhuma gravação de reunião encontrada no Google Drive.")
        return

    selecionados = _menu_selecao(gravacoes)
    if not selecionados:
        print("Nenhuma gravação selecionada.")
        return

    for gravacao in selecionados:
        try:
            caminho = google_drive.baixar_arquivo(gravacao, config.DOWNLOADS_DIR)
            _processar(caminho, gravacao["name"])
        except Exception as e:
            print(f"  ERRO em '{gravacao['name']}': {e}")


def modo_zoho():
    from sources import zoho
    print("\n[Zoho Meetings]")
    print("Buscando gravações...")
    gravacoes = zoho.listar_gravacoes()

    if not gravacoes:
        print("Nenhuma gravação encontrada no Zoho Meetings.")
        return

    selecionados = _menu_selecao(gravacoes)
    if not selecionados:
        print("Nenhuma gravação selecionada.")
        return

    for gravacao in selecionados:
        try:
            caminho = zoho.baixar_arquivo(gravacao, config.DOWNLOADS_DIR)
            _processar(caminho, gravacao["name"])
        except Exception as e:
            print(f"  ERRO em '{gravacao['name']}': {e}")


def modo_arquivo_local():
    print("\n[Arquivo local]")
    print("Digite o caminho do arquivo de áudio/vídeo:")
    caminho_str = input("> ").strip().strip('"')
    caminho = Path(caminho_str)

    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}")
        return

    _processar(caminho, caminho.name)


def modo_playwright_meet():
    import asyncio
    from sources import playwright_meet

    print("\n[Google Meet via link - gravacao ao vivo]")
    print("Cole o link da reuniao:")
    url = input("> ").strip()

    if not url.startswith("http"):
        print("Link invalido.")
        return

    try:
        caminho = asyncio.run(playwright_meet.entrar_e_gravar(url, config.DOWNLOADS_DIR))
        _processar(caminho, "meet_gravacao")
    except Exception as e:
        print(f"  ERRO: {e}")


def menu_principal():
    print("\n" + "=" * 50)
    print("  CONVERSOR DE REUNIOES -> TRANSCRICAO TXT")
    print(f"  Modelo Whisper: {config.WHISPER_MODEL} | Idioma: {config.WHISPER_LANGUAGE}")
    print("=" * 50)
    print("\nEscolha a fonte das gravacoes:")
    print("  [1] Google Meet (via Google Drive)")
    print("  [2] Zoho Meetings")
    print("  [3] Arquivo local (mp4, mp3, wav, m4a...)")
    print("  [4] Google Meet via link (gravacao ao vivo)")
    print("  [0] Sair")

    opcao = input("\nOpcao: ").strip()
    return opcao


def main():
    while True:
        opcao = menu_principal()
        if opcao == "1":
            modo_google_meet()
        elif opcao == "2":
            modo_zoho()
        elif opcao == "3":
            modo_arquivo_local()
        elif opcao == "4":
            modo_playwright_meet()
        elif opcao == "0":
            print("Saindo.")
            break
        else:
            print("Opcao invalida.")

        print("\nPressione ENTER para continuar...")
        input()


if __name__ == "__main__":
    main()
