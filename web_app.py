import streamlit as st
import tempfile
import os
from pathlib import Path
from datetime import datetime

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


# ── Model cache ───────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Carregando modelo Whisper...")
def load_model(name: str):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8")


# ── Transcription ─────────────────────────────────────────────────────────────
def transcrever(audio_bytes: bytes, label: str, model) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
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

# Entrada de áudio
col1, col2 = st.columns(2)

with col1:
    st.subheader("🎤 Microfone")
    mic_audio = st.audio_input("Gravar pelo microfone")
    mic_file  = st.file_uploader("ou enviar arquivo", type=["wav","mp3","mp4","m4a","ogg"],
                                  key="mic_file")

with col2:
    st.subheader("🔊 Navegador / Sistema")
    sys_file = st.file_uploader("Enviar gravação do sistema", type=["wav","mp3","mp4","m4a","ogg"],
                                 key="sys_file")
    st.caption("Grave o áudio do sistema separadamente e envie aqui.")

st.divider()

# Transcrever
if st.button("▶ Transcrever", use_container_width=True):
    segments = []

    mic_bytes = None
    if mic_audio:
        mic_bytes = mic_audio.getvalue()
    elif mic_file:
        mic_bytes = mic_file.read()

    sys_bytes = sys_file.read() if sys_file else None

    if not mic_bytes and not sys_bytes:
        st.warning("Forneça ao menos um áudio para transcrever.")
    else:
        with st.spinner("Transcrevendo..."):
            if mic_bytes:
                segments += transcrever(mic_bytes, "Microfone", model)
            if sys_bytes:
                segments += transcrever(sys_bytes, "Navegador", model)

        texto = formatar(segments)
        st.session_state["transcricao"] = texto
        st.session_state["resumo"] = ""

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
