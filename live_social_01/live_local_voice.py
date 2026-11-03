"""Optional, local microphone adapter for the Command Center test mode."""
from __future__ import annotations

import threading


class LocalVoiceError(RuntimeError):
    pass


class LocalVoiceInput:
    """Uses SpeechRecognition only when it is already installed.

    No credentials, audio, or transcripts are persisted by this adapter.
    """
    def __init__(self) -> None:
        try:
            import speech_recognition as speech_recognition
        except ImportError:
            speech_recognition = None
        self.sr = speech_recognition
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self.sr is not None

    def microphones(self) -> list[str]:
        if not self.sr:
            return ["Padrão do sistema"]
        try:
            return ["Padrão do sistema", *self.sr.Microphone.list_microphone_names()]
        except Exception:
            return ["Padrão do sistema"]

    def start(self, on_state, on_text, on_error, device_name: str = "Padrão do sistema") -> bool:
        if not self.sr:
            on_error("Reconhecimento de voz não está disponível neste Python.")
            return False
        if self._thread and self._thread.is_alive():
            return False
        self._cancel.clear()

        def run() -> None:
            try:
                index = None
                names = self.sr.Microphone.list_microphone_names()
                if device_name and device_name != "Padrão do sistema" and device_name in names:
                    index = names.index(device_name)
                recognizer = self.sr.Recognizer()
                on_state("OUVINDO...")
                with self.sr.Microphone(device_index=index) as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.25)
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
                if self._cancel.is_set():
                    return
                on_state("PROCESSANDO...")
                text = recognizer.recognize_google(audio, language="pt-BR").strip()
                if not text:
                    raise LocalVoiceError("Não consegui entender. Tente novamente.")
                if not self._cancel.is_set():
                    on_text(text)
            except self.sr.WaitTimeoutError:
                on_error("Não ouvi uma fala a tempo. Tente novamente.")
            except self.sr.UnknownValueError:
                on_error("Não consegui entender. Tente novamente.")
            except Exception as error:
                on_error(f"Erro de microfone: {error}")

        self._thread = threading.Thread(target=run, name="jarvis-local-stt", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._cancel.set()
