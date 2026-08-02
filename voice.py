"""
Voz do assistente - push-to-talk (fala) e sintese de voz (TTS)
==================================================================
- Escuta uma tecla global (F9 por padrao) com `pynput`: segurar grava
  audio do microfone, soltar transcreve com `faster-whisper` (modelo
  local, roda na CPU).
- `falar(texto)` envia o texto para uma thread dedicada que chama o
  binario `espeak` (TTS offline) via subprocess pra falar em voz alta.
  Importante: usamos o binario `espeak` diretamente (subprocess), NAO o
  pacote pip `pyttsx3` - nesse ambiente, chamar pyttsx3.init() numa thread
  quebra a pintura das janelas do Qt (o driver do espeak que ele usa por
  baixo dos panos mexe num estado global que conflita com o event loop do
  Qt), mesmo que o TTS em si funcionasse. Rodar como processo separado
  evita esse problema por completo.

Tudo isso roda fora da thread principal do Qt, entao a comunicacao com a
UI e feita via sinais do PyQt5 (seguro de emitir de qualquer thread,
desde que o QObject tenha sido criado na thread principal).
"""
import queue
import subprocess
import threading

import numpy as np
import sounddevice as sd
from PyQt5.QtCore import QObject, pyqtSignal
from pynput import keyboard

TECLA_PUSH_TO_TALK = keyboard.Key.f9
TAXA_AMOSTRAGEM = 16000
MODELO_WHISPER = "small"
IDIOMA = "pt"
VOZ_TTS = "pt-br"
VELOCIDADE_TTS = 175  # palavras por minuto, mesmo default que o pyttsx3 usava


class VoiceAssistant(QObject):
    gravacao_iniciada = pyqtSignal()
    gravacao_finalizada = pyqtSignal()
    transcricao_pronta = pyqtSignal(str)
    fala_finalizada = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._modelo_whisper = None
        self._gravando = False
        self._frames = []
        self._stream = None
        self._listener = None
        self.mudo = False

        self._fila_fala = queue.Queue()
        self._thread_fala = threading.Thread(target=self._loop_fala, daemon=True)
        self._thread_fala.start()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def iniciar(self):
        threading.Thread(target=self._carregar_whisper, daemon=True).start()
        self._listener = keyboard.Listener(on_press=self._ao_pressionar, on_release=self._ao_soltar)
        self._listener.start()

    def parar(self):
        if self._listener:
            self._listener.stop()
        self._fila_fala.put(None)

    def _carregar_whisper(self):
        from faster_whisper import WhisperModel
        self._modelo_whisper = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8")

    # ------------------------------------------------------------------
    # Gravacao (push-to-talk)
    # ------------------------------------------------------------------
    def _ao_pressionar(self, key):
        if key != TECLA_PUSH_TO_TALK or self._gravando:
            return
        self._gravando = True
        self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=TAXA_AMOSTRAGEM, channels=1, dtype="float32",
                callback=self._callback_audio,
            )
            self._stream.start()
            self.gravacao_iniciada.emit()
        except Exception:
            self._gravando = False
            self._stream = None

    def _callback_audio(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())

    def _ao_soltar(self, key):
        if key != TECLA_PUSH_TO_TALK or not self._gravando:
            return
        self._gravando = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.gravacao_finalizada.emit()
        threading.Thread(target=self._transcrever, daemon=True).start()

    def _transcrever(self):
        if not self._frames or self._modelo_whisper is None:
            self.transcricao_pronta.emit("")
            return
        audio = np.concatenate(self._frames, axis=0).flatten()
        segmentos, _info = self._modelo_whisper.transcribe(audio, language=IDIOMA, beam_size=1)
        texto = " ".join(segmento.text.strip() for segmento in segmentos).strip()
        self.transcricao_pronta.emit(texto)

    # ------------------------------------------------------------------
    # Fala (TTS)
    # ------------------------------------------------------------------
    def falar(self, texto):
        self._fila_fala.put(texto)

    def _loop_fala(self):
        while True:
            texto = self._fila_fala.get()
            if texto is None:
                break
            if texto and not self.mudo:
                try:
                    subprocess.run(
                        ["espeak", "-v", VOZ_TTS, "-s", str(VELOCIDADE_TTS), texto],
                        check=False,
                    )
                except FileNotFoundError:
                    print("[voz] binario 'espeak' nao encontrado - instale com 'sudo apt install espeak'.")
            self.fala_finalizada.emit()
