"""Per-author, in-memory burst coalescing before the Gemini lock."""
from __future__ import annotations
import re
import threading
from dataclasses import dataclass
from types import SimpleNamespace

BURST_WINDOW_SECONDS = .75
BURST_MAX_PARTS = 5

@dataclass
class BurstStats:
    consolidated: int = 0
    messages_consolidated: int = 0
    stale_dropped: int = 0

class BurstCoordinator:
    def __init__(self, ready, window: float = BURST_WINDOW_SECONDS, on_event=lambda *_: None) -> None:
        self.ready, self.window, self.stats = ready, window, BurstStats()
        self.on_event = on_event
        self._pending, self._versions, self._lock = {}, {}, threading.Lock()

    def submit(self, comment) -> None:
        author = comment.author
        with self._lock:
            version = self._versions[author] = self._versions.get(author, 0) + 1
            entry = self._pending.get(author)
            if entry:
                entry["parts"].append(comment)
                entry["parts"] = entry["parts"][-BURST_MAX_PARTS:]
                entry["timer"].cancel()
                self.stats.consolidated += 1; self.stats.messages_consolidated += 1
            else:
                entry = {"parts": [comment]}; self._pending[author] = entry
            entry["version"] = version
            self.on_event("BURST_MERGED" if len(entry["parts"]) > 1 else "BURST_START")
            timer = threading.Timer(self.window, self._flush, args=(author, version))
            timer.daemon = True; entry["timer"] = timer; timer.start()

    def _flush(self, author: str, expected_version: int | None = None) -> None:
        with self._lock:
            if expected_version is not None and self._pending.get(author, {}).get("version") != expected_version:
                return
            entry = self._pending.pop(author, None)
            if not entry: return
            version = entry["version"]
        parts = entry["parts"]
        text = " ".join(part.text.strip() for part in parts if part.text.strip())
        last = parts[-1]
        merged = SimpleNamespace(comment_id=last.comment_id, author=author, text=text,
            normalized=re.sub(r"\s+", " ", text.lower()).strip(), received_at=last.received_at,
            burst_version=version, burst_count=len(parts),
            director_classification=getattr(last, 'director_classification', 'CHAT'),
            director_version=getattr(last, 'director_version', 0),
            flow_decision=getattr(last,'flow_decision',None),
            correlation_ids=tuple(cid for part in parts for cid in getattr(part,'correlation_ids',(getattr(part,'correlation_id',part.comment_id),))),
            source=getattr(last, "source", "LIVE_YOUTUBE"),
            tts_enabled=getattr(last, "tts_enabled", True))
        self.on_event("BURST_READY")
        self.ready(merged, merged.received_at)

    def current(self, comment) -> bool:
        return getattr(comment, "burst_version", 0) >= self._versions.get(comment.author, 0)

    def cancel_author(self, author: str) -> None:
        """Drop only the selected local tester's pending burst."""
        with self._lock:
            entry = self._pending.pop(author, None)
            if entry:
                entry["timer"].cancel()

    def stop(self) -> None:
        with self._lock:
            for entry in self._pending.values(): entry["timer"].cancel()
            self._pending.clear()
