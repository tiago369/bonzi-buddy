"""
Assistant voice - push-to-talk (speech input) and speech synthesis (TTS)
============================================================================
- Listens for a global key (F9 by default) with `pynput`: holding it
  records audio from the microphone, releasing it transcribes with
  `faster-whisper` (local model, runs on CPU).
- `speak(text)` sends the text to a dedicated thread that calls the
  `espeak` binary (offline TTS) via subprocess to speak it aloud.
  Important: we call the `espeak` binary directly (subprocess), NOT the
  `pyttsx3` pip package - on this machine, calling pyttsx3.init() from a
  thread breaks Qt's window painting (the espeak driver it uses under the
  hood touches some global state that conflicts with Qt's event loop),
  even though the TTS itself would work. Running it as a separate process
  avoids that problem entirely.

All of this runs off the Qt main thread, so communication with the UI is
done via PyQt5 signals (safe to emit from any thread, as long as the
QObject was created on the main thread).
"""
import queue
import subprocess
import threading

import numpy as np
import sounddevice as sd
from PyQt5.QtCore import QObject, pyqtSignal
from pynput import keyboard

PUSH_TO_TALK_KEY = keyboard.Key.f9
SAMPLE_RATE = 16000
WHISPER_MODEL = "small"
LANGUAGE = "pt"
TTS_VOICE = "pt-br"
TTS_SPEED = 175  # words per minute, same default pyttsx3 used


class VoiceAssistant(QObject):
    recording_started = pyqtSignal()
    recording_finished = pyqtSignal()
    transcription_ready = pyqtSignal(str)
    speech_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._whisper_model = None
        self._recording = False
        self._frames = []
        self._stream = None
        self._listener = None
        self.muted = False

        self._speech_queue = queue.Queue()
        self._speech_thread = threading.Thread(target=self._speech_loop, daemon=True)
        self._speech_thread.start()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._load_whisper, daemon=True).start()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
        self._speech_queue.put(None)

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        self._whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    # ------------------------------------------------------------------
    # Recording (push-to-talk)
    # ------------------------------------------------------------------
    def _on_press(self, key):
        if key != PUSH_TO_TALK_KEY or self._recording:
            return
        self._recording = True
        self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
            self.recording_started.emit()
        except Exception:
            self._recording = False
            self._stream = None

    def _audio_callback(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())

    def _on_release(self, key):
        if key != PUSH_TO_TALK_KEY or not self._recording:
            return
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.recording_finished.emit()
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        if not self._frames or self._whisper_model is None:
            self.transcription_ready.emit("")
            return
        audio = np.concatenate(self._frames, axis=0).flatten()
        segments, _info = self._whisper_model.transcribe(audio, language=LANGUAGE, beam_size=1)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        self.transcription_ready.emit(text)

    # ------------------------------------------------------------------
    # Speech (TTS)
    # ------------------------------------------------------------------
    def speak(self, text):
        self._speech_queue.put(text)

    def _speech_loop(self):
        while True:
            text = self._speech_queue.get()
            if text is None:
                break
            if text and not self.muted:
                try:
                    subprocess.run(
                        ["espeak", "-v", TTS_VOICE, "-s", str(TTS_SPEED), text],
                        check=False,
                    )
                except FileNotFoundError:
                    print("[voice] 'espeak' binary not found - install it with 'sudo apt install espeak'.")
            self.speech_finished.emit()
