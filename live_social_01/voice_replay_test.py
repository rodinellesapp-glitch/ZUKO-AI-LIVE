"""Speak previously generated local test responses without another Gemini call."""
from __future__ import annotations

import json
import time
from pathlib import Path

import psutil

from live_response import JarvisSpeechQueue, LiveResponse

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "last_voice_test_result.json"


def main() -> None:
    previous = json.loads(RESULT.read_text(encoding="utf-8"))
    gemini_example = next(item.split(": ", 1)[1] for item in previous["examples"] if item.startswith("GEMINI: "))
    received = time.monotonic()
    responses = [
        LiveResponse("replayed-gemini", "Ana", gemini_example, "GEMINI", previous["avg_gemini_ms"], received),
        LiveResponse("replayed-rule", "Carlos", "Que bom ter você aqui na Live!", "RULE", 0.04, received),
    ]
    process = psutil.Process()
    rss_before = process.memory_info().rss
    cpu_before = process.cpu_times()
    started = time.perf_counter()
    voice = JarvisSpeechQueue(cooldown_seconds=3.0)
    for response in responses:
        voice.enqueue(response)
    idle = voice.wait_until_idle()
    elapsed = max(time.perf_counter() - started, 0.001)
    cpu_after = process.cpu_times()
    cpu_percent = 100 * ((cpu_after.user + cpu_after.system) - (cpu_before.user + cpu_before.system)) / elapsed
    stress = JarvisSpeechQueue(cooldown_seconds=0.05, speaker=lambda _: time.sleep(0.2))
    for index in range(7):
        stress.enqueue(LiveResponse(f"stress-{index}", "Teste", "Fila de teste.", "RULE", 0.0, time.monotonic()))
    stress_idle = stress.wait_until_idle(timeout=10.0)
    delays = [voice.started_at[item.comment_id] - item.received_at for item in voice.completed]
    previous.update({
        "rule_tts_ok": idle and any(item.provider == "RULE" for item in voice.completed),
        "gemini_tts_ok": idle and any(item.provider == "GEMINI" for item in voice.completed),
        "voice_queue_ok": stress_idle and stress.dropped >= 1 and len(stress.completed) <= 6,
        "cooldown_ok": len(voice.completed) == 2 and voice.started_at["replayed-rule"] - voice.started_at["replayed-gemini"] >= 2.95,
        "overlap_blocked": not voice.speaking and len(voice.completed) == 2,
        "avg_comment_to_speech_ms": round(sum(delays) * 1000 / len(delays), 2),
        "cpu_peak_percent": max(previous["cpu_peak_percent"], round(cpu_percent, 2)),
        "cpu_avg_percent": round((previous["cpu_avg_percent"] + cpu_percent) / 2, 2),
        "additional_ram_mib": round(max(previous["additional_ram_mib"], (process.memory_info().rss - rss_before) / 1048576), 2),
        "examples": [f"{item.provider}: {item.text}" for item in responses],
        "gemini_real_calls": 0,
    })
    RESULT.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(previous, ensure_ascii=False))


if __name__ == "__main__":
    main()
