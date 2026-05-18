# Configuração do Conversor de Reuniões

## 1. Pré-requisitos

### Python 3.9+
Verifique com: `python --version`

### FFmpeg
Baixe em https://ffmpeg.org/download.html e adicione ao PATH do Windows.
Verifique com: `ffmpeg -version`

### Instalar dependências Python
```
pip install -r requirements.txt
```

---

## 2. Configurar arquivo .env

Copie `.env.example` para `.env` e preencha:

```
copy .env.example .env
```

---

## 3. Google Meet (Google Drive)

### Passo a passo:
1. Acesse https://console.cloud.google.com/
2. Crie um projeto ou selecione um existente
3. Ative a **Google Drive API**: APIs e Serviços → Biblioteca → busque "Drive API"
4. Crie credenciais: APIs e Serviços → Credenciais → Criar Credenciais → **ID do cliente OAuth 2.0**
   - Tipo: **Aplicativo para computador**
5. Baixe o JSON e salve como `credentials.json` na pasta do projeto
6. Na primeira execução, um navegador abrirá para autenticação — faça login com a conta Google que tem as gravações

> As gravações do Google Meet ficam automaticamente no Google Drive do organizador.

---

## 4. Zoho Meetings

### Passo a passo:
1. Acesse https://api-console.zoho.com/
2. Clique em **Add Client** → **Server-based Applications**
3. Anote o **Client ID** e **Client Secret**
4. Para gerar o **Refresh Token**:
   - Acesse: `https://accounts.zoho.com/oauth/v2/auth?scope=ZohoMeeting.recording.READ&client_id=SEU_CLIENT_ID&response_type=code&redirect_uri=https://localhost&access_type=offline`
   - Faça login e autorize
   - Copie o `code` da URL de redirect
   - Troque o code pelo refresh token:
     ```
     POST https://accounts.zoho.com/oauth/v2/token
     grant_type=authorization_code&code=SEU_CODE&client_id=SEU_CLIENT_ID&client_secret=SEU_SECRET&redirect_uri=https://localhost
     ```
5. Preencha `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET` e `ZOHO_REFRESH_TOKEN` no `.env`

---

## 5. Executar

```
python main.py
```

### Modelos Whisper disponíveis (configure no .env):
| Modelo  | Velocidade | Precisão | VRAM   |
|---------|-----------|----------|--------|
| tiny    | Muito rápido | Básica | ~1 GB |
| base    | Rápido     | Boa      | ~1 GB |
| small   | Médio      | Muito boa| ~2 GB |
| medium  | Lento      | Ótima    | ~5 GB |
| large   | Muito lento| Máxima   | ~10 GB|

Para português, `small` já tem excelente qualidade.

---

## Estrutura de pastas gerada

```
convert/
├── downloads/       ← arquivos de áudio baixados (temporário)
└── transcricoes/    ← arquivos TXT com as transcrições
```
