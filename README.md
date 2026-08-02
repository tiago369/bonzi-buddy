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
- Reads and creates **Google Calendar** events, and gives you a heads-up
  shortly before a meeting starts — ask it "o que eu tenho na agenda hoje?"
  or "marca uma reuniao com o time amanha as 15h".
- Reads your **Gmail** inbox (list unread/recent, search, read a specific
  email) — ask it "tenho email novo?" or "procura email do joao". Read-only
  on purpose — it has no way to send, reply, or delete anything, and no
  proactive polling (email arrives far more often than tasks/meetings, so
  it only checks when you ask).

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

## Google Calendar + Gmail setup (optional)

Unlike Todoist, Google requires real OAuth2 (no simple API token). Calendar
and Gmail share one login (see `google_auth.py`) - you only authenticate
once and both work.

1. **console.cloud.google.com** → create a project (or pick an existing
   one) → **APIs & Services → Library** → enable both **"Google Calendar
   API"** and **"Gmail API"**.
2. **APIs & Services → OAuth consent screen**: choose **External** (unless
   you have a Workspace org), fill in the required fields, save. Leave it
   in **Testing** status — no Google review needed for personal use.
3. On that same consent screen, under **Público-alvo / Audience → Test
   users**, add your own Google account. Without this you'll hit a
   `403 access_denied` when authenticating, even with everything else
   configured correctly. (Google's console UI has been mid-redesign; if
   "OAuth consent screen" in the sidebar redirects to an "Overview" tab
   instead of showing test users directly, look for a separate
   **"Público-alvo"/"Audience"** tab in the same sidebar.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client
   ID**. Application type: **Desktop app**.
5. Copy the **Client ID** and **Client Secret** into `.env`:
   ```
   GOOGLE_CLIENT_ID=your_client_id_here
   GOOGLE_CLIENT_SECRET=your_client_secret_here
   ```
6. Run the one-time interactive authorization (opens a browser for you to
   grant access to both APIs at once, then stores a refresh token):
   ```bash
   ./venv/bin/python3 google_auth.py
   ```
   This writes `.google_token.json` (git-ignored). After that,
   `animation.py` picks it up automatically on startup — no need to
   re-run this unless you delete that file, revoke access, or add another
   Google API later (which would need re-running this with the expanded
   `SCOPES` in `google_auth.py`).

Same tool-calling pattern as Todoist: the model decides when to call
`list_events`/`create_event` (`CALENDAR_KEYWORDS`) or
`list_recent_emails`/`search_emails`/`read_email` (`GMAIL_KEYWORDS`) based
on `animation.py`'s keyword lists. For event creation, `create_event`'s
`start` parameter deliberately accepts a natural Portuguese phrase (e.g.
"amanha as 15h") rather than asking the small local model to compute an
exact ISO datetime itself - that computation turned out to be unreliable
for a 3B model, so `gcal.py`'s `parse_natural_datetime` resolves it
deterministically instead (mirroring how Todoist's own `due_string` parser
works). Meeting reminders are checked every `CALENDAR_POLL_INTERVAL_MS`
and announced for events starting within `CALENDAR_LOOKAHEAD_MINUTES`
(`animation.py`, defaults: every 2 minutes, 15-minute lookahead). Gmail
has no proactive polling (see `gmail.py`'s docstring for why) and is
read-only by design.

## Configuration

A few constants worth knowing about, if you want to tweak behavior:

- `brain.py`: `MODEL` (Ollama model name), `SYSTEM_PROMPT` (the monkey's
  persona/system prompt).
- `voice.py`: `PUSH_TO_TALK_KEY` (default `F9`), `WHISPER_MODEL`
  (default `"small"`), `TTS_VOICE` (espeak voice, default `pt-br`).
- `states.py`: which animations play for each assistant state (idle,
  listening, thinking, talking, success/error reactions).
- `animation.py`: `REMINDER_POLL_INTERVAL_MS` (how often to check Todoist
  for due/overdue tasks), `CALENDAR_POLL_INTERVAL_MS`/
  `CALENDAR_LOOKAHEAD_MINUTES` (same, for upcoming Calendar events).
- `gmail.py`: `MAX_RESULTS` (how many emails to summarize per query - kept
  small since summaries get fed back into the local model's context),
  `MAX_SNIPPET_CHARS`/`MAX_BODY_CHARS` (truncation limits).

## Project files

| File | Purpose |
|---|---|
| `animation.py` | Main app: sprite rendering/animation engine, assistant state machine, UI (window, speech balloon, chat input, context menu). Entry point. |
| `brain.py` | Talks to the local Ollama REST API, keeps conversation history. |
| `voice.py` | Push-to-talk recording + speech-to-text (`faster-whisper`) and text-to-speech (`espeak` subprocess). |
| `states.py` | Maps assistant states to pools of animation names. |
| `todoist.py` | Todoist REST API client + tool schemas for the LLM (list/add tasks). |
| `google_auth.py` | Shared Google OAuth2 flow/token management, used by both `gcal.py` and `gmail.py`. |
| `gcal.py` | Google Calendar REST API client + tool schemas for the LLM (list/create events). |
| `gmail.py` | Gmail REST API client + tool schemas for the LLM (list/search/read emails) - read-only by design. |
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
