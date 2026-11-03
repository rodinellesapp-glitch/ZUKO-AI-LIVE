"""Captura e reconhecimento SpeechRecognition e reprodução Edge TTS."""
import asyncio
import os
from pathlib import Path
import tempfile
import threading
import time
import edge_tts
import pygame
import speech_recognition as sr
import config

_trava_fala = threading.Lock()


def falar(texto, cancelar=lambda: False, *, voice=None, rate=None, pitch=None, volume=None, on_synthesized=None):
    """Speak once under the existing global lock.

    Optional arguments are an isolated Live Social override. Existing callers keep
    using the configuration defaults unchanged.
    """
    print("JARVIS:", texto, flush=True)
    with _trava_fala:
        if cancelar():
            return
        descritor, nome = tempfile.mkstemp(prefix="jarvis_voz_", suffix=".mp3")
        os.close(descritor)
        carregado = False
        async def gerar():
            comunicacao = edge_tts.Communicate(
                text=texto, voice=voice or config.VOZ, rate=rate or config.VELOCIDADE,
                pitch=pitch or config.TOM, volume=volume or config.VOLUME)
            await asyncio.wait_for(comunicacao.save(nome), timeout=config.TIMEOUT_TTS)
        try:
            asyncio.run(gerar())
            if cancelar():
                return
            if on_synthesized:
                on_synthesized()
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(nome)
            carregado = True
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if cancelar():
                    pygame.mixer.music.stop()
                    break
                pygame.time.wait(50)
        finally:
            if carregado:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            Path(nome).unlink(missing_ok=True)


class CapturaCancelada(Exception):
    pass


class MicrofoneSemDados(TimeoutError):
    pass


class FluxoCancelavel:
    """Espera dados disponíveis antes de chamar a leitura bloqueante do driver."""
    def __init__(self, original, cancelar):
        self.original = original
        self.cancelar = cancelar

    def read(self, tamanho):
        prazo = time.monotonic() + 2.0
        while True:
            if self.cancelar():
                raise CapturaCancelada()
            if self.original.pyaudio_stream.get_read_available() >= tamanho:
                return self.original.read(tamanho)
            if time.monotonic() >= prazo:
                raise MicrofoneSemDados("O microfone ficou sem entregar áudio por 2 segundos.")
            time.sleep(0.02)

    def close(self):
        self.original.close()


class Escuta:
    def __init__(self):
        self.reconhecedor = sr.Recognizer()
        self.reconhecedor.operation_timeout = config.TIMEOUT_REDE
        self.reconhecedor.pause_threshold = config.PAUSA_FIM_FRASE
        self.calibrado = False

    def ouvir(self, status=lambda texto: None, cancelar=lambda: False):
        with sr.Microphone() as fonte:
            if fonte.stream is None:
                raise MicrofoneSemDados("Não consegui abrir o microfone.")
            fonte.stream = FluxoCancelavel(fonte.stream, cancelar)
            if cancelar():
                return None
            if not self.calibrado:
                status("CALIBRANDO MICROFONE... Aguarde um instante.")
                self.reconhecedor.adjust_for_ambient_noise(fonte, duration=config.CALIBRACAO)
                self.calibrado = True
                self.reconhecedor.dynamic_energy_threshold = False
                print("MICROFONE: calibrado; sensibilidade", round(self.reconhecedor.energy_threshold), flush=True)
            if cancelar():
                return None
            status("OUVINDO...")
            audio = self.reconhecedor.listen(
                fonte, timeout=config.TEMPO_ESPERA, phrase_time_limit=config.LIMITE_FRASE)
        if cancelar():
            return None
        status("PROCESSANDO...")
        return self.reconhecedor.recognize_google(audio, language=config.IDIOMA).lower()


def fechar_audio():
    if pygame.mixer.get_init():
        pygame.mixer.quit()
