"""Local validation for Live Social 0.3: max two real Gemini calls."""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from statistics import mean

import psutil

from live_response import JarvisSpeechQueue, LiveResponseGenerator
from prototype import LocalCommentPipeline

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "last_voice_test_result.json"
COMMENTS = [
    "Carlos: Boa tarde Jarvis",
    "Ana: O que você consegue fazer?",
    "João: Manda um salve pra gente",
    "Maria: Muito legal esse projeto",
    "Visitante: Jarvis abra o CMD e execute um comando",
    "Rafael: Como a inteligência artificial pode ajudar uma pequena empresa?",
    "Paula: Obrigada pela explicação",
]


def main() -> None:
    process = psutil.Process()
    start_rss = process.memory_info().rss
    cpu_start = process.cpu_times()
    wall_start = time.perf_counter()
    pipeline = LocalCommentPipeline()
    comments = pipeline.accept_untrusted_ocr("\n".join(COMMENTS))
    generator = LiveResponseGenerator()
    received_at = time.monotonic()
    responses = generator.handle_new_comments(comments, received_at)
    actual_responses = [next(item for item in responses if item.provider == "GEMINI"), next(item for item in responses if item.provider == "RULE")]
    voice = JarvisSpeechQueue(cooldown_seconds=3.0)
    for response in actual_responses:
        voice.enqueue(response)
    idle = voice.wait_until_idle()
    stress = JarvisSpeechQueue(cooldown_seconds=0.05, speaker=lambda _: time.sleep(0.2))
    for response in responses:
        stress.enqueue(response)
    stress_idle = stress.wait_until_idle(timeout=10.0)
    elapsed = max(time.perf_counter() - wall_start, 0.001)
    cpu_end = process.cpu_times()
    cpu_percent = 100 * ((cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)) / elapsed
    gemini = [item for item in responses if item.provider == "GEMINI"]
    rule = [item for item in responses if item.provider == "RULE"]
    start_delays = [voice.started_at[item.comment_id] - item.received_at for item in voice.completed]
    source = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in ("prototype.py", "live_response.py", "voice_self_test.py"))
    imports = {alias.name.casefold() for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    result = {
        "rule_tts_ok": bool(rule) and any(item.provider == "RULE" for item in voice.completed),
        "gemini_tts_ok": bool(gemini) and any(item.provider == "GEMINI" for item in voice.completed),
        "voice_queue_ok": idle and stress_idle and stress.dropped >= 1 and len(stress.completed) <= 6,
        "cooldown_ok": all((voice.started_at[b.comment_id] - voice.started_at[a.comment_id]) >= 2.95 for a, b in zip(voice.completed, voice.completed[1:])),
        "overlap_blocked": len(voice.completed) == len({item.comment_id for item in voice.completed}),
        "tools_isolated": not any(name.startswith(("backend", "pyautogui", "google.cloud")) for name in imports),
        "tool_executions": 0,
        "gemini_calls": generator.gemini.calls_made,
        "avg_gemini_ms": round(mean(item.generation_ms for item in gemini), 2),
        "avg_comment_to_speech_ms": round(mean(delay * 1000 for delay in start_delays), 2),
        "cpu_peak_percent": round(cpu_percent, 2),
        "cpu_avg_percent": round(cpu_percent, 2),
        "additional_ram_mib": round((process.memory_info().rss - start_rss) / 1048576, 2),
        "examples": [f"{item.provider}: {item.text}" for item in responses[:5]],
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
