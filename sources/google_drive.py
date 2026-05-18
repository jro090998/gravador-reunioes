import os
import io
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_FILE = "google_token.json"

# MIME types de gravações de reuniões
RECORDING_MIMETYPES = [
    "video/mp4",
    "audio/mp4",
    "audio/mpeg",
    "audio/x-m4a",
    "video/quicktime",
    "audio/wav",
]


def _autenticar() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Arquivo '{config.GOOGLE_CREDENTIALS_FILE}' não encontrado.\n"
                    "Baixe o credentials.json no Google Cloud Console e coloque na pasta do projeto."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def listar_gravacoes(max_resultados: int = 50) -> list[dict]:
    """Lista gravações de reuniões no Google Drive."""
    creds = _autenticar()
    service = build("drive", "v3", credentials=creds)

    # Monta query para buscar arquivos de áudio/vídeo de reuniões
    mime_query = " or ".join(f"mimeType='{m}'" for m in RECORDING_MIMETYPES)
    query = f"({mime_query}) and trashed=false"

    results = (
        service.files()
        .list(
            q=query,
            pageSize=max_resultados,
            fields="files(id, name, size, createdTime, mimeType)",
            orderBy="createdTime desc",
        )
        .execute()
    )

    return results.get("files", [])


def baixar_arquivo(arquivo: dict, pasta_destino: str) -> Path:
    """Baixa um arquivo do Google Drive para a pasta local."""
    creds = _autenticar()
    service = build("drive", "v3", credentials=creds)

    Path(pasta_destino).mkdir(parents=True, exist_ok=True)
    destino = Path(pasta_destino) / arquivo["name"]

    if destino.exists():
        print(f"  [cache] Já existe: {destino.name}")
        return destino

    request = service.files().get_media(fileId=arquivo["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    print(f"  Baixando: {arquivo['name']}...")
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"    {int(status.progress() * 100)}%", end="\r")

    destino.write_bytes(buffer.getvalue())
    print(f"  Salvo em: {destino}")
    return destino
