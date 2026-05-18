"""Gravador de Reuniões — servidor Flask"""

import os, tempfile, smtplib, subprocess
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_SMTP = os.getenv("EMAIL_SMTP", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".ts", ".mpeg", ".mpg", ".webm"}

_model = None

def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
    return _model

def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def extract_audio(path: str) -> str:
    out = path + "_audio.wav"
    subprocess.run(
        [ffmpeg_exe(), "-i", path, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", out, "-y", "-loglevel", "error"],
        check=True,
    )
    return out

def transcrever(path: str, label: str) -> list[dict]:
    ext = Path(path).suffix.lower()
    audio_path = extract_audio(path) if ext in VIDEO_EXTS else path
    try:
        segs, _ = get_model().transcribe(
            audio_path, language="pt", beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt="Transcrição em português brasileiro.",
        )
        return [{"start": s.start, "source": label, "text": s.text.strip()}
                for s in segs if s.text.strip()]
    finally:
        if audio_path != path:
            try: os.unlink(audio_path)
            except: pass

@app.route("/")
def index():
    resp = app.make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        segments, tmp_files = [], []
        for field, label in [("mic", "Microfone"), ("sys", "Navegador")]:
            f = request.files.get(field)
            if f and f.filename:
                suffix = Path(f.filename).suffix or ".webm"
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                f.save(tmp.name)
                tmp_files.append(tmp.name)
                segments += transcrever(tmp.name, label)
        for p in tmp_files:
            try: os.unlink(p)
            except: pass
        segments.sort(key=lambda x: x["start"])
        lines = [f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['source']}: {s['text']}"
                 for s in segments]
        return jsonify({"ok": True, "text": "\n".join(lines) or "(sem fala detectada)"})
    except Exception:
        import traceback
        return jsonify({"ok": False, "error": traceback.format_exc()}), 500

@app.route("/summarize", methods=["POST"])
def summarize():
    try:
        text = request.get_json().get("text", "").strip()
        if not text:
            return jsonify({"ok": False, "error": "Transcrição vazia"}), 400
        from groq import Groq
        resp = Groq(api_key=GROQ_API_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile", max_tokens=1024,
            messages=[{"role": "user", "content": (
                "Você é um assistente especializado em resumos de reuniões corporativas "
                "em português brasileiro.\n\n"
                "Analise a transcrição e gere um resumo estruturado com:\n"
                "**Participantes identificados** (se mencionados)\n"
                "**Tópicos discutidos**\n"
                "**Decisões tomadas**\n"
                "**Próximos passos / ações**\n\n"
                f"Transcrição:\n{text}"
            )}],
        )
        return jsonify({"ok": True, "summary": resp.choices[0].message.content})
    except Exception:
        import traceback
        return jsonify({"ok": False, "error": traceback.format_exc()}), 500

@app.route("/send-email", methods=["POST"])
def send_email():
    try:
        data = request.get_json()
        to, subject, body = data.get("to","").strip(), data.get("subject",""), data.get("body","")
        if not to:
            return jsonify({"ok": False, "error": "Destinatário não informado"}), 400
        if not EMAIL_FROM or not EMAIL_PASS:
            return jsonify({"ok": False, "error": "EMAIL_FROM / EMAIL_PASS não configurados"}), 400
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT) as s:
            s.starttls(); s.login(EMAIL_FROM, EMAIL_PASS); s.send_message(msg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    print("Servidor iniciado em http://localhost:5000")
    get_model()
    app.run(host="0.0.0.0", port=5000, debug=False)
