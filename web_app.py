import streamlit as st
import tempfile
import os
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


# ── Página de gravação servida pelo servidor local ────────────────────────────
_RECORDER_PAGE = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Gravador de Reunião</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:#0e0e0e;color:#f1f5f9;font-family:'Segoe UI',sans-serif;
         min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}
    .card{background:#181818;border-radius:16px;padding:2rem;max-width:480px;width:100%;
          box-shadow:0 8px 32px #0006;display:flex;flex-direction:column;gap:1.25rem}
    h1{font-size:1.4rem;font-weight:700;color:#f1f5f9}
    .subtitle{font-size:0.85rem;color:#94a3b8}
    .btns{display:flex;gap:10px;flex-wrap:wrap}
    button{border:none;border-radius:10px;padding:11px 20px;font-size:0.9rem;
           font-weight:600;cursor:pointer;transition:background .15s}
    #btnStart{background:#6366f1;color:#fff}
    #btnStart:hover:not(:disabled){background:#4f46e5}
    #btnStop{background:#333;color:#666;cursor:not-allowed}
    #btnStop.active{background:#ef4444;color:#fff;cursor:pointer}
    #btnStop.active:hover{background:#dc2626}
    button:disabled{opacity:.5;cursor:not-allowed}
    .status{font-size:0.85rem;padding:10px 14px;border-radius:8px;
            background:#111;border-left:3px solid #6366f1;color:#a5b4fc;min-height:42px}
    .status.ok{border-color:#22c55e;color:#4ade80}
    .status.err{border-color:#ef4444;color:#f87171}
    .status.rec{border-color:#ef4444;color:#f87171}
    .status.warn{border-color:#f59e0b;color:#fbbf24}
    .hint{font-size:0.78rem;color:#64748b;line-height:1.5}
    .hint b{color:#94a3b8}
  </style>
</head>
<body>
<div class="card">
  <div>
    <h1>🎙🖥 Gravador de Reunião</h1>
    <p class="subtitle">Captura microfone + áudio do PC simultaneamente</p>
  </div>
  <div class="btns">
    <button id="btnStart" onclick="startRec()">▶ Iniciar Gravação</button>
    <button id="btnStop" onclick="stopRec()">⏹ Parar</button>
  </div>
  <div id="status" class="status">Pronto. Clique em Iniciar para começar.</div>
  <p class="hint">
    Na janela de compartilhamento:<br>
    • Guia → selecione a guia e marque <b>"Compartilhar áudio da guia"</b><br>
    • PC inteiro → selecione <b>"Tela inteira"</b> e marque <b>"Compartilhar áudio do sistema"</b>
  </p>
</div>
<script>
var recorder, chunks=[], sources;

async function startRec(){
  setStatus('Aguardando permissões...','');
  try{
    var mic=null;
    try{ mic=await navigator.mediaDevices.getUserMedia({audio:true,video:false}); }
    catch(e){ setStatus('Microfone negado: '+e.message,'err'); }

    var disp=null;
    try{
      disp=await navigator.mediaDevices.getDisplayMedia({
        video:true, audio:{echoCancellation:false,noiseSuppression:false,sampleRate:44100}
      });
      disp.getVideoTracks().forEach(t=>t.stop());
    }catch(e){ setStatus('Compartilhamento cancelado: '+e.message,'warn'); }

    if(!mic && !disp){ setStatus('Nenhuma fonte de áudio.','err'); return; }

    var ctx=new AudioContext(), dest=ctx.createMediaStreamDestination();
    if(mic) ctx.createMediaStreamSource(mic).connect(dest);
    var sysOk=false;
    if(disp){
      var st=disp.getAudioTracks();
      if(st.length){ ctx.createMediaStreamSource(new MediaStream(st)).connect(dest); sysOk=true; }
      else setStatus('Áudio do sistema não detectado — marque "Compartilhar áudio" na seleção.','warn');
    }

    var mime=MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':'audio/webm';
    recorder=new MediaRecorder(dest.stream,{mimeType:mime});
    chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=send;
    recorder.start(1000);
    sources={mic,disp,ctx};

    document.getElementById('btnStart').disabled=true;
    var stop=document.getElementById('btnStop');
    stop.classList.add('active');

    var label=[mic?'microfone':null,sysOk?'áudio do PC':null].filter(Boolean).join(' + ');
    setStatus('🔴 Gravando: '+label,'rec');
  }catch(e){ setStatus('Erro: '+e.message,'err'); }
}

function stopRec(){
  if(recorder&&recorder.state!=='inactive') recorder.stop();
  if(sources){
    if(sources.mic) sources.mic.getTracks().forEach(t=>t.stop());
    if(sources.disp) sources.disp.getTracks().forEach(t=>t.stop());
    if(sources.ctx) sources.ctx.close();
  }
  document.getElementById('btnStop').classList.remove('active');
  setStatus('Enviando áudio para o Streamlit...','');
}

async function send(){
  var blob=new Blob(chunks,{type:'audio/webm'});
  try{
    var r=await fetch('/audio',{method:'POST',headers:{'Content-Type':'audio/webm'},body:blob});
    if(r.ok){
      setStatus('✅ Gravação enviada! Volte ao Streamlit e clique em ▶ Transcrever.','ok');
      document.getElementById('btnStart').disabled=false;
    } else setStatus('Erro no servidor: '+r.status,'err');
  }catch(e){ setStatus('Falha ao enviar: '+e.message,'err'); }
}

function setStatus(msg,cls){
  var el=document.getElementById('status');
  el.textContent=msg;
  el.className='status'+(cls?' '+cls:'');
}
</script>
</body>
</html>"""

# ── Servidor HTTP local ───────────────────────────────────────────────────────
CAPTURE_PORT = 8765
_cap_buf: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = _RECORDER_PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == "/audio":
            n = int(self.headers.get("Content-Length", 0))
            _cap_buf["bytes"] = self.rfile.read(n)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404)
            self.end_headers()

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
        pass  # porta já em uso
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

# ── Captura de voz + áudio do PC ─────────────────────────────────────────────
st.subheader("🎙🖥 Gravar Voz + Áudio do PC")

if _cap_buf.get("bytes"):
    st.success("Gravação recebida e pronta para transcrição.", icon="✅")
    if st.button("🗑 Limpar gravação", key="clear_cap"):
        _cap_buf.clear()
        st.rerun()
else:
    st.link_button(
        "▶ Abrir Gravador (nova aba)",
        url=f"http://localhost:{CAPTURE_PORT}",
        use_container_width=True,
    )
    st.caption("Abre uma página dedicada onde mic + áudio do PC funcionam corretamente. "
               "Após gravar, volte aqui e clique em **▶ Transcrever**.")

st.divider()

# ── Entrada de áudio por arquivo ──────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("🎤 Microfone")
    mic_audio = st.audio_input("Gravar pelo microfone")
    mic_file  = st.file_uploader("ou enviar arquivo", type=["wav","mp3","mp4","m4a","ogg","webm"],
                                  key="mic_file")

with col2:
    st.subheader("🔊 Áudio do Sistema")
    sys_file = st.file_uploader("Enviar gravação do sistema",
                                 type=["wav","mp3","mp4","m4a","ogg","webm"],
                                 key="sys_file")
    st.caption("Alternativa: envie um arquivo de áudio gravado separadamente.")

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
                segments += transcrever(sys_bytes, "Gravação", model, suffix=".webm")

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
