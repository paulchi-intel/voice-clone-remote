# Voice Clone Remote — Qwen3-TTS backend for Intel GPUs (XPU)
FROM ubuntu:24.04

ARG http_proxy
ARG https_proxy
ARG no_proxy
ENV DEBIAN_FRONTEND=noninteractive

# Intel GPU user-space runtime (Level Zero + OpenCL) for Battlemage, plus SoX
RUN apt-get update \
 && apt-get install -y --no-install-recommends software-properties-common gpg-agent ca-certificates \
 && add-apt-repository -y ppa:kobuk-team/intel-graphics \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      libze1 libze-intel-gpu1 intel-opencl-icd clinfo \
      python3 python3-venv python3-pip \
      sox libsox-fmt-all libsndfile1 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/xpu \
 && pip install --no-cache-dir -r /app/requirements.txt

COPY tts_server.py /app/tts_server.py

ENV HF_HOME=/models \
    TTS_MODEL_ID=Qwen/Qwen3-TTS-12Hz-1.7B-Base \
    TTS_PORT=17494 \
    PYTHONUNBUFFERED=1

WORKDIR /app
EXPOSE 17494
CMD ["python", "tts_server.py"]
