import streamlit as st
import streamlit.components.v1 as components
import tempfile
import os
from pathlib import Path
from datetime import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Gravador de Reuniões",
    page_icon="🎙",
    layout="centered",
)

# ── CSS dark ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0e0e0e; }
[data-testid="stHeader"] { background: #0e0e0e; }
section[data-testid="stSidebar"] { background: #181818; }
h1, h2, h3, label, p, div { color: #f1f5f9 !important; }
.stButton > button {
    background: #6366f1;
    color: #f1f5f9;
    border: none;
    border-radius: 8px;
    padding: 0.5rem 1.5rem;
    font-weight: 600;
}
.stButton > button:hover { background: #4f46e5; }
.stSelectbox > div { background: #222; }
textarea { background: #222 !important; color: #f1f5f9 !important; }
.resumo-box {
    background: #1a1a2e;
    border-left: 4px solid #6366f1;
    padding: 1rem 1.2rem;
    border-radius: 8px;
    white-space: pre-wrap;
    font-family: 'Consolas', monospace;
    font-size: 0.9rem;
    color: #f1f5f9;
}
</style>
""", unsafe_allow_html=True)


# ── Mini servidor HTTP para receber áudio capturado pelo browser ──────────────
CAPTURE_PORT = 8765
_cap_buf: dict = {}   # buffer módulo-nível; app local single-user


class _Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _cap_buf["bytes"] = self.rfile.read(n)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *_):
        pass


if not st.session_state.get("_cap_srv_started"):
    try:
        _srv = HTTPServer(("127.0.0.1", CAPTURE_PORT), _Handler)
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
    except OSError:
        pass  # porta já em uso — servidor já rodando
    st.session_state["_cap_srv_started"] = True


# ── Model cache ───────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Carregando modelo Whisper...")
def load_model(name: str):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8")


# ── Transcription ─────────────────────────────────────────────────────────────
def transcrever(audio_bytes: bytes, label: str, model, suffix=".wav") -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        segs_raw, _ = model.transcribe(
            tmp,
            language="pt",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt="Transcrição em português brasileiro.",
        )
        return [
            {"start": seg.start, "source": label, "text": seg.text.strip()}
            for seg in segs_raw if seg.text.strip()
        ]
    finally:
        os.unlink(tmp)


def formatar(segments: list[dict]) -> str:
    segments.sort(key=lambda x: x["start"])
    return "\n".join(
        f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['source']}: {s['text']}"
        for s in segments
    ) or "(sem fala detectada)"


# ── Summary ───────────────────────────────────────────────────────────────────
def gerar_resumo(transcricao: str, api_key: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Você é um assistente especializado em resumos de reuniões corporativas "
                "em português brasileiro.\n\n"
                "Analise a transcrição abaixo e gere um resumo estruturado com:\n"
                "**Participantes identificados** (se mencionados)\n"
                "**Tópicos discutidos**\n"
                "**Decisões tomadas**\n"
                "**Próximos passos / ações**\n\n"
                f"Transcrição:\n{transcricao}"
            ),
        }],
    )
    return resp.choices[0].message.content


# ── Componente de captura de tela / guia ──────────────────────────────────────
_CAPTURE_HTML = f"""
<div style="font-family:sans-serif;padding:4px 0;">
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
    <button id="btnStart" onclick="startCapture()"
      style="background:#6366f1;color:#fff;border:none;border-radius:8px;
             padding:7px 14px;font-weight:600;cursor:pointer;font-size:0.85rem;">
      🖥 Compartilhar Tela / Guia
    </button>
    <button id="btnStop" onclick="stopCapture()" disabled
      style="background:#444;color:#888;border:none;border-radius:8px;
             padding:7px 14px;font-weight:600;cursor:not-allowed;font-size:0.85rem;">
      ⏹ Parar Gravação
    </button>
  </div>
  <p id="cap-status"
    style="color:#a5b4fc;margin:6px 0 0;font-size:0.8rem;min-height:1.2em;">
    Pronto. Clique em "Compartilhar" e escolha a guia ou a tela inteira.
  </p>
</div>
<script>
var recorder=null, chunks=[], stream=null;

async function startCapture(){{
  try{{
    stream = await navigator.mediaDevices.getDisplayMedia({{
      video: true,
      audio: {{ echoCancellation:false, noiseSuppression:false, sampleRate:44100 }}
    }});
    // descarta trilhas de vídeo — só precisamos do áudio
    stream.getVideoTracks().forEach(function(t){{ t.stop(); }});
    var audioTracks = stream.getAudioTracks();
    if(!audioTracks.length){{
      setStatus('⚠️ Nenhum áudio detectado. Marque "Compartilhar áudio" na janela de seleção.','#fbbf24');
      return;
    }}
    var audioStream = new MediaStream(audioTracks);
    var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
               ? 'audio/webm;codecs=opus' : 'audio/webm';
    recorder = new MediaRecorder(audioStream, {{mimeType: mime}});
    chunks = [];
    recorder.ondataavailable = function(e){{ if(e.data.size) chunks.push(e.data); }};
    recorder.onstop = sendAudio;
    recorder.start(1000);
    btnState(true);
    setStatus('🔴 Gravando... clique em Parar quando terminar.','#f87171');
  }}catch(e){{
    setStatus('Erro: ' + e.message,'#f87171');
  }}
}}

function stopCapture(){{
  if(recorder && recorder.state !== 'inactive') recorder.stop();
  if(stream) stream.getTracks().forEach(function(t){{ t.stop(); }});
  setStatus('Enviando áudio...','#a5b4fc');
}}

async function sendAudio(){{
  var blob = new Blob(chunks, {{type:'audio/webm'}});
  try{{
    var r = await fetch('http://127.0.0.1:{CAPTURE_PORT}', {{
      method: 'POST',
      headers: {{'Content-Type':'audio/webm'}},
      body: blob
    }});
    if(r.ok){{
      setStatus('✅ Áudio capturado! Pressione "▶ Transcrever" abaixo.','#4ade80');
    }}else{{
      setStatus('Erro no servidor local: ' + r.status,'#f87171');
    }}
  }}catch(e){{
    setStatus('Falha ao enviar áudio: ' + e.message,'#f87171');
  }}
  btnState(false);
}}

function btnState(recording){{
  var s = document.getElementById('btnStart');
  var p = document.getElementById('btnStop');
  s.disabled = recording;
  p.disabled = !recording;
  p.style.background = recording ? '#ef4444' : '#444';
  p.style.color      = recording ? '#fff'    : '#888';
  p.style.cursor     = recording ? 'pointer' : 'not-allowed';
}}

function setStatus(msg, color){{
  var el = document.getElementById('cap-status');
  el.textContent = msg;
  el.style.color  = color || '#a5b4fc';
}}
</script>
"""


# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🎙 Gravador de Reuniões")
st.caption("Transcrição automática + resumo com IA")
st.divider()

# Sidebar — configurações
with st.sidebar:
    st.header("⚙ Configurações")
    modelo = st.selectbox("Modelo Whisper", ["tiny", "base", "small", "medium", "large"], index=1)

    groq_key = st.secrets.get("GROQ_API_KEY", "") if hasattr(st, "secrets") else ""
    if not groq_key:
        groq_key = st.text_input("Chave Groq API", type="password",
                                  help="Gratuita em console.groq.com")
    else:
        st.success("Chave Groq configurada ✓")

    st.divider()
    st.caption("Os áudios são processados localmente e não são armazenados.")

# Carrega modelo
model = load_model(modelo)

# Entrada de áudio
col1, col2 = st.columns(2)

with col1:
    st.subheader("🎤 Microfone")
    mic_audio = st.audio_input("Gravar pelo microfone")
    mic_file  = st.file_uploader("ou enviar arquivo", type=["wav","mp3","mp4","m4a","ogg","webm"],
                                  key="mic_file")

with col2:
    st.subheader("🖥 Tela / Guia do Navegador")
    components.html(_CAPTURE_HTML, height=90)
    if _cap_buf.get("bytes"):
        st.success("Áudio da tela capturado e pronto.", icon="✅")
    sys_file = st.file_uploader("ou enviar arquivo de áudio",
                                 type=["wav","mp3","mp4","m4a","ogg","webm"],
                                 key="sys_file")
    st.caption("Na janela do Chrome, marque 'Compartilhar áudio da guia'.")

st.divider()

# Transcrever
if st.button("▶ Transcrever", use_container_width=True):
    segments = []

    mic_bytes = None
    if mic_audio:
        mic_bytes = mic_audio.getvalue()
    elif mic_file:
        mic_bytes = mic_file.read()

    sys_bytes = None
    if _cap_buf.get("bytes"):
        sys_bytes = _cap_buf["bytes"]
    elif sys_file:
        sys_bytes = sys_file.read()

    if not mic_bytes and not sys_bytes:
        st.warning("Forneça ao menos um áudio para transcrever.")
    else:
        with st.spinner("Transcrevendo..."):
            if mic_bytes:
                segments += transcrever(mic_bytes, "Microfone", model)
            if sys_bytes:
                segments += transcrever(sys_bytes, "Tela/Sistema", model, suffix=".webm")

        texto = formatar(segments)
        st.session_state["transcricao"] = texto
        st.session_state["resumo"] = ""
        _cap_buf.clear()

# Exibe transcrição
if "transcricao" in st.session_state and st.session_state["transcricao"]:
    st.subheader("📝 Transcrição")
    texto_editado = st.text_area("", value=st.session_state["transcricao"], height=220,
                                  label_visibility="collapsed")

    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button("⬇ Baixar TXT", texto_editado,
                           file_name=f"transcricao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with col_b:
        if st.button("✨ Gerar Resumo com IA", use_container_width=True):
            if not groq_key:
                st.error("Configure a chave Groq na barra lateral.")
            else:
                with st.spinner("Gerando resumo..."):
                    try:
                        st.session_state["resumo"] = gerar_resumo(texto_editado, groq_key)
                    except Exception as e:
                        st.error(f"Erro: {e}")

# Exibe resumo
if st.session_state.get("resumo"):
    st.subheader("🤖 Resumo da Reunião")
    st.markdown(
        f'<div class="resumo-box">{st.session_state["resumo"]}</div>',
        unsafe_allow_html=True,
    )
    st.download_button("⬇ Baixar Resumo",
                       st.session_state["resumo"],
                       file_name=f"resumo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
