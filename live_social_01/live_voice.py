"""Local voice preferences for Live Social, backed by the installed Edge TTS engine."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from pathlib import Path

import edge_tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import config

PREFERENCES_PATH = Path(__file__).resolve().parent / "live_voice_preferences.json"
DEFAULTS = {
    "voice": config.VOZ,
    "rate": config.VELOCIDADE,
    "pitch": config.TOM,
    "volume": config.VOLUME,
}
_lock = threading.RLock()


class VoicePreferenceError(ValueError):
    pass


def _percent(value: object, *, minimum: int, maximum: int, field: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+%", value):
        number = int(value[:-1])
    elif isinstance(value, int):
        number = value
    else:
        raise VoicePreferenceError(f"{field} inválida.")
    if not minimum <= number <= maximum:
        raise VoicePreferenceError(f"{field} deve estar entre {minimum}% e {maximum}%.")
    return f"{number:+d}%"


def _pitch(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+Hz", value):
        number = int(value[:-2])
    elif isinstance(value, int):
        number = value
    else:
        raise VoicePreferenceError("Tom inválido.")
    if not -100 <= number <= 100:
        raise VoicePreferenceError("Tom deve estar entre -100Hz e +100Hz.")
    return f"{number:+d}Hz"


def list_ptbr_voices() -> list[dict[str, str]]:
    """Return only current, real pt-BR Edge voice metadata; no hardcoded names."""
    try:
        raw = asyncio.run(edge_tts.list_voices())
    except Exception as error:
        raise VoicePreferenceError("Não foi possível listar as vozes Edge TTS agora.") from error
    return [
        {"id": item["ShortName"], "name": item.get("FriendlyName", item["ShortName"]), "locale": item["Locale"]}
        for item in raw
        if item.get("Locale") == "pt-BR" and isinstance(item.get("ShortName"), str)
    ]


def get_preferences() -> dict[str, str]:
    with _lock:
        values = dict(DEFAULTS)
        try:
            saved = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return values
        if not isinstance(saved, dict):
            return values
        try:
            values["voice"] = saved.get("voice", values["voice"])
            values["rate"] = _percent(saved.get("rate", values["rate"]), minimum=-50, maximum=100, field="Velocidade")
            values["pitch"] = _pitch(saved.get("pitch", values["pitch"]))
            values["volume"] = _percent(saved.get("volume", values["volume"]), minimum=-50, maximum=100, field="Volume")
        except VoicePreferenceError:
            return dict(DEFAULTS)
        return values


def update_preferences(request: dict[str, object]) -> dict[str, str]:
    if not isinstance(request, dict):
        raise VoicePreferenceError("Configuração de voz inválida.")
    voices = {item["id"] for item in list_ptbr_voices()}
    current = get_preferences()
    voice = request.get("voice", current["voice"])
    if not isinstance(voice, str) or voice not in voices:
        raise VoicePreferenceError("Selecione uma voz pt-BR disponível no Edge TTS.")
    updated = {
        "voice": voice,
        "rate": _percent(request.get("rate", current["rate"]), minimum=-50, maximum=100, field="Velocidade"),
        "pitch": _pitch(request.get("pitch", current["pitch"])),
        "volume": _percent(request.get("volume", current["volume"]), minimum=-50, maximum=100, field="Volume"),
    }
    with _lock:
        temporary = PREFERENCES_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(PREFERENCES_PATH)
    return updated


def live_speech_options() -> dict[str, str]:
    return get_preferences()
