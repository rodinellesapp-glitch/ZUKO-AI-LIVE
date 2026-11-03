"""Small redacted JSONL session logger for the local Command Center."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from threading import Lock

_SECRET = re.compile(r"(?i)(api[_ -]?key|token|senha|password|authorization)\s*[:=]\s*[^\s|]+")
_SENSITIVE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}[\s.-]?\d{4}")


class SessionLogger:
    def __init__(self, directory: Path, limit_bytes: int = 2_000_000) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"live_{datetime.now():%Y-%m-%d_%H%M%S}.jsonl"
        self.limit_bytes, self._lock = limit_bytes, Lock()

    @staticmethod
    def redact(text: str) -> str:
        parts=re.split(r'(T[0-9]_[A-Z_]+=[0-9.]+ms|wait_ms=[0-9.]+)',text)
        return ''.join(part if re.fullmatch(r'(T[0-9]_[A-Z_]+=[0-9.]+ms|wait_ms=[0-9.]+)',part) else _SENSITIVE.sub('[REDACTED]',_SECRET.sub('[REDACTED]',part)) for part in parts)[:800]

    def write(self, component: str, event: str, status: str = "INFO", latency_ms: float | None = None) -> None:
        row = {"at": datetime.now().isoformat(timespec="seconds"), "component": component, "event": self.redact(event), "status": status}
        if latency_ms is not None:
            row["latency_ms"] = round(latency_ms, 1)
        encoded = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            if self.path.exists() and self.path.stat().st_size + len(encoded.encode("utf-8")) > self.limit_bytes:
                archive=self.path.with_name(self.path.stem+'_'+datetime.now().strftime('%H%M%S%f')+'.jsonl')
                self.path.replace(archive)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(encoded)
