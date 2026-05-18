import requests
from pathlib import Path
from datetime import datetime, timedelta

import config

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_API_BASE = "https://meeting.zoho.com/api/v2"

_access_token_cache: dict = {"token": None, "expires_at": None}


def _obter_access_token() -> str:
    """Obtém access token usando o refresh token do Zoho."""
    cache = _access_token_cache
    if cache["token"] and cache["expires_at"] and datetime.now() < cache["expires_at"]:
        return cache["token"]

    if not config.ZOHO_CLIENT_ID or not config.ZOHO_REFRESH_TOKEN:
        raise ValueError(
            "Credenciais Zoho não configuradas no .env.\n"
            "Defina ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET e ZOHO_REFRESH_TOKEN."
        )

    resp = requests.post(
        ZOHO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": config.ZOHO_CLIENT_ID,
            "client_secret": config.ZOHO_CLIENT_SECRET,
            "refresh_token": config.ZOHO_REFRESH_TOKEN,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Erro ao obter token Zoho: {data}")

    cache["token"] = data["access_token"]
    cache["expires_at"] = datetime.now() + timedelta(seconds=data.get("expires_in", 3600) - 60)
    return cache["token"]


def _headers() -> dict:
    return {"Authorization": f"Zoho-oauthtoken {_obter_access_token()}"}


def listar_gravacoes(max_resultados: int = 50) -> list[dict]:
    """Lista gravações de reuniões do Zoho Meetings."""
    resp = requests.get(
        f"{ZOHO_API_BASE}/recordings.json",
        headers=_headers(),
        params={"page_size": max_resultados},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    gravacoes = []
    for item in data.get("recordings", []):
        gravacoes.append({
            "id": item.get("recording_id"),
            "name": f"{item.get('topic', 'reuniao')}_{item.get('start_time', '')}.mp4",
            "download_url": item.get("download_url"),
            "size": item.get("file_size"),
            "createdTime": item.get("start_time"),
            "mimeType": "video/mp4",
        })
    return gravacoes


def baixar_arquivo(arquivo: dict, pasta_destino: str) -> Path:
    """Baixa uma gravação do Zoho para a pasta local."""
    Path(pasta_destino).mkdir(parents=True, exist_ok=True)
    destino = Path(pasta_destino) / arquivo["name"]

    if destino.exists():
        print(f"  [cache] Já existe: {destino.name}")
        return destino

    url = arquivo.get("download_url")
    if not url:
        raise ValueError(f"URL de download não encontrada para '{arquivo['name']}'")

    print(f"  Baixando: {arquivo['name']}...")
    with requests.get(url, headers=_headers(), stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        baixado = 0
        with open(destino, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                baixado += len(chunk)
                if total:
                    pct = int(baixado / total * 100)
                    print(f"    {pct}%", end="\r")

    print(f"  Salvo em: {destino}")
    return destino
