"""Manual local verification of the installed Edge TTS voices; no playback or Gemini."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

from live_voice import DEFAULTS, list_ptbr_voices, update_preferences


async def synthesize(voice: str, rate: str, destination: Path) -> int:
    await edge_tts.Communicate(
        text="Teste local da voz do JARVIS na Live.", voice=voice,
        rate=rate, pitch="+0Hz", volume="+0%",
    ).save(str(destination))
    return destination.stat().st_size


def main() -> None:
    voices = list_ptbr_voices()
    if len(voices) < 2:
        raise RuntimeError("São necessárias pelo menos duas vozes pt-BR disponíveis.")
    with tempfile.TemporaryDirectory(prefix="jarvis-live-voice-") as folder:
        folder_path = Path(folder)
        samples = [
            (voices[0]["id"], "-15%", "default"),
            (voices[0]["id"], "+25%", "faster"),
            (voices[1]["id"], "-15%", "second_voice"),
        ]
        result = {"engine": "edge_tts", "voices": voices, "samples": []}
        for voice, rate, label in samples:
            size = asyncio.run(synthesize(voice, rate, folder_path / f"{label}.mp3"))
            result["samples"].append({"voice": voice, "rate": rate, "bytes": size})
    persisted = update_preferences(dict(DEFAULTS))
    child = subprocess.run(
        [sys.executable, "-c", "import json; from live_social_01.live_voice import get_preferences; print(json.dumps(get_preferences()))"],
        check=True, capture_output=True, text=True,
    )
    result["persistence_after_new_process"] = json.loads(child.stdout)
    result["persistence_ok"] = result["persistence_after_new_process"] == persisted
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
