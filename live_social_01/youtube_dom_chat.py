"""Manual DOM fallback for a locally open YouTube Live Chat; no API or OCR."""
from __future__ import annotations

import re
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from youtube_live_chat import YouTubeComment


class ChatSource(str, Enum):
    YOUTUBE_API = "youtube"
    YOUTUBE_DOM = "dom"
    OCR = "ocr"


class YouTubeDomChat:
    """Accepts only structured events from the optional local content script."""
    def __init__(self) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._records: deque[YouTubeComment] = deque()
        self._events: deque[dict] = deque()
        self.duplicates = 0

    def _remember(self, message_id: str) -> bool:
        if message_id in self._seen:
            self.duplicates += 1
            return False
        self._seen[message_id] = None
        if len(self._seen) > 10000:
            self._seen.popitem(last=False)
        return True

    @staticmethod
    def _normalized(value: str) -> str:
        value = unicodedata.normalize("NFKD", value)
        value = "".join(char for char in value if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", value).strip().casefold()

    def ingest(self, event: dict) -> bool:
        if str(event.get("type") or "CHAT").upper() != "CHAT":
            event_id = event.get("event_id") or event.get("message_id")
            if not isinstance(event_id, str) or not event_id.strip() or not self._remember(event_id.strip()):
                return False
            if event.get("initial") is not True:
                self._events.append(dict(event))
            return True
        message_id, author, text = (event.get(key) for key in ("message_id", "author", "text"))
        if not all(isinstance(value, str) and value.strip() for value in (message_id, author, text)):
            return False
        message_id, author, text = message_id.strip(), author.strip(), text.strip()
        if len(message_id) > 256 or len(author) > 128 or len(text) > 1000:
            return False
        if not self._remember(message_id):
            return False
        # The script seeds existing renderer IDs as initial history. Never speak it.
        if event.get("initial") is True:
            return False
        published_at = None
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            try:
                published_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
            except ValueError:
                pass
        self._records.append(YouTubeComment(f"dom:{message_id}", author, text, self._normalized(text),
                                             published_at=published_at, received_at=time.monotonic()))
        return True

    def drain(self) -> list[YouTubeComment]:
        records = list(self._records)
        self._records.clear()
        return records

    def drain_events(self) -> list[dict]:
        events = list(self._events); self._events.clear()
        return events
