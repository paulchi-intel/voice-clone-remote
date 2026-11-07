# Voice Clone Remote — Chrome Extension

A Chrome side-panel extension that clones any voice with [Qwen3-TTS 1.7B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base).
The model runs in a Docker container on an Intel GPU (XPU) server; the extension on your PC only sends requests to it.

## Features

- 🎤 **Voice cloning** — upload a reference `.wav`, type text, hear it in that voice
- 👤 **Voice profiles** — save/load named voices; switch instantly from a dropdown
- 📋 **Task queue** — enqueue multiple jobs; they run sequentially
- ⏹ / ↺ **Stop / Retry** — abort or retry any task with one click
- ↕ **Drag-to-reorder** — rearrange waiting tasks in the queue
- 📝 **Copy & expand** — copy the synthesis text, expand long text in the queue
- ⏱ **Elapsed time** — shows generation duration per card; persists after restart
- 🖥️ **Remote backend** — no Python or model on your PC; Qwen3-TTS runs on the server
- 🔔 **Update notice** — a banner appears when a newer GitHub Release exists
- 🌐 **i18n** — English, 繁體中文, 简体中文

---

## Architecture

```
Chrome extension (your PC)
  sidepanel.js  ──HTTP──▶  http://<SERVER_IP>:17494
                                   │
                    server: container voice-clone-tts
                         server/tts_server.py
                         Qwen3-TTS 1.7B on one Intel GPU (XPU)
                                   │
                            WAV (base64)  ──▶  audio player
```

API:

| Endpoint | Description |
|---|---|
| `GET /health` | `{"status":"ok","model_loaded":true,"device":"xpu"}` |
| `POST /synthesize` | body `{"audio_base64","reference_text","text","language"}` → `{"status":"ok","audio_base64","sample_rate"}` |

---

## Server setup

Files are in [`server/`](server/). On the GPU server:

```bash
mkdir -p ~/voice-clone-remote && cd ~/voice-clone-remote/server   # copy server/ here first
docker compose up -d --build
docker logs -f voice-clone-tts        # first start downloads the model (~3.5 GB) into the voice-clone-models volume
```

Edit `docker-compose.yml` first so the `devices:` entry points at the GPU render node you want to use (`/dev/dri/renderD128`, `renderD129`, …) and `group_add` matches your host's `render` group id.

Docker publishes `0.0.0.0:17494` through its own iptables rules, which bypass ufw. Check it:

```bash
curl --noproxy '*' http://<SERVER_IP>:17494/health
```

Notes:
- The service has **no authentication** — anyone who can reach port 17494 can use it. Keep it on a trusted network.
- The model cache lives in the Docker volume `voice-clone-models`, so restarts don't re-download.

---

## Extension setup (your PC)

```bash
git clone https://github.com/paulchi-intel/voice-clone-remote.git
```

1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (toggle, top-right)
3. Click **Load unpacked** → select this folder
4. Click the **Voice Clone Remote** icon to open the side panel
5. On first run the **Server** field opens automatically — enter `http://<SERVER_IP>:17494` and press Enter. Chrome asks permission for that one address; the address is stored only in your browser (`chrome.storage`), not in this repository
6. Wait for "ready", then follow the numbered steps: prepare the reference voice → enter the text → **Generate Speech**

---

## Update

The side panel checks the latest GitHub Release when it opens and caches the result for six hours. When a newer version exists, a banner appears with a **Download** button that fetches the release ZIP; **×** dismisses that version.

Chrome does not allow unpacked extensions to update themselves, so to apply the update: unzip the download over your existing folder, then click **Reload** on the extension in `chrome://extensions`. Settings, profiles and the queue stay in `chrome.storage.local`.

The check needs the repository to be readable without logging in; for a private repository it finds no release and shows nothing.

## Release

1. Update `version` in `manifest.json` and commit it.
2. Create and push a matching tag, e.g. `git tag v2.1.0 && git push origin v2.1.0`.
3. GitHub Actions ([`release.yml`](.github/workflows/release.yml)) checks the tag matches `manifest.json` and that the JavaScript parses, then publishes `voice-clone-remote-vX.Y.Z.zip` and its SHA-256 checksum.

---

## Voice Profiles

| Action | How |
|---|---|
| Save as new profile | Click 💾, enter a **new** name |
| Update existing profile | Click 💾, enter the **same** name |
| Switch profile | Pick from dropdown — fields auto-fill |
| Delete profile | Click 🗑 and confirm |

## Task Queue Controls

| Control | Behaviour |
|---|---|
| ⏹ | Abort in-flight synthesis |
| ↺ | Re-queue a stopped or failed task |
| ✕ | Remove task (aborts if generating) |
| ⠿ drag | Reorder waiting tasks (grab the handle) |
| hover text | Shows copy and expand buttons |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Set the server address first" | Open the ⚙ next to the status and enter the server address |
| "Server unreachable" | Check `docker ps` on the server shows `voice-clone-tts` running, and `curl --noproxy '*' http://<SERVER_IP>:17494/health` answers |
| Works with curl on the server but not from Chrome | Your PC's proxy may be intercepting the server address; add it to the proxy bypass list, or use an SSH tunnel (`ssh -L 17494:localhost:17494 <user>@<SERVER_IP>`) and set Server to `http://localhost:17494` |
| Stuck on "loading the model" | First run downloads ~3.5 GB — watch `docker logs -f voice-clone-tts` |
| Audio sounds distorted | Use a 16–24 kHz mono WAV, 5–15 s long, minimal background noise |

---

## License

MIT — see [LICENSE](LICENSE)
