"""
Job application generator integration - "vaga:<url>" command
================================================================
Wraps the `aplication_generator` git submodule (a separate project that
scrapes a job posting and asks an LLM to tailor a CV + cover letter from
your base templates) as a subprocess call, so the monkey can trigger it
directly from a chat message like "vaga:https://example.com/job/123"
without that message ever going through Ollama - this is a deterministic
command, not something to leave up to the small local model to interpret.

Runs with the same Python interpreter as the rest of buddy (its deps were
installed into buddy's venv) but as a subprocess, since generate.py is a
standalone CLI script with its own sys.path/import setup.
"""
import os
import re
import subprocess
import sys

SUBMODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aplication_generator")
GENERATE_SCRIPT = os.path.join(SUBMODULE_DIR, "generate.py")
ENV_FILE = os.path.join(SUBMODULE_DIR, ".env")

# Generation involves job-posting scraping + two LLM calls + LaTeX
# compilation, easily 1-2 minutes - generous timeout so a slow provider
# response doesn't get killed mid-way.
TIMEOUT_SECONDS = 300

# Matches the "vaga:<url>" command anywhere in the message (case-insensitive),
# tolerating a space after the colon (e.g. "vaga: https://...").
VAGA_COMMAND_RE = re.compile(r"^\s*vaga\s*:\s*(\S+)\s*$", re.IGNORECASE)


def extract_vaga_url(text):
    """Returns the URL if `text` is a "vaga:<url>" command, else None."""
    match = VAGA_COMMAND_RE.match(text or "")
    return match.group(1) if match else None


class JobApplicationGenerator:
    def is_configured(self):
        return os.path.exists(GENERATE_SCRIPT)

    def generate(self, url):
        """Runs generate.py for `url` and returns {"out_dir": str,
        "log_tail": str}. Raises RuntimeError on failure (missing API key,
        scrape failure, etc.) with the script's stderr as the message."""
        result = subprocess.run(
            [sys.executable, GENERATE_SCRIPT, url],
            cwd=SUBMODULE_DIR,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            error_tail = (result.stderr or result.stdout or "unknown error").strip().splitlines()
            raise RuntimeError(error_tail[-1] if error_tail else "unknown error")

        out_dir = None
        for line in result.stdout.splitlines():
            if line.startswith("Done. Output in "):
                out_dir = line[len("Done. Output in "):].strip()
        return {"out_dir": out_dir, "log_tail": result.stdout.strip()[-500:]}
