"""Single-owner, cancellable Edge TTS queue for Live Social."""
from __future__ import annotations

import threading
import time
import logging
from collections import deque
from dataclasses import dataclass

import pygame

logger = logging.getLogger(__name__)


@dataclass
class Utterance:
    response: object
    author_id: str
    conversation_version: int
    created_at: float
    priority: int
    source: str
    cancelled: threading.Event
    voice_config: dict | None = None
    preview_audio_path: str | None = None
    cancel_reason: str = ''


class TTSManager:
    """One worker owns synthesis and playback; never overlaps speech."""
    IDLE, SYNTHESIZING, PLAYING, CANCELLING, ERROR = "IDLE", "SYNTHESIZING", "PLAYING", "CANCELLING", "ERROR"

    def __init__(self, on_state, on_spoken, on_tts_event=lambda *_: None, speech_options=lambda: {},
                 on_started=lambda *_: None, on_audio_started=lambda *_: None,
                 on_synthesized=lambda *_: None, before_playback=None) -> None:
        self.on_state, self.on_spoken, self.on_tts_event = on_state, on_spoken, on_tts_event
        self.speech_options, self.on_started, self.on_audio_started = speech_options, on_started, on_audio_started
        self.on_synthesized = on_synthesized
        self.before_playback = before_playback or (lambda _response, _cancelled: None)
        self.queue: deque[Utterance] = deque()
        self.enqueued_at: dict[str, float] = {}
        self.lock, self.wake = threading.RLock(), threading.Event()
        self.validate_pending = lambda response: True
        self.worker: threading.Thread | None = None
        self.current: Utterance | None = None
        self._versions: dict[str, int] = {}
        self.state, self.paused, self.stopped = self.IDLE, False, False
        self.dropped_full = self.dropped_stale = self.cancelled = self.barge_ins = self.errors = 0
        self._queue_wait_total_ms = 0.0
        self._queue_wait_count = 0
        self._queue_wait_max_ms = 0.0
        self._queue_depth_max = 0
        self.worker_close_result: dict[str, object] | None = None

    def _set_state(self, state: str) -> None:
        self.state = state
        self.on_tts_event("TTS_STATE", None, state)

    @staticmethod
    def _priority(response) -> int:
        return max(getattr(response, "tts_priority", 1), 2 if getattr(response, "source", "") in {"LOCAL_TEXT", "LOCAL_VOICE"} else 1)

    def enqueue(self, response) -> None:
        source = getattr(response, "source", "LIVE_YOUTUBE")
        preview = bool(getattr(response, "_voice_preview", False))
        is_zuko = source == "ZUKO" or str(getattr(response, "provider", "")).startswith("ZUKO_")
        voice_config = None
        if preview:
            voice_config = dict(getattr(response, "_voice_config", {}))
        elif is_zuko:
            import zuko_voice_config
            voice_config = dict(zuko_voice_config.load())
        with self.lock:
            author = response.author
            conversational = source in {"LOCAL_TEXT", "LOCAL_VOICE", "LIVE_YOUTUBE", "YOUTUBE_DOM", "OCR"}
            version = self._versions.get(author, 0)
            if conversational:
                version = self._versions[author] = version + 1
            # Keep the active utterance and HIGH events; replace only same-author pending conversation replies.
            if conversational:
                kept = deque()
                for item in self.queue:
                    if item.author_id == author and item.source in {"LOCAL_TEXT", "LOCAL_VOICE", "LIVE_YOUTUBE", "YOUTUBE_DOM", "OCR"}:
                        item.cancelled.set(); self.dropped_stale += 1
                        self.enqueued_at.pop(item.response.comment_id, None)
                        self.on_tts_event("TTS_STALE_DROPPED", item.response)
                    else:
                        kept.append(item)
                self.queue = kept
            item = Utterance(response, author, version, time.monotonic(), self._priority(response),
                             source, threading.Event(), voice_config,
                             getattr(response, "_preview_audio_path", None))
            # Stable priority ordering; never reorder the utterance already playing.
            position = next((i for i, queued in enumerate(self.queue) if queued.priority < item.priority), len(self.queue))
            self.queue.insert(position, item)
            self.enqueued_at[response.comment_id] = item.created_at
            self._queue_depth_max = max(self._queue_depth_max, len(self.queue))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._drain, name="jarvis-live-tts-manager", daemon=True)
                self.worker.start()
            self.wake.set()

    def set_paused(self, paused: bool) -> None:
        with self.lock: self.paused = paused
        self.wake.set()

    def cancel_current(self, *, barge_in: bool = False, clear_pending: bool = False,
                       reason: str = 'REQUESTED') -> None:
        with self.lock:
            if self.current:
                self._set_state(self.CANCELLING)
                self.current.cancel_reason=reason
                self.current.cancelled.set(); self.cancelled += 1
                if barge_in: self.barge_ins += 1
            if clear_pending:
                for item in self.queue:item.cancel_reason=reason;item.cancelled.set()
                self.queue.clear(); self.enqueued_at.clear()
        try:
            if pygame.mixer.get_init(): pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.wake.set()

    def barge_in(self, author: str) -> None:
        """Voice input may interrupt the current local utterance only."""
        with self.lock:
            local_current = self.current and self.current.author_id == author and self.current.source in {"LOCAL_TEXT", "LOCAL_VOICE"}
        if local_current:
            self.cancel_current(barge_in=True,reason='BARGE_IN')

    def stop(self) -> None:
        self.stopped = True; self.cancel_current(clear_pending=True,reason='SHUTDOWN'); self.wake.set()

    def cancel_preview(self) -> bool:
        """Stop only voice-preview work, leaving queued live speech untouched."""
        cancelled = False
        with self.lock:
            if self.current and getattr(self.current.response, "_voice_preview", False):
                self.current.cancel_reason='PREVIEW_CANCELLED'
                self.current.cancelled.set(); self.cancelled += 1; cancelled = True
            kept = deque()
            for item in self.queue:
                if getattr(item.response, "_voice_preview", False):
                    item.cancel_reason='PREVIEW_CANCELLED'
                    item.cancelled.set(); self.enqueued_at.pop(item.response.comment_id, None); cancelled = True
                else:
                    kept.append(item)
            self.queue = kept
        if cancelled and pygame.mixer.get_init():
            pygame.mixer.music.stop()
        self.wake.set()
        return cancelled

    def _drain(self) -> None:
        from zuko_voice import falar
        while not self.stopped:
            with self.lock:
                if self.paused or not self.queue:
                    item = None
                else:
                    item = self.queue.popleft()
                    self.current = item
                    queued_at = self.enqueued_at.pop(item.response.comment_id, item.created_at)
            if item is None:
                self.wake.wait(.15); self.wake.clear(); continue
            version_stale = item.source in {"LOCAL_TEXT", "LOCAL_VOICE", "LIVE_YOUTUBE", "YOUTUBE_DOM", "OCR"} and self._versions.get(item.author_id) != item.conversation_version
            preview = bool(getattr(item.response, "_voice_preview", False))
            if item.cancelled.is_set() or version_stale or (not preview and not self.validate_pending(item.response)):
                with self.lock:
                    self.current = None
                    self.dropped_stale += 1
                self.on_tts_event("TTS_STALE_DROPPED", item.response); continue
            if not getattr(item.response, "tts_enabled", True):
                self.on_tts_event("TTS_SKIPPED", item.response); self.current = None; continue
            started = time.monotonic(); self._set_state(self.SYNTHESIZING)
            queue_wait_ms = max(0.0, (started - queued_at) * 1000)
            with self.lock:
                self._queue_wait_total_ms += queue_wait_ms
                self._queue_wait_count += 1
                self._queue_wait_max_ms = max(self._queue_wait_max_ms, queue_wait_ms)
            if not preview:self.on_started(item.response, queue_wait_ms, (started - item.response.received_at) * 1000)
            failure: list[Exception] = []; playback_started = False; synthesis_completed_at: list[float | None] = [None]
            playback_lock=threading.Lock()
            def playback_began():
                nonlocal playback_started
                with playback_lock:
                    if playback_started or item.cancelled.is_set():return
                    playback_started=True
                self._set_state(self.PLAYING)
                playback_anchor=synthesis_completed_at[0] or started
                if not preview:self.on_audio_started(item.response,max(0.0,(time.monotonic()-playback_anchor)*1000))
                self.on_tts_event('TTS_INICIO',item.response);self.on_state('SPEAKING')
            def speak() -> None:
                try:
                    def synthesized() -> None:
                        synthesis_completed_at[0] = time.monotonic()
                        if not preview:self.on_synthesized(item.response, (synthesis_completed_at[0] - started) * 1000)
                    options = dict(self.speech_options())
                    if item.voice_config is not None:
                        if preview:
                            options['voice_config'] = item.voice_config
                        else:
                            # Resolve at playback time so a saved selector change applies to the next queued ZUKO utterance.
                            import zuko_voice_config
                            options['voice_config'] = dict(zuko_voice_config.load())
                    if item.preview_audio_path:options['preview_audio_path'] = item.preview_audio_path
                    if preview:options['voice_request'] = item.response.comment_id
                    def prepare():
                        if not item.cancelled.is_set():self.before_playback(item.response,item.cancelled.is_set)
                    falar(item.response.text, cancelar=item.cancelled.is_set, on_synthesized=synthesized,
                          before_playback=prepare,on_playback_started=playback_began,**options)
                except Exception as error: failure.append(error)
            thread = threading.Thread(target=speak, name="live-social-edge-tts", daemon=True); thread.start()
            while thread.is_alive():
                if not playback_started and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    playback_began()
                time.sleep(.01)
            thread.join()
            if item.cancelled.is_set(): self.on_tts_event("TTS_CANCELLED", item.response, item.cancel_reason or 'CANCEL_REASON_UNKNOWN')
            elif failure:
                self.errors += 1; self.on_tts_event("TTS_ERRO", item.response, str(failure[0]))
            elif not playback_started:
                self.errors += 1; self.on_tts_event("TTS_ERRO", item.response, "reprodução não iniciou")
            else:
                self.on_tts_event("TTS_OK", item.response)
                if not preview:self.on_spoken(item.response, (started - item.response.received_at) * 1000)
            with self.lock: self.current = None
            self._set_state(self.IDLE); self.on_state("WATCHING")
        # The speech process belongs to this serial queue and ends with it.
        # A shutdown timeout must not terminate this manager thread with an
        # uncaught exception or prevent its remaining state cleanup.
        try:
            from zuko_voice_worker import worker as local_worker
            self.worker_close_result = local_worker.close()
            if not self.worker_close_result.get('exited', True):
                logger.error('ZUKO TTS worker remained active after shutdown: %s',
                             self.worker_close_result)
        except Exception as error:
            self.worker_close_result = {'status':'CLOSE_ERROR','exited':False,
                                        'error_type':type(error).__name__}
            logger.exception('Unable to close ZUKO TTS worker during manager cleanup')
        finally:
            with self.lock:
                self.current = None
                if self.stopped:
                    self.state = self.IDLE

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {"TTS_STATE": self.state, "TTS_QUEUE_DEPTH": len(self.queue),
                    "TTS_PAUSED":self.paused,
                    "TTS_STALE_DROPPED_SESSION": self.dropped_stale, "TTS_BARGE_IN_SESSION": self.barge_ins,
                    "TTS_CANCELLED_SESSION": self.cancelled, "TTS_ERRORS_SESSION": self.errors,
                    "TTS_MAX_QUEUE_WAIT_MS": round(self._queue_wait_max_ms, 2),
                    "TTS_AVG_QUEUE_WAIT_MS": round(self._queue_wait_total_ms / self._queue_wait_count, 2) if self._queue_wait_count else 0.0,
                    "TTS_QUEUE_DEPTH_MAX": self._queue_depth_max,
                    "TTS_WORKER_CLOSE": dict(self.worker_close_result) if self.worker_close_result else None}
