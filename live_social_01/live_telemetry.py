"""Bounded, local-only metrics for the Live Social Command Center."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean
from threading import Lock


@dataclass
class _Samples:
    values: list[float] = field(default_factory=list)
    def add(self, value: float) -> None:
        self.values.append(max(0.0, value))
        del self.values[:-300]
    def summary(self) -> tuple[float, float]:
        return (fmean(self.values), max(self.values)) if self.values else (0.0, 0.0)


class LiveTelemetry:
    """Thread-safe counters and bounded latency samples; no network or persistence."""
    def __init__(self) -> None:
        self._lock = Lock()
        self.counts = defaultdict(int)
        self.latency = defaultdict(_Samples)
        self.health = {"DOM": "OFFLINE", "PONTE 8766": "OFFLINE", "GEMINI": "NÃO VERIFICADO", "TTS": "NÃO VERIFICADO", "FILA DE VOZ": "IDLE"}
        self.last_error = "—"

    def event(self, name: str, latency_ms: float | None = None, health: tuple[str, str] | None = None) -> None:
        with self._lock:
            self.counts[name] += 1
            if latency_ms is not None:
                self.latency[name].add(latency_ms)
            if health:
                self.health[health[0]] = health[1]

    def error(self, text: str, is_429: bool = False) -> None:
        with self._lock:
            self.counts["erros"] += 1
            if is_429:
                self.counts["429"] += 1
                self.health["GEMINI"] = "COOLDOWN"
            self.last_error = text[:180]

    def reset_session_errors(self):
        with self._lock:
            self.counts['429']=0; self.counts['erros']=0; self.last_error='—'

    def set_gemini_calls_session(self, count: int) -> None:
        with self._lock:
            self.counts["gemini_calls_session"] = max(0, count)

    def set_gemini_metrics(self, attempts: int, success: int, errors: int) -> None:
        with self._lock:
            if success > self.counts["GEMINI_CALL_SUCCESS_SESSION"]:
                self.health["GEMINI"] = "ONLINE"
            self.counts["gemini_calls_session"] = attempts
            self.counts["GEMINI_CALL_ATTEMPTS_SESSION"] = attempts
            self.counts["GEMINI_CALL_SUCCESS_SESSION"] = success
            self.counts["GEMINI_CALL_ERRORS_SESSION"] = errors

    def set_gemini_output_metrics(self, finish_reason: str, output_chars: int) -> None:
        with self._lock:
            self.counts["LAST_FINISH_REASON"] = finish_reason
            self.counts["LAST_OUTPUT_CHARS"] = max(0, output_chars)
            if finish_reason == "MAX_TOKENS":
                self.counts["FINISH_MAX_TOKENS_SESSION"] += 1

    def set_tts_metrics(self, metrics: dict[str, object]) -> None:
        with self._lock:
            state=str(metrics.get('TTS_STATE','NÃO VERIFICADO'))
            self.health['FILA DE VOZ']=state
            if state=='PLAYING':self.health['TTS']='REPRODUZINDO · início confirmado'
            elif state=='SYNTHESIZING':self.health['TTS']='SINTETIZANDO'
            elif state=='ERROR':self.health['TTS']='ERRO'
            for key, value in metrics.items():
                self.counts[key] = value

    def set_event_metrics(self, metrics: dict[str, int]) -> None:
        with self._lock:
            self.counts.update(metrics)

    def set_audience_metrics(self, metrics: dict[str, object]) -> None:
        with self._lock:
            self.counts.update({key: value for key, value in metrics.items()
                                if key not in {"TREND_OPPORTUNITY", "TREND_LAST_CLUSTER"}})

    def set_presenter_metrics(self, metrics: dict[str, object]) -> None:
        with self._lock:
            self.counts.update(metrics)

    def set_director_metrics(self, metrics):
        with self._lock:
            self.counts.update(metrics)

    def set_memory_metrics(self, metrics):
        with self._lock:
            self.counts.update(metrics)

    def set_moderation_metrics(self, metrics):
        with self._lock:
            self.counts.update(metrics)

    def sample(self, name: str, value: float) -> None:
        with self._lock:
            self.latency[name].add(value)

    def set_conversation_metrics(self, metrics: dict[str, object]) -> None:
        with self._lock:
            for key in ("ACTIVE_TOPIC", "TOPIC_SWITCHES_SESSION", "PENDING_QUESTION_ACTIVE",
                        "PENDING_QUESTION_CLEARED", "CONTEXT_FACTS_COUNT", "CONVERSATION_STAGE",
                        "DELIVERED_POINTS_COUNT", "DIALOGUE_ADVANCES_SESSION", "DIALOGUE_REPEATS_PREVENTED",
                        "PLANNED_POINTS_COUNT", "USER_QUESTIONS_HISTORY", "JARVIS_QUESTIONS_HISTORY"):
                if key in metrics:
                    self.counts[key] = metrics[key]

    def set_local_mode(self, active: bool) -> None:
        """Expose local-only health without starting network readers."""
        with self._lock:
            if active:
                self.health["DOM"] = "NÃO NECESSÁRIO"
                self.health["PONTE 8766"] = "NÃO NECESSÁRIO"
                self.health["MICROFONE"] = "PRONTO"
                self.health["STT"] = "PRONTO"
            else:
                self.health.pop("MICROFONE", None)
                self.health.pop("STT", None)

    def reset_local_session(self) -> None:
        """Reset only the current local-test counters and latency samples."""
        with self._lock:
            self.counts.clear()
            self.latency.clear()
            self.last_error = "—"

    def snapshot(self, queue_size: int = 0, gemini_calls: int = 0) -> dict:
        with self._lock:
            result = dict(self.counts)
            result.update({"health": dict(self.health), "queue": queue_size,
                           "gemini_calls": self.counts["gemini_calls_session"] if gemini_calls == 0 else gemini_calls,
                           "last_error": self.last_error})
            for name in ("dom", "gemini", "tts", "total"):
                avg, maximum = self.latency[name].summary()
                result[f"{name}_avg"] = avg
                result[f"{name}_max"] = maximum
            for name in ("GEMINI_GENERATION_MS", "TTS_QUEUE_WAIT_MS", "TTS_SYNTHESIS_MS", "TTS_PLAYBACK_START_MS", "TTS_TOTAL_TO_SPEECH_MS"):
                avg, maximum = self.latency[name].summary()
                result[f"{name}_avg"] = avg
                result[f"{name}_max"] = maximum
            aggregate = self.latency['tts'].values
            available = next((self.latency[name].values for name in ('tts','TTS_SYNTHESIS_MS','TTS_PLAYBACK_START_MS')
                              if any(self.latency[name].values)), [])
            result['tts_available'] = bool(any(available))
            if available and not any(aggregate):
                result['tts_avg'], result['tts_max'] = fmean(available), max(available)
            return result
