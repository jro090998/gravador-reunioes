#!/usr/bin/env python3
"""Gravador com transcrição por fonte (Microfone / Navegador) — faster-whisper + dark UI."""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import pyaudiowpatch as pyaudio
import numpy as np
from scipy.signal import resample_poly
from math import gcd
import threading
import wave
from datetime import datetime
from pathlib import Path
import os
import json
import sys

# Quando rodando como .exe, salva config ao lado do executável
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(sys.executable).parent
else:
    CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "GravadorReunioes"

CONFIG_FILE = CONFIG_DIR / "settings.json"
OUTPUT_DIR  = Path("transcricoes")
MODELS      = ["tiny", "base", "small", "medium", "large"]
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
WHISPER_RATE = 16000

# ── Paleta dark ───────────────────────────────────────────────────────────────
BG      = "#0e0e0e"
SURFACE = "#181818"
CARD    = "#222222"
ACCENT  = "#6366f1"
DANGER  = "#ef4444"
GREEN   = "#22c55e"
TEXT    = "#f1f5f9"
MUTED   = "#6b7280"
FONT    = ("Segoe UI", 10)
FONT_B  = ("Segoe UI", 10, "bold")
MONO    = ("Consolas", 10)


# ── Device helpers ────────────────────────────────────────────────────────────

def _input_devices(pa: pyaudio.PyAudio) -> list[dict]:
    devs = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
            devs.append({"index": i, "name": d["name"],
                         "channels": int(d["maxInputChannels"]),
                         "rate": int(d["defaultSampleRate"])})
    return devs


def _loopback_devices(pa: pyaudio.PyAudio) -> list[dict]:
    devs = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("isLoopbackDevice") and d["maxInputChannels"] > 0:
            devs.append({"index": i,
                         "name": d["name"].replace(" [Loopback]", ""),
                         "channels": int(d["maxInputChannels"]),
                         "rate": int(d["defaultSampleRate"])})
    return devs


def _wasapi_defaults(pa: pyaudio.PyAudio) -> tuple[int, int]:
    try:
        w = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        return w["defaultInputDevice"], w["defaultOutputDevice"]
    except Exception:
        return 0, 0


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _to_mono_f32(data: bytes, channels: int) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        arr = arr[: len(arr) - len(arr) % channels].reshape(-1, channels).mean(axis=1)
    return arr


def _resample(arr: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return arr
    g = gcd(src, dst)
    return resample_poly(arr, dst // g, src // g)


def _save_wav(arr: np.ndarray, rate: int, path: Path):
    pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm.tobytes())


# ── Video helpers ─────────────────────────────────────────────────────────────

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".ts", ".mpeg", ".mpg", ".webm"}

def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def _extract_audio(video_path: str) -> str:
    import subprocess
    out = video_path + "_audio.wav"
    subprocess.run(
        [_ffmpeg_exe(), "-i", video_path, "-vn",
         "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", out, "-y", "-loglevel", "error"],
        check=True,
    )
    return out


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Gravador de Reunioes")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self.recording = False
        self.model = None
        self.pa = pyaudio.PyAudio()
        self.timer_id = None
        self.elapsed = 0
        self.config = _load_config()

        self.in_devs = _input_devices(self.pa)
        self.lb_devs = _loopback_devices(self.pa)

        self._apply_styles()
        self._build_ui()
        self._load_model_async()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TCombobox",
                    fieldbackground=CARD, background=CARD,
                    foreground=TEXT, selectbackground=ACCENT,
                    selectforeground=TEXT, arrowcolor=MUTED,
                    borderwidth=0, padding=(6, 4))
        s.map("TCombobox",
              fieldbackground=[("readonly", CARD)],
              background=[("readonly", CARD)],
              foreground=[("readonly", TEXT)],
              arrowcolor=[("readonly", MUTED)])

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        default_in, default_out = _wasapi_defaults(self.pa)

        # Header
        hdr = tk.Frame(self.root, bg=SURFACE, pady=14, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Gravador de Reunioes",
                 font=("Segoe UI", 14, "bold"), fg=TEXT, bg=SURFACE).pack(side="left")
        tk.Button(hdr, text="⚙", command=self._open_settings,
                  bg=SURFACE, fg=MUTED, relief="flat",
                  font=("Segoe UI", 14), cursor="hand2", bd=0).pack(side="right", padx=(8, 0))
        self._status_lbl = tk.Label(hdr, text="Carregando...",
                                     font=FONT, fg=MUTED, bg=SURFACE)
        self._status_lbl.pack(side="right")

        body = tk.Frame(self.root, bg=BG, padx=18, pady=14)
        body.pack(fill="both")

        # Modelo
        row = self._row(body, "Modelo Whisper")
        self.model_var = tk.StringVar(value="base")
        self._combo(row, self.model_var, MODELS, 10)
        self._flat_btn(row, "Recarregar", self._load_model_async).pack(side="left", padx=(8, 0))

        # Microfone
        row_mic = self._row(body, "Microfone")
        self.mic_var = tk.StringVar()
        mic_names = [d["name"] for d in self.in_devs]
        self._mic_combo = self._combo(row_mic, self.mic_var, mic_names, 46)
        for i, d in enumerate(self.in_devs):
            if d["index"] == default_in:
                self._mic_combo.current(i)
                break
        else:
            if mic_names:
                self._mic_combo.current(0)

        # Sistema (loopback)
        row_lb = self._row(body, "Sistema (navegador)")
        self.lb_var = tk.StringVar()
        lb_names = [d["name"] for d in self.lb_devs]
        self._lb_combo = self._combo(row_lb, self.lb_var, lb_names, 46)
        if lb_names:
            try:
                out_dev = self.pa.get_device_info_by_index(default_out)
                for i, d in enumerate(self.lb_devs):
                    if d["name"] in out_dev["name"] or out_dev["name"].startswith(d["name"]):
                        self._lb_combo.current(i)
                        break
                else:
                    self._lb_combo.current(0)
            except Exception:
                self._lb_combo.current(0)

        # Botão gravar + timer + arquivo
        rec = tk.Frame(body, bg=BG, pady=18)
        rec.pack()
        self.btn = tk.Button(
            rec, text="  GRAVAR  ", command=self.toggle,
            bg=DANGER, fg=TEXT, font=("Segoe UI", 18, "bold"),
            relief="flat", cursor="hand2", padx=28, pady=14,
            state="disabled",
        )
        self.btn.pack(side="left")
        self.timer_var = tk.StringVar(value="")
        tk.Label(rec, textvariable=self.timer_var,
                 font=("Courier New", 22, "bold"), fg=DANGER,
                 bg=BG, width=6).pack(side="left", padx=18)
        self.file_btn = tk.Button(
            rec, text="  Arquivo  ", command=self._open_file,
            bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold"),
            relief="flat", cursor="hand2", padx=16, pady=14,
            state="disabled",
        )
        self.file_btn.pack(side="left")

        # Transcrição
        tk.Label(body, text="Transcricao", font=FONT_B,
                 fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(2, 4))
        self.text = scrolledtext.ScrolledText(
            body, width=64, height=16, font=MONO,
            bg=CARD, fg=TEXT, insertbackground=TEXT,
            relief="flat", wrap="word", padx=10, pady=8,
        )
        self.text.pack(fill="both")

        btn_row = tk.Frame(body, bg=BG, pady=10)
        btn_row.pack()
        self._flat_btn(btn_row, "Copiar tudo", self._copy).pack(side="left", padx=4)
        self._flat_btn(btn_row, "Limpar", self._clear).pack(side="left", padx=4)
        self.resumo_btn = tk.Button(
            btn_row, text="Resumo IA", command=self._resumo_async,
            bg=ACCENT, fg=TEXT, relief="flat",
            font=FONT_B, cursor="hand2", padx=12, pady=5,
        )
        self.resumo_btn.pack(side="left", padx=4)

    def _row(self, parent: tk.Frame, label: str) -> tk.Frame:
        tk.Label(parent, text=label, font=FONT_B, fg=MUTED,
                 bg=BG, anchor="w").pack(fill="x", pady=(10, 3))
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")
        return row

    def _combo(self, parent: tk.Frame, var: tk.StringVar,
               values: list, width: int) -> ttk.Combobox:
        cb = ttk.Combobox(parent, textvariable=var, values=values,
                          state="readonly", width=width)
        cb.pack(side="left")
        return cb

    def _flat_btn(self, parent: tk.Frame, text: str, cmd) -> tk.Button:
        return tk.Button(parent, text=text, command=cmd,
                         bg=CARD, fg=TEXT, relief="flat",
                         font=FONT, cursor="hand2", padx=12, pady=5)

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = MUTED):
        self._status_lbl.config(text=msg, fg=color)

    # ── Model ─────────────────────────────────────────────────────────────────

    def _load_model_async(self):
        self.btn.config(state="disabled")
        self._set_status(f"Carregando '{self.model_var.get()}'...")
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.model_var.get(), device="cpu", compute_type="int8")
            self.root.after(0, lambda: self._set_status("Pronto", GREEN))
            self.root.after(0, lambda: self.btn.config(state="normal"))
            self.root.after(0, lambda: self.file_btn.config(state="normal"))
        except Exception as e:
            self.root.after(0, lambda: self._set_status(f"Erro: {e}", DANGER))

    # ── Device selection ──────────────────────────────────────────────────────

    def _sel_mic(self) -> dict:
        name = self.mic_var.get()
        return next((d for d in self.in_devs if d["name"] == name), self.in_devs[0])

    def _sel_lb(self) -> dict | None:
        name = self.lb_var.get()
        return next((d for d in self.lb_devs if d["name"] == name),
                    self.lb_devs[0] if self.lb_devs else None)

    # ── Recording ─────────────────────────────────────────────────────────────

    def toggle(self):
        if not self.recording:
            self._start()
        else:
            self._stop()

    def _start(self):
        if not self.model:
            messagebox.showwarning("Aguarde", "Modelo ainda carregando.")
            return

        self.recording = True
        self.mic_chunks: list[bytes] = []
        self.lb_chunks: list[bytes] = []
        self.btn.config(text="  PARAR  ", bg=ACCENT)
        self.elapsed = 0
        self._tick()

        mic = self._sel_mic()
        lb  = self._sel_lb()
        self._mic_info = mic
        self._lb_info  = lb

        self.mic_stream = self.pa.open(
            format=FORMAT, channels=mic["channels"], rate=mic["rate"],
            input=True, input_device_index=mic["index"],
            frames_per_buffer=CHUNK, stream_callback=self._on_mic,
        )
        self.mic_stream.start_stream()

        self.lb_stream = None
        if lb:
            try:
                self.lb_stream = self.pa.open(
                    format=FORMAT, channels=lb["channels"], rate=lb["rate"],
                    input=True, input_device_index=lb["index"],
                    frames_per_buffer=CHUNK, stream_callback=self._on_lb,
                )
                self.lb_stream.start_stream()
                self._set_status(f"Gravando — mic + {lb['name']}", GREEN)
            except Exception as e:
                self.lb_stream = None
                self._set_status(f"Gravando — so mic ({e})", MUTED)
        else:
            self._set_status("Gravando — so microfone", GREEN)

    def _on_mic(self, data, *_):
        self.mic_chunks.append(data)
        return (None, pyaudio.paContinue)

    def _on_lb(self, data, *_):
        self.lb_chunks.append(data)
        return (None, pyaudio.paContinue)

    def _stop(self):
        self.recording = False
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_var.set("")

        self.btn.config(state="disabled", text="  GRAVAR  ", bg=DANGER)
        self._set_status("Transcrevendo...")

        self.mic_stream.stop_stream()
        self.mic_stream.close()
        if self.lb_stream:
            self.lb_stream.stop_stream()
            self.lb_stream.close()

        threading.Thread(
            target=self._transcribe,
            args=(
                b"".join(self.mic_chunks),
                b"".join(self.lb_chunks) if self.lb_chunks else None,
                self._mic_info,
                self._lb_info if self.lb_stream else None,
            ),
            daemon=True,
        ).start()

    # ── Timer ─────────────────────────────────────────────────────────────────

    def _tick(self):
        if not self.recording:
            return
        m, s = divmod(self.elapsed, 60)
        self.timer_var.set(f"{m:02d}:{s:02d}")
        self.elapsed += 1
        self.timer_id = self.root.after(1000, self._tick)

    # ── Transcription ─────────────────────────────────────────────────────────

    def _transcribe_source(self, arr: np.ndarray, label: str) -> list[dict]:
        segs_raw, _ = self.model.transcribe(
            arr,
            language="pt",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt="Transcrição em português brasileiro. Reunião, apresentação, conversa.",
        )
        return [
            {"start": seg.start, "source": label, "text": seg.text.strip()}
            for seg in segs_raw
            if seg.text.strip()
        ]

    def _transcribe(self, mic_data: bytes, lb_data: bytes | None,
                    mic_info: dict, lb_info: dict | None):
        try:
            OUTPUT_DIR.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            mic_arr = _resample(_to_mono_f32(mic_data, mic_info["channels"]),
                                mic_info["rate"], WHISPER_RATE)

            self.root.after(0, lambda: self._set_status("Transcrevendo microfone..."))
            segments = self._transcribe_source(mic_arr, "Microfone")

            lb_arr = None
            if lb_data and lb_info:
                lb_arr = _resample(_to_mono_f32(lb_data, lb_info["channels"]),
                                   lb_info["rate"], WHISPER_RATE)
                self.root.after(0, lambda: self._set_status("Transcrevendo navegador..."))
                segments += self._transcribe_source(lb_arr, "Navegador")

            segments.sort(key=lambda x: x["start"])
            lines = [
                f"[{int(s['start']) // 60:02d}:{int(s['start']) % 60:02d}] {s['source']}: {s['text']}"
                for s in segments
            ]
            text = "\n".join(lines) or "(sem fala detectada)"

            # WAV de referencia (mix)
            if lb_arr is not None:
                n = min(len(mic_arr), len(lb_arr))
                audio = np.clip(mic_arr[:n] * 0.6 + lb_arr[:n] * 0.6, -1.0, 1.0)
            else:
                audio = np.clip(mic_arr, -1.0, 1.0)
            _save_wav(audio, WHISPER_RATE, OUTPUT_DIR / f"gravacao_{ts}.wav")

            txt_path = OUTPUT_DIR / f"gravacao_{ts}.txt"
            txt_path.write_text(text, encoding="utf-8")

            self.root.after(0, lambda: self._on_done(text, str(txt_path)))

        except Exception:
            import traceback
            err = traceback.format_exc()
            self.root.after(0, lambda: self._on_error(err))

    # ── Result callbacks ──────────────────────────────────────────────────────

    def _on_done(self, text: str, path: str):
        hora = datetime.now().strftime("%H:%M")
        self.text.insert("end", f"\n── {hora} {'─' * 44}\n{text}\n")
        self.text.see("end")
        self._set_status(f"Salvo: {path}", GREEN)
        self.btn.config(state="normal")

    def _on_error(self, err: str):
        self._set_status("Erro — veja o console", DANGER)
        messagebox.showerror("Erro na transcricao", err)
        self.btn.config(state="normal")

    def _copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end"))

    def _clear(self):
        self.text.delete("1.0", "end")

    # ── Arquivo ───────────────────────────────────────────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo de áudio/vídeo",
            filetypes=[
                ("Áudio/Vídeo", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.m4v *.ts *.mpeg *.mpg *.webm *.mp3 *.wav *.m4a *.ogg *.opus *.flac"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not path:
            return
        self.btn.config(state="disabled")
        self.file_btn.config(state="disabled")
        self._set_status(f"Processando: {Path(path).name}")
        threading.Thread(target=self._transcribe_file, args=(path,), daemon=True).start()

    def _transcribe_file(self, path: str):
        tmp_audio = None
        try:
            ext = Path(path).suffix.lower()
            if ext in VIDEO_EXTS:
                self.root.after(0, lambda: self._set_status("Extraindo audio do video..."))
                tmp_audio = _extract_audio(path)
                audio_path = tmp_audio
            else:
                audio_path = path

            self.root.after(0, lambda: self._set_status("Transcrevendo arquivo..."))
            segs = self._transcribe_source(audio_path, Path(path).name)

            lines = [
                f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}"
                for s in segs
            ]
            text = "\n".join(lines) or "(sem fala detectada)"

            OUTPUT_DIR.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            txt_path = OUTPUT_DIR / f"arquivo_{ts}.txt"
            txt_path.write_text(text, encoding="utf-8")

            self.root.after(0, lambda: self._on_done(text, str(txt_path)))
        except Exception:
            import traceback
            err = traceback.format_exc()
            self.root.after(0, lambda: self._on_error(err))
        finally:
            if tmp_audio:
                try:
                    os.unlink(tmp_audio)
                except Exception:
                    pass
            self.root.after(0, lambda: self.file_btn.config(state="normal"))
            self.root.after(0, lambda: self.btn.config(state="normal"))

    # ── Resumo IA ─────────────────────────────────────────────────────────────

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Configurações")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="Configurações", font=("Segoe UI", 13, "bold"),
                 fg=TEXT, bg=SURFACE, pady=12).pack(fill="x")

        body = tk.Frame(win, bg=BG, padx=18, pady=14)
        body.pack(fill="both")

        tk.Label(body, text="Chave da API Groq", font=FONT_B, fg=MUTED, bg=BG,
                 anchor="w").pack(fill="x", pady=(0, 4))
        tk.Label(body, text="Gratuita em console.groq.com → API Keys",
                 font=("Segoe UI", 9), fg=MUTED, bg=BG, anchor="w").pack(fill="x")

        key_var = tk.StringVar(value=self.config.get("groq_api_key", ""))
        entry = tk.Entry(body, textvariable=key_var, show="*",
                         bg=CARD, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=MONO, width=48)
        entry.pack(fill="x", pady=(6, 2))

        show_var = tk.BooleanVar(value=False)
        def toggle_show():
            entry.config(show="" if show_var.get() else "*")
        tk.Checkbutton(body, text="Mostrar chave", variable=show_var,
                       command=toggle_show, bg=BG, fg=MUTED,
                       selectcolor=CARD, activebackground=BG,
                       font=FONT).pack(anchor="w", pady=(2, 12))

        def salvar():
            self.config["groq_api_key"] = key_var.get().strip()
            _save_config(self.config)
            win.destroy()
            self._set_status("Configurações salvas", GREEN)

        tk.Button(body, text="Salvar", command=salvar,
                  bg=ACCENT, fg=TEXT, relief="flat",
                  font=FONT_B, cursor="hand2", padx=16, pady=6).pack()

    def _resumo_async(self):
        transcricao = self.text.get("1.0", "end").strip()
        if not transcricao or transcricao == "(sem fala detectada)":
            messagebox.showwarning("Sem conteúdo", "Grave algo antes de gerar o resumo.")
            return
        api_key = self.config.get("groq_api_key", "").strip()
        if not api_key:
            messagebox.showerror("Chave ausente",
                                 "Configure sua chave Groq em ⚙ Configurações.\n(gratuito em console.groq.com)")
            return
        self.resumo_btn.config(state="disabled", text="Gerando...")
        self._set_status("Gerando resumo...")
        threading.Thread(target=self._gerar_resumo, args=(transcricao, api_key), daemon=True).start()

    def _gerar_resumo(self, transcricao: str, api_key: str):
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        "Você é um assistente especializado em resumos de reuniões corporativas em português brasileiro.\n\n"
                        "Analise a transcrição abaixo e gere um resumo estruturado com as seções:\n"
                        "**Participantes identificados** (se mencionados)\n"
                        "**Tópicos discutidos**\n"
                        "**Decisões tomadas**\n"
                        "**Próximos passos / ações**\n\n"
                        f"Transcrição:\n{transcricao}"
                    ),
                }],
            )
            resumo = resp.choices[0].message.content
            self.root.after(0, lambda: self._exibir_resumo(resumo))
        except Exception:
            import traceback
            err = traceback.format_exc()
            self.root.after(0, lambda: self._on_resumo_erro(err))

    def _exibir_resumo(self, resumo: str):
        win = tk.Toplevel(self.root)
        win.title("Resumo da Reunião")
        win.configure(bg=BG)
        win.geometry("640x500")

        tk.Label(win, text="Resumo da Reunião", font=("Segoe UI", 13, "bold"),
                 fg=TEXT, bg=SURFACE, pady=12).pack(fill="x")

        txt = scrolledtext.ScrolledText(win, font=MONO, bg=CARD, fg=TEXT,
                                         relief="flat", wrap="word",
                                         padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=14, pady=10)
        txt.insert("1.0", resumo)
        txt.config(state="disabled")

        btn_row = tk.Frame(win, bg=BG, pady=8)
        btn_row.pack()

        def copiar():
            win.clipboard_clear()
            win.clipboard_append(resumo)

        def salvar():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = OUTPUT_DIR / f"resumo_{ts}.txt"
            path.write_text(resumo, encoding="utf-8")
            messagebox.showinfo("Salvo", f"Resumo salvo em:\n{path}")

        tk.Button(btn_row, text="Copiar", command=copiar,
                  bg=CARD, fg=TEXT, relief="flat", font=FONT, padx=12, pady=5).pack(side="left", padx=4)
        tk.Button(btn_row, text="Salvar TXT", command=salvar,
                  bg=ACCENT, fg=TEXT, relief="flat", font=FONT_B, padx=12, pady=5).pack(side="left", padx=4)

        self._set_status("Resumo gerado!", GREEN)
        self.resumo_btn.config(state="normal", text="Resumo IA")

    def _on_resumo_erro(self, err: str):
        self._set_status("Erro ao gerar resumo", DANGER)
        messagebox.showerror("Erro", err)
        self.resumo_btn.config(state="normal", text="Resumo IA")

    def on_close(self):
        self.pa.terminate()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
