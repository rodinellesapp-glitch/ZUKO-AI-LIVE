"""One-comment local check for Gemini -> sanitized UI bridge -> serialized TTS."""
from __future__ import annotations

import json
import time
from pathlib import Path

import psutil

from live_monitor import FreshSpeechQueue
from live_response import LiveResponse, LiveResponseGenerator
from live_ui_bridge import LiveUiBridge


def main() -> None:
    process = psutil.Process()
    start_rss = process.memory_info().rss
    bridge = LiveUiBridge()
    bridge.start()
    history: list[str] = []
    author, comment = "Ana", "O que você consegue fazer?"

    def state_change(state: str) -> None:
        ui_state = {"SPEAKING": "RESPONDENDO", "WATCHING": "AGUARDANDO"}[state]
        history.append(ui_state)
        bridge.publish(state=ui_state)

    try:
        bridge.publish(state="OUVINDO", author=author, comment=comment, response="")
        history.append("OUVINDO")
        bridge.publish(state="PENSANDO")
        history.append("PENSANDO")
        generator = LiveResponseGenerator()
        started = time.perf_counter()
        response = generator.generate("bridge-gemini-1", author, comment, "ana: o que voce consegue fazer?")
        latency_ms = (time.perf_counter() - started) * 1000
        assert response is not None and response.provider == "GEMINI"
        bridge.publish(state="PENSANDO", author=author, comment=comment, response=response.text)
        queue = FreshSpeechQueue(state_change, lambda _response, _delay: None)
        queue.enqueue(LiveResponse(response.comment_id, author, response.text, "GEMINI", latency_ms, time.monotonic()))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and queue.worker and queue.worker.is_alive():
            time.sleep(.1)
        result = {
            "gemini_to_tts_ok": not queue.worker or not queue.worker.is_alive(),
            "states": history,
            "latency_ms": round(latency_ms, 2),
            "bridge": bridge.snapshot(),
            "ram_additional_mib": round((process.memory_info().rss - start_rss) / 1048576, 2),
            "tools_activated": 0,
        }
        Path(__file__).with_name("last_integration_bridge_test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
