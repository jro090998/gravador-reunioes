"""
Assistente de configuração do Conversor de Reuniões
Configura: Google Meet (Drive API) + Zoho Meetings
"""

import os
import sys
import json
import time
import webbrowser
import urllib.parse
import threading
import http.server
from pathlib import Path


# ──────────────────────────────────────────────
# Helpers de terminal
# ──────────────────────────────────────────────

def titulo(texto):
    print(f"\n{'=' * 55}")
    print(f"  {texto}")
    print(f"{'=' * 55}")

def passo(n, texto):
    print(f"\n[Passo {n}] {texto}")

def ok(texto):
    print(f"  OK  {texto}")

def info(texto):
    print(f"  >>  {texto}")

def erro(texto):
    print(f"  !!  {texto}")

def aguardar(msg="Pressione ENTER quando terminar..."):
    input(f"\n  --> {msg}")

# ──────────────────────────────────────────────
# Servidor local para capturar redirect OAuth
# ──────────────────────────────────────────────

_oauth_code = {"value": None}

class _OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _oauth_code["value"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style='font-family:sans-serif;text-align:center;padding:40px'>
                <h2>Autorizado com sucesso!</h2>
                <p>Pode fechar esta aba e voltar ao terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass  # silencia logs do servidor


def _iniciar_servidor_local(porta=8080):
    server = http.server.HTTPServer(("localhost", porta), _OAuthHandler)
    t = threading.Thread(target=server.handle_request)
    t.daemon = True
    t.start()
    return server


# ──────────────────────────────────────────────
# .env
# ──────────────────────────────────────────────

def _ler_env() -> dict:
    env = {}
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _salvar_env(dados: dict):
    env_path = Path(".env")
    existente = _ler_env()
    existente.update(dados)

    linhas = []
    # mantém comentários do .env.example como referência
    exemplo = Path(".env.example")
    if exemplo.exists():
        for linha in exemplo.read_text(encoding="utf-8").splitlines():
            if linha.startswith("#") or not linha.strip():
                linhas.append(linha)
            elif "=" in linha:
                chave = linha.split("=")[0].strip()
                valor = existente.get(chave, linha.split("=", 1)[1].strip())
                linhas.append(f"{chave}={valor}")
    else:
        for k, v in existente.items():
            linhas.append(f"{k}={v}")

    env_path.write_text("\n".join(linhas), encoding="utf-8")
    ok(f".env atualizado")


# ──────────────────────────────────────────────
# GOOGLE MEET
# ──────────────────────────────────────────────

def configurar_google():
    titulo("CONFIGURAÇÃO — GOOGLE MEET")

    info("As gravações do Google Meet ficam salvas no Google Drive.")
    info("Precisamos criar credenciais OAuth no Google Cloud Console.")
    print()

    # Verifica se já tem credentials.json
    if Path("credentials.json").exists():
        ok("credentials.json já encontrado na pasta!")
    else:
        passo(1, "Criar projeto no Google Cloud Console")
        info("Vou abrir o navegador. Se já tiver um projeto, pode usá-lo.")
        aguardar("ENTER para abrir o Google Cloud Console...")
        webbrowser.open("https://console.cloud.google.com/projectcreate")
        aguardar("Crie o projeto e pressione ENTER para continuar...")

        passo(2, "Ativar a Google Drive API")
        info("Vou abrir a página da Drive API. Clique em 'Ativar'.")
        aguardar("ENTER para abrir a página da Drive API...")
        webbrowser.open("https://console.cloud.google.com/apis/library/drive.googleapis.com")
        aguardar("Ative a API e pressione ENTER para continuar...")

        passo(3, "Configurar tela de consentimento OAuth")
        info("Vou abrir a configuração. Selecione 'Externo', preencha o nome do app")
        info("e adicione seu e-mail como 'usuário de teste'.")
        aguardar("ENTER para abrir a configuração OAuth...")
        webbrowser.open("https://console.cloud.google.com/apis/credentials/consent")
        aguardar("Configure e salve. Pressione ENTER para continuar...")

        passo(4, "Criar credenciais OAuth 2.0")
        info("Vou abrir a página de credenciais.")
        info("Clique em: Criar credenciais → ID do cliente OAuth")
        info("Tipo: 'App para computador' → dê um nome → Criar")
        info("Depois clique em 'Baixar JSON' e salve como 'credentials.json'")
        info(f"na pasta: {Path('.').resolve()}")
        aguardar("ENTER para abrir a página de credenciais...")
        webbrowser.open("https://console.cloud.google.com/apis/credentials")

        print()
        print("  Aguardando o arquivo credentials.json na pasta do projeto...")
        for _ in range(60):  # aguarda até 5 minutos
            if Path("credentials.json").exists():
                break
            time.sleep(5)
            print("    ...", end="\r")
        else:
            erro("credentials.json não encontrado após 5 minutos.")
            erro("Coloque o arquivo na pasta manualmente e rode o wizard novamente.")
            return False

    ok("credentials.json encontrado!")

    # Realiza autenticação e salva token
    passo(5, "Autenticar com sua conta Google")
    info("O navegador vai abrir para você fazer login e autorizar o acesso.")
    aguardar("ENTER para iniciar autenticação...")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("google_token.json", "w") as f:
            f.write(creds.to_json())
        ok("Token salvo em google_token.json")
        ok("Google Meet configurado com sucesso!")
        return True
    except Exception as e:
        erro(f"Erro na autenticação: {e}")
        return False


# ──────────────────────────────────────────────
# ZOHO MEETINGS
# ──────────────────────────────────────────────

def configurar_zoho():
    titulo("CONFIGURAÇÃO — ZOHO MEETINGS")

    info("Precisamos criar um app no Zoho API Console para acessar as gravações.")
    print()

    passo(1, "Criar app no Zoho API Console")
    info("Vou abrir o Zoho API Console.")
    info("Clique em 'Add Client' → 'Server-based Applications'")
    info("Preencha:")
    info("  Client Name: Conversor Reunioes (ou qualquer nome)")
    info("  Homepage URL: http://localhost")
    info("  Redirect URI: http://localhost:8080")
    aguardar("ENTER para abrir o Zoho API Console...")
    webbrowser.open("https://api-console.zoho.com/")
    aguardar("Crie o app e pressione ENTER para continuar...")

    passo(2, "Informar Client ID e Client Secret")
    print()
    client_id = input("  Cole aqui o CLIENT ID: ").strip()
    client_secret = input("  Cole aqui o CLIENT SECRET: ").strip()

    if not client_id or not client_secret:
        erro("Client ID ou Secret não informados. Configuração cancelada.")
        return False

    passo(3, "Autorizar acesso às gravações")
    info("Vou abrir o navegador para você autorizar o acesso.")
    info("Após autorizar, você será redirecionado para localhost:8080")
    info("(que está sendo monitorado automaticamente)")

    auth_url = (
        "https://accounts.zoho.com/oauth/v2/auth"
        f"?scope=ZohoMeeting.recording.READ"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&response_type=code"
        f"&redirect_uri=http://localhost:8080"
        f"&access_type=offline"
    )

    _iniciar_servidor_local(8080)
    aguardar("ENTER para abrir a página de autorização no navegador...")
    webbrowser.open(auth_url)

    print("  Aguardando autorização no navegador", end="")
    for _ in range(120):
        if _oauth_code["value"]:
            break
        time.sleep(1)
        print(".", end="", flush=True)
    print()

    if not _oauth_code["value"]:
        erro("Tempo esgotado. Tente novamente.")
        return False

    ok(f"Código de autorização recebido!")

    passo(4, "Trocando código pelo Refresh Token")
    import requests
    try:
        resp = requests.post(
            "https://accounts.zoho.com/oauth/v2/token",
            data={
                "grant_type": "authorization_code",
                "code": _oauth_code["value"],
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": "http://localhost:8080",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "refresh_token" not in data:
            erro(f"Resposta inesperada do Zoho: {data}")
            return False

        refresh_token = data["refresh_token"]
        ok("Refresh token obtido com sucesso!")

        _salvar_env({
            "ZOHO_CLIENT_ID": client_id,
            "ZOHO_CLIENT_SECRET": client_secret,
            "ZOHO_REFRESH_TOKEN": refresh_token,
        })

        ok("Zoho Meetings configurado com sucesso!")
        return True

    except Exception as e:
        erro(f"Erro ao obter refresh token: {e}")
        return False


# ──────────────────────────────────────────────
# CONFIGURAÇÃO DO WHISPER
# ──────────────────────────────────────────────

def configurar_whisper():
    titulo("CONFIGURAÇÃO — WHISPER (Transcrição)")

    print("""
  Modelos disponíveis:
    [1] tiny   — Muito rápido, precisão básica
    [2] base   — Rápido, boa precisão          (padrão recomendado)
    [3] small  — Médio, muito boa precisão     (melhor para pt-BR)
    [4] medium — Lento, ótima precisão
    [5] large  — Muito lento, máxima precisão
    """)

    opcao = input("  Escolha o modelo [1-5, ENTER=base]: ").strip()
    modelos = {"1": "tiny", "2": "base", "3": "small", "4": "medium", "5": "large"}
    modelo = modelos.get(opcao, "base")

    print("""
  Idioma da transcrição:
    [1] pt — Português (recomendado)
    [2] en — Inglês
    [3] auto — Detectar automaticamente
    """)

    opcao_idioma = input("  Escolha o idioma [1-3, ENTER=pt]: ").strip()
    idiomas = {"1": "pt", "2": "en", "3": "auto"}
    idioma = idiomas.get(opcao_idioma, "pt")

    _salvar_env({"WHISPER_MODEL": modelo, "WHISPER_LANGUAGE": idioma})
    ok(f"Modelo: {modelo} | Idioma: {idioma}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    titulo("ASSISTENTE DE CONFIGURAÇÃO — CONVERSOR DE REUNIÕES")
    print("""
  Este assistente irá configurar:
    - Google Meet (via Google Drive API)
    - Zoho Meetings API
    - Modelo Whisper para transcrição
    """)

    # Garante .env base
    if not Path(".env").exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            ok(".env criado a partir do .env.example")

    configurar_whisper()

    print("\n" + "-" * 55)
    resp_google = input("\nConfigurar Google Meet agora? [S/n]: ").strip().lower()
    google_ok = False
    if resp_google != "n":
        google_ok = configurar_google()

    print("\n" + "-" * 55)
    resp_zoho = input("\nConfigurar Zoho Meetings agora? [S/n]: ").strip().lower()
    zoho_ok = False
    if resp_zoho != "n":
        zoho_ok = configurar_zoho()

    titulo("CONFIGURAÇÃO CONCLUÍDA")
    print(f"  Google Meet : {'OK' if google_ok else 'Pendente'}")
    print(f"  Zoho Meetings: {'OK' if zoho_ok else 'Pendente'}")
    print()
    info("Para iniciar o conversor, execute:")
    info("  python main.py")
    print()


if __name__ == "__main__":
    main()
