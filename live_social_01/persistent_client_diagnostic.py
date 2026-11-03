"""Validation of one persistent Gemini client for one Live Social session."""
from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import mean

import psutil

from live_response import GeminiResponder

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "last_persistent_client_diagnostic.json"
COMMENT = "Como a inteligência artificial pode ajudar uma pequena empresa?"


def token(metadata: object, names: tuple[str, ...]) -> int | None:
    for name in names:
        value = getattr(metadata, name, None)
        if isinstance(value, int):
            return value
    return None


def main() -> None:
    process = psutil.Process()
    start_rss = process.memory_info().rss
    cpu_start = process.cpu_times()
    started = time.perf_counter()
    responder = GeminiResponder(call_limit=4)
    init_started = time.perf_counter()
    responder.start_session()
    init_ms = (time.perf_counter() - init_started) * 1000
    warm_started = time.perf_counter()
    responder.generate(COMMENT)
    warm_ms = (time.perf_counter() - warm_started) * 1000
    calls = []
    for _ in range(3):
        call_started = time.perf_counter()
        response = responder.generate(COMMENT)
        latency = (time.perf_counter() - call_started) * 1000
        metadata = responder.last_usage_metadata
        calls.append({
            "latency_ms": round(latency, 2), "input_tokens": token(metadata, ("prompt_token_count", "input_token_count")),
            "output_tokens": token(metadata, ("candidates_token_count", "output_token_count")), "response": response,
            "client_id": id(responder._client),
        })
    elapsed = max(time.perf_counter() - started, 0.001)
    cpu_end = process.cpu_times()
    cpu_percent = 100 * ((cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)) / elapsed
    total_input = sum(item["input_tokens"] or 0 for item in calls)
    total_output = sum(item["output_tokens"] or 0 for item in calls)
    cost_usd = total_input * 0.10 / 1_000_000 + total_output * 0.40 / 1_000_000
    result = {
        "persistent_client_ok": len({item["client_id"] for item in calls}) == 1,
        "single_authentication_ok": responder._credentials is not None,
        "initialization_ms": round(init_ms, 2), "warmup_ms": round(warm_ms, 2),
        "calls": calls, "average_ms": round(mean(item["latency_ms"] for item in calls), 2),
        "total_input_tokens": total_input, "total_output_tokens": total_output,
        "estimated_cost_usd": round(cost_usd, 8), "cpu_percent": round(cpu_percent, 2),
        "additional_ram_mib": round((process.memory_info().rss - start_rss) / 1048576, 2),
    }
    responder.end_session()
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
