"""
tts_server.py — Voice Clone Remote HTTP backend (runs in a container on B70)
Port: 17494 (TTS_PORT)

Starts the HTTP server immediately, then loads Qwen3-TTS 1.7B in the
background (downloading it into HF_HOME on first run), and serves:
  GET  /health     → {"status":"ok","model_loaded":bool,"device":"xpu"}
  POST /synthesize → {"audio_base64", "reference_text", "text", "language"}
                   ← {"status":"ok","audio_base64":"...","sample_rate":24000}
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

MODEL_ID = os.environ.get("TTS_MODEL_ID", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
HOST     = os.environ.get("TTS_HOST", "0.0.0.0")
PORT     = int(os.environ.get("TTS_PORT", "17494"))

# Language name map expected by Qwen3-TTS
LANG_MAP: dict[str, str] = {
    "en": "english",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
    "de": "german",
    "fr": "french",
    "ru": "russian",
    "pt": "portuguese",
    "es": "spanish",
    "it": "italian",
}

# ── Model loading (background thread) ─────────────────────────────────────────
model        = None
MODEL_LOADED = False
MODEL_ERROR  = None
DEVICE       = None
# Qwen3-TTS is not safe to call from several request threads at once
infer_lock   = threading.Lock()


def _pick_device(torch) -> str:
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_model() -> None:
    global model, MODEL_LOADED, MODEL_ERROR, DEVICE
    try:
        import torch
        from huggingface_hub import snapshot_download
        from qwen_tts import Qwen3TTSModel

        DEVICE = _pick_device(torch)
        dtype  = torch.bfloat16 if DEVICE != "cpu" else torch.float32

        print(f"[tts_server] Fetching {MODEL_ID} (cached in {os.environ.get('HF_HOME')})…", flush=True)
        model_path = snapshot_download(MODEL_ID)

        print(f"[tts_server] Loading model on {DEVICE}…", flush=True)
        m = Qwen3TTSModel.from_pretrained(
            model_path,
            local_files_only=True,
            dtype=dtype,
            **({"device_map": DEVICE} if DEVICE != "cpu" else {}),
        )
        model        = m
        MODEL_LOADED = True
        print(f"[tts_server] Model loaded on {DEVICE}.", flush=True)
    except Exception as exc:
        MODEL_ERROR = str(exc)
        print(f"[tts_server] ERROR loading model: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()


def synthesize(audio_bytes: bytes, reference_text: str, text: str, language: str) -> tuple[bytes, int]:
    import numpy as np
    import soundfile as sf

    # Write reference audio to a temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_ref:
        tmp_ref.write(audio_bytes)
        tmp_ref_path = tmp_ref.name
    tmp_out_path = tmp_ref_path.replace(".wav", "_out.wav")

    try:
        with infer_lock:
            voice_prompt = model.create_voice_clone_prompt(
                tmp_ref_path,
                reference_text,
                x_vector_only_mode=False,
            )
            result = model.generate_voice_clone(
                text,
                voice_clone_prompt=voice_prompt,
                language=language,
            )

        # generate_voice_clone returns (waveform, sample_rate) tuple
        if isinstance(result, (tuple, list)) and len(result) == 2:
            audio_raw, sample_rate = result
        else:
            audio_raw, sample_rate = result, 24000

        # Normalise to numpy float32
        if isinstance(audio_raw, (list, tuple)) and len(audio_raw) == 1:
            audio_raw = audio_raw[0]
        if hasattr(audio_raw, "detach"):
            audio_raw = audio_raw.detach().float().cpu().numpy()
        audio_np = np.array(audio_raw, dtype=np.float32)
        if audio_np.ndim > 1:
            audio_np = audio_np.squeeze()
        sf.write(tmp_out_path, audio_np, sample_rate, format="WAV")

        with open(tmp_out_path, "rb") as f:
            return f.read(), sample_rate
    finally:
        for p in [tmp_ref_path, tmp_out_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        print(f"[tts_server] {self.client_address[0]} {fmt % args}", flush=True)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json({
                "status":       "ok",
                "model_loaded": MODEL_LOADED,
                "model_error":  MODEL_ERROR,
                "device":       DEVICE,
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/synthesize":
            self._send_json({"error": "Not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, 400)
            return

        audio_b64      = payload.get("audio_base64", "")
        reference_text = payload.get("reference_text", "").strip()
        text           = payload.get("text", "").strip()
        lang_code      = payload.get("language", "en")

        if not audio_b64 or not reference_text or not text:
            self._send_json({"error": "Missing required fields"}, 400)
            return

        if not MODEL_LOADED or model is None:
            self._send_json({"error": MODEL_ERROR or "Model not loaded yet", "status": "error"}, 503)
            return

        try:
            out_bytes, sample_rate = synthesize(
                base64.b64decode(audio_b64), reference_text, text,
                LANG_MAP.get(lang_code, "english"),
            )
            self._send_json({
                "status":       "ok",
                "audio_base64": base64.b64encode(out_bytes).decode(),
                "sample_rate":  sample_rate,
            })
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"status": "error", "error": str(exc)}, 500)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each request in its own thread."""
    daemon_threads = True


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=load_model, daemon=True).start()
    server = ThreadedHTTPServer((HOST, PORT), Handler)
    print(f"[tts_server] Listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[tts_server] Stopped.", flush=True)
