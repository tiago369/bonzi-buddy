# Desktop Monkey Assistant

A Bonzi-Buddy-style animated monkey that lives on your desktop and acts as a
real assistant: it rests on screen, reacts with contextual animations, and
answers questions (typed or spoken) using a local Ollama model — no cloud
APIs, everything runs on your machine.

Note: code comments and console output are in Portuguese; this README is in
English.

## What it does

- Floats on screen, frameless and always on top. Drag it anywhere.
- Idles naturally: breathes continuously, and occasionally throws in a
  one-shot gesture (blink, yawn, shrug...) before settling back down.
- **Click** it (no drag) to open a small text chat bar. Type a question,
  hit Enter.
- **Hold `F9`** anywhere on screen to talk to it (push-to-talk). Release to
  send. Speech-to-text runs locally via `faster-whisper`.
- Replies show up in a speech balloon above it and are spoken aloud via
  `espeak`.
- **Right-click** for a small menu: mute voice, or quit.
- **Double-click** makes it wave hello on demand.

## Requirements

- Python 3.10+ with a venv (already set up in `venv/` if you cloned this
  as-is; recreate with `python3 -m venv venv` if needed).
- [Ollama](https://ollama.com) installed, with a model pulled:
  ```
  ollama pull llama3.2:3b
  ```
- The `espeak` system package for text-to-speech (`sudo apt install espeak`
  on Debian/Ubuntu).
- A microphone (for voice input) — optional, typed chat works without one.

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
ollama pull llama3.2:3b
```

## Running it

Ollama needs to be running before you start the assistant:

```bash
./start_ollama.sh &      # starts Ollama in CPU mode (see note below)
./venv/bin/python3 animation.py
```

**Machine-specific note**: on this machine, Ollama's GPU (CUDA/Vulkan)
backend crashes or hangs with the installed driver, so `start_ollama.sh`
forces CPU-only inference. Don't use a plain `ollama serve` here — CPU
inference is a bit slower (a few seconds per reply) but reliable.

## Start automatically on login

```bash
./configurar_autostart.sh            # enable autostart
./configurar_autostart.sh --remover  # disable it
```

This installs `~/.config/autostart/desktop-monkey-assistant.desktop`,
pointing at `iniciar_macaco.sh`, which starts Ollama (if it isn't already
running) and then the monkey.

## Configuration

A few constants worth knowing about, if you want to tweak behavior:

- `brain.py`: `MODELO` (Ollama model name), `PROMPT_SISTEMA` (the monkey's
  persona/system prompt).
- `voice.py`: `TECLA_PUSH_TO_TALK` (default `F9`), `MODELO_WHISPER`
  (default `"small"`), `VOZ_TTS` (espeak voice, default `pt-br`).
- `states.py`: which animations play for each assistant state (idle,
  listening, thinking, talking, success/error reactions).

## Project files

| File | Purpose |
|---|---|
| `animation.py` | Main app: sprite rendering/animation engine, assistant state machine, UI (window, speech balloon, chat input, context menu). Entry point. |
| `brain.py` | Talks to the local Ollama REST API, keeps conversation history. |
| `voice.py` | Push-to-talk recording + speech-to-text (`faster-whisper`) and text-to-speech (`espeak` subprocess). |
| `states.py` | Maps assistant states to pools of animation names. |
| `organizer.py` | Standalone GUI tool used to build `imgs/animations.json` from raw sprite frames — only needed if you add/edit animations, not at runtime. |
| `imgs/` | Sprite frames and `animations.json` (animation definitions). |
| `start_ollama.sh` | Starts Ollama in CPU mode (works around this machine's GPU driver issue). |
| `iniciar_macaco.sh` | Launcher used by autostart: ensures Ollama is running, then starts the monkey. |
| `configurar_autostart.sh` | Enables/disables autostart on login. |

## Adding or editing animations

Run `./venv/bin/python3 organizer.py` to open the sprite organizer: pick a
folder of frames, assemble them into a named animation (with optional
mouth-overlay compositing for talking poses), and export to
`imgs/animations.json`. Then add the new animation's name to the
appropriate pool in `states.py` if it should be used by the assistant.
