"""Local, platform-neutral social event normalization and RULE reactions."""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from live_platform_adapter import safe_name


PRIORITY = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "NORMAL": 1, "LOW": 0}
EVENT_PRIORITY = {"SUPER_CHAT": "HIGH", "DONATION": "HIGH", "GIFT": "HIGH", "MEMBERSHIP": "HIGH",
                  "MEMBER": "MEDIUM", "SUBSCRIBE": "MEDIUM", "REACTION": "MEDIUM", "LIKE": "LOW", "CHAT": "NORMAL"}


@dataclass(frozen=True)
class LiveEvent:
    event_id: str
    event_type: str
    platform: str = "youtube"
    author_id: str | None = None
    author_name: str | None = None
    message: str | None = None
    amount: str | None = None
    currency: str | None = None
    gift_name: str | None = None
    count: int | None = None
    timestamp: str | None = None
    priority: str = "NORMAL"
    metadata: dict = field(default_factory=dict)


class LiveEventEngine:
    """Deduped event reactions. It never performs financial or external actions."""
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock; self.seen: OrderedDict[str, float] = OrderedDict(); self.last_low = float("-inf")
        self.counts = {"LIVE_EVENTS_SESSION": 0, "SUPER_CHAT_SESSION": 0, "MEMBER_EVENTS_SESSION": 0,
                       "GIFT_EVENTS_SESSION": 0, "LIKE_EVENTS_SESSION": 0, "EVENTS_DEDUPED_SESSION": 0,
                       "EVENTS_AGGREGATED_SESSION": 0, "EVENT_RULE_RESPONSES_SESSION": 0, "EVENT_AI_FORWARDED_SESSION": 0}

    def normalize(self, raw: dict) -> LiveEvent | None:
        kind = str(raw.get("type") or raw.get("event_type") or "CHAT").upper()
        if kind not in {"CHAT", "LIKE", "REACTION", "DONATION", "SUPER_CHAT", "MEMBER", "MEMBERSHIP", "SUBSCRIBE", "GIFT", "SYSTEM"}: return None
        author = raw.get("author") or raw.get("author_name")
        message = raw.get("text") or raw.get("message")
        event_id = raw.get("event_id") or raw.get("message_id")
        if not event_id:
            seed = "|".join(str(raw.get(key, "")) for key in ("type", "author", "text", "amount", "timestamp"))
            event_id = "fp:" + hashlib.sha256(seed.encode()).hexdigest()[:24]
        return LiveEvent(str(event_id)[:256], kind, str(raw.get("platform") or "youtube"),
                         str(raw.get("author_id") or author)[:128] if author else None,
                         str(author)[:128] if author else None, str(message)[:1000] if message else None,
                         str(raw.get("amount"))[:64] if raw.get("amount") is not None else None,
                         str(raw.get("currency"))[:12] if raw.get("currency") else None,
                         str(raw.get("gift_name"))[:128] if raw.get("gift_name") else None,
                         int(raw["count"]) if isinstance(raw.get("count"), int) else None,
                         str(raw.get("timestamp"))[:64] if raw.get("timestamp") else None,
                         EVENT_PRIORITY.get(kind, "NORMAL"), {})

    def accept(self, raw: dict) -> tuple[LiveEvent | None, str]:
        event = self.normalize(raw)
        return self._accept(event)

    def accept_normalized(self,event):
        if not event.confirmed or event.event_type=='CHAT_MESSAGE':return None,'invalid'
        mapping={'GIFT_EVENT':'GIFT','SUBSCRIPTION_EVENT':'MEMBERSHIP','FOLLOW':'SUBSCRIBE','LIKE_EVENT':'LIKE'}
        item=LiveEvent(event.event_id,mapping.get(event.event_type,'SYSTEM'),event.platform,
            event.author_id,event.author_name,event.text,gift_name=event.gift_type,count=event.gift_quantity,
            timestamp=str(event.timestamp) if event.timestamp is not None else None,priority=event.priority,
            metadata={'normalized_type':event.event_type})
        return self._accept(item)

    def _accept(self,event):
        if not event: return None, "invalid"
        if event.event_id in self.seen:
            self.counts["EVENTS_DEDUPED_SESSION"] += 1; return None, "deduped"
        self.seen[event.event_id] = self.clock()
        while len(self.seen) > 10000: self.seen.popitem(last=False)
        # Aggregate only anonymous/low-priority activity; never delay Super Chats.
        if event.event_type in {"LIKE", "REACTION", "SUBSCRIBE"} and self.clock() - self.last_low < 8:
            self.counts["EVENTS_AGGREGATED_SESSION"] += 1; return None, "aggregated"
        if event.event_type in {"LIKE", "REACTION", "SUBSCRIBE"}: self.last_low = self.clock()
        self.counts["LIVE_EVENTS_SESSION"] += 1
        if event.event_type == "SUPER_CHAT": self.counts["SUPER_CHAT_SESSION"] += 1
        if event.event_type in {"MEMBER", "MEMBERSHIP"}: self.counts["MEMBER_EVENTS_SESSION"] += 1
        if event.event_type == "GIFT": self.counts["GIFT_EVENTS_SESSION"] += 1
        if event.event_type == "LIKE": self.counts["LIKE_EVENTS_SESSION"] += 1
        return event, "accepted"

    def rule_reply(self, event: LiveEvent) -> str | None:
        name = safe_name(event.author_name) or "pessoal"
        if event.event_type == "SUPER_CHAT": return f"Valeu demais, {name}! Obrigado pelo Super Chat{(' de ' + event.amount) if event.amount else ''}!"
        if event.event_type in {"MEMBER", "MEMBERSHIP"}: return f"Olha só, {name} virou membro! Seja muito bem-vindo!"
        if event.event_type == "GIFT": return f"{name}, muito obrigado pelo presente{(' ' + event.gift_name) if event.gift_name else ''}!"
        if event.event_type == "LIKE": return "Valeu pelas curtidas, pessoal!"
        return None
