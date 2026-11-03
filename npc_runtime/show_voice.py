from pathlib import Path
import shutil
import threading
import time


class ShowVoice:
    def __init__(self, client, config, trace, evidence=None):
        self.client, self.config, self.trace, self.evidence = client, config, trace, evidence
        self.stop = threading.Event()
        self.thread = None
        self.started = False

    def _send(self, event):
        try:
            self.client.send_event(event)
            self.trace('TCP_SENT', event=event)
        except ConnectionError:
            self.trace('NPC_DISCONNECTED', event=event)

    def _start(self):
        self.started = True
        self.trace('VOICE_STARTED')
        self._send('talk')
        def repeat():
            # Wave é um clipe corporal pronto de 2,083 s; nunca reiniciar por frame.
            while not self.stop.wait(2.15):
                self._send('talk')
        self.thread = threading.Thread(target=repeat, name='npc-show-gesture', daemon=True)
        self.thread.start()

    def _end(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        self._send('idle')
        self.trace('VOICE_ENDED', started=self.started)

    def speak(self, text):
        from vendor.nexus.voz import falar
        self.stop.clear()
        self.started = False
        def synthesized_file(filename):
            path = Path(filename)
            self.trace('VOICE_SYNTHESIZED', bytes=path.stat().st_size)
            if self.evidence:
                shutil.copyfile(path, self.evidence)
        try:
            falar(text, voice=self.config['name'], rate=self.config['rate'],
                  pitch=self.config['pitch'], volume=self.config['volume'],
                  engine=self.config.get("engine", "edge"), windows_rate=self.config.get("windows_rate", 2),
                  on_audio_file=synthesized_file, on_playback_started=self._start,
                  on_playback_ended=self._end)
            if not self.started:
                raise RuntimeError('Voz não iniciou a reprodução.')
        except Exception:
            self.stop.set()
            if self.thread:
                self.thread.join(timeout=1)
            self._send('idle')
            raise
