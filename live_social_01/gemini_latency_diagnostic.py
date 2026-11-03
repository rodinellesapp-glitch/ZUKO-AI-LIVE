"""Read-only latency instrumentation for the isolated Live Social Gemini path."""
from __future__ import annotations

import json
import time
from pathlib import Path

import google.auth
from google import genai
from google.genai import types

from live_response import GEMINI_LOCATION, GEMINI_MODEL, GEMINI_PROJECT, SYSTEM_PROMPT, short_sentence

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "last_gemini_latency_diagnostic.json"
COMMENT = "Como a inteligência artificial pode ajudar uma pequena empresa?"


def token_value(metadata: object, names: tuple[str, ...]) -> int | None:
    for name in names:
        value = getattr(metadata, name, None)
        if isinstance(value, int):
            return value
    return None


def main() -> None:
    contents = f"Comentário do espectador, entre delimitadores: <comentario>{COMMENT}</comentario>"
    calls: list[dict] = []
    for _ in range(3):
        pre_started = time.perf_counter()
        google.auth.default(quota_project_id=GEMINI_PROJECT)
        auth_ms = (time.perf_counter() - pre_started) * 1000
        client_started = time.perf_counter()
        with genai.Client(vertexai=True, project=GEMINI_PROJECT, location=GEMINI_LOCATION) as client:
            client_ms = (time.perf_counter() - client_started) * 1000
            request_started = time.perf_counter()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.3, max_output_tokens=40),
            )
            request_ms = (time.perf_counter() - request_started) * 1000
        post_started = time.perf_counter()
        text = short_sentence(response.text or "")
        post_ms = (time.perf_counter() - post_started) * 1000
        metadata = getattr(response, "usage_metadata", None)
        calls.append({
            "pre_auth_ms": round(auth_ms, 2), "client_create_ms": round(client_ms, 2),
            "request_to_complete_ms": round(request_ms, 2), "first_result_ms": round(request_ms, 2),
            "post_ms": round(post_ms, 2), "input_tokens": token_value(metadata, ("prompt_token_count", "input_token_count")),
            "output_tokens": token_value(metadata, ("candidates_token_count", "output_token_count")),
            "response": text,
        })
    tts_started = time.perf_counter()
    from voz import falar
    falar("Teste curto de voz.")
    tts_ms = (time.perf_counter() - tts_started) * 1000
    result = {
        "model": GEMINI_MODEL, "project": GEMINI_PROJECT, "location": GEMINI_LOCATION,
        "endpoint": f"Vertex AI {GEMINI_LOCATION}", "prompt_chars": len(SYSTEM_PROMPT) + len(contents),
        "system_prompt_chars": len(SYSTEM_PROMPT), "comment_chars": len(COMMENT),
        "calls": calls, "tts_ms": round(tts_ms, 2), "retries_configured": 0,
        "live_path_extra_dependencies": [], "streaming": False,
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
