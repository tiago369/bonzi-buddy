# Desktop Monkey Assistant

A Bonzi-Buddy-style animated monkey that lives on your desktop and acts as a
real assistant: it rests on screen, reacts with contextual animations, and
answers questions (typed or spoken) using a local Ollama model — no cloud
APIs, everything runs on your machine.

Note: the code, comments, and console output are in English, but the
monkey's actual persona keeps replying and speaking in Portuguese on
purpose (see `brain.py`'s `SYSTEM_PROMPT` and `voice.py`'s `TTS_VOICE`).

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
- Reads, creates, and reminds you about **Todoist** tasks — ask it things
  like "o que eu tenho pra fazer hoje?" or "anota pra eu ligar pro dentista
  amanha as 10h", and it periodically checks on its own and interrupts you
  (once, per task) when something is due or overdue.

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
./configure_autostart.sh          # enable autostart
./configure_autostart.sh --remove # disable it
```

This installs `~/.config/autostart/desktop-monkey-assistant.desktop`,
pointing at `start_monkey.sh`, which starts Ollama (if it isn't already
running) and then the monkey.

## Todoist setup (optional)

1. Get a token from Todoist: **Settings -> Integrations -> Developer -> API
   token**.
2. Create a `.env` file in this folder (it's already git-ignored, never
   committed):
   ```
   TODOIST_API_TOKEN=your_token_here
   ```
3. That's it — `todoist.py` picks it up automatically on startup. Without a
   token, the assistant just works as before (chat/voice, no Todoist tools,
   no reminder polling).

The model decides on its own when to call the `list_tasks`/`add_task`
tools based on what you say (e.g. asking about pending tasks, or asking it
to note/add/remind something) — see `brain.py`'s tool-calling and
`todoist.py`'s tool schemas. To keep the small local model (`llama3.2:3b`)
from reaching for a tool during plain small talk, tools are only offered
to it when your message contains one of `animation.py`'s `TODOIST_KEYWORDS`
(tarefa, lembrete, anota, hoje, etc.) — see `brain.py`'s
`tool_trigger_keywords`. Proactive reminders are checked every
`REMINDER_POLL_INTERVAL_MS` (`animation.py`, default 5 minutes) and only
spoken while the monkey is idle; each task is only announced once per
session.

Note: Todoist retired the old `rest/v2` API in favor of a unified
`api/v1` — `todoist.py` already targets the new one (list endpoint is
`/tasks/filter?query=...`, not a `filter` param on `/tasks`).

## Configuration

A few constants worth knowing about, if you want to tweak behavior:

- `brain.py`: `MODEL` (Ollama model name), `SYSTEM_PROMPT` (the monkey's
  persona/system prompt).
- `voice.py`: `PUSH_TO_TALK_KEY` (default `F9`), `WHISPER_MODEL`
  (default `"small"`), `TTS_VOICE` (espeak voice, default `pt-br`).
- `states.py`: which animations play for each assistant state (idle,
  listening, thinking, talking, success/error reactions).
- `animation.py`: `REMINDER_POLL_INTERVAL_MS` (how often to check Todoist
  for due/overdue tasks).

## Project files

| File | Purpose |
|---|---|
| `animation.py` | Main app: sprite rendering/animation engine, assistant state machine, UI (window, speech balloon, chat input, context menu). Entry point. |
| `brain.py` | Talks to the local Ollama REST API, keeps conversation history. |
| `voice.py` | Push-to-talk recording + speech-to-text (`faster-whisper`) and text-to-speech (`espeak` subprocess). |
| `states.py` | Maps assistant states to pools of animation names. |
| `todoist.py` | Todoist REST API client + tool schemas for the LLM (list/add tasks). |
| `organizer.py` | Standalone GUI tool used to build `imgs/animations.json` from raw sprite frames — only needed if you add/edit animations, not at runtime. |
| `imgs/` | Sprite frames and `animations.json` (animation definitions). |
| `start_ollama.sh` | Starts Ollama in CPU mode (works around this machine's GPU driver issue). |
| `start_monkey.sh` | Launcher used by autostart: ensures Ollama is running, then starts the monkey. |
| `configure_autostart.sh` | Enables/disables autostart on login. |

## Adding or editing animations

Run `./venv/bin/python3 organizer.py` to open the sprite organizer: pick a
folder of frames, assemble them into a named animation (with optional
mouth-overlay compositing for talking poses), and export to
`imgs/animations.json`. Then add the new animation's name to the
appropriate pool in `states.py` if it should be used by the assistant.
