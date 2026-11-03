"""Read-only YouTube Data API source. Secrets stay in environment/memory."""
from __future__ import annotations

import json
import os
import re
import socket
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


class ChatError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False, *, status: int | None = None,
                 exception_type: str = "", reason: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.exception_type = exception_type
        self.reason = reason


@dataclass(frozen=True)
class YouTubeComment:
    comment_id: str
    author: str
    text: str
    normalized: str
    status: str = "NOVO"
    published_at: float | None = None
    received_at: float = 0.0


def video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[\w-]{11}", value, re.ASCII):
        return value
    url = urlparse(value)
    host = (url.hostname or "").lower()
    if url.scheme != "https" or host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ChatError("Informe o ID ou link HTTPS da live do YouTube.")
    candidate = url.path.strip("/").split("/")[-1] if host == "youtu.be" or url.path.startswith(("/live/", "/shorts/")) else parse_qs(url.query).get("v", [""])[0]
    if not re.fullmatch(r"[\w-]{11}", candidate, re.ASCII):
        raise ChatError("ID da live inválido.")
    return candidate


class YouTubeLiveChat:
    def __init__(self, video: str, *, api_key: str = "", access_token: str = "", transport=None):
        self.video = video_id(video)
        if not api_key and not access_token:
            raise ChatError("Configure YOUTUBE_API_KEY ou YOUTUBE_ACCESS_TOKEN no ambiente local.")
        self._api_key, self._access_token = api_key, access_token
        self._transport = transport or self._get
        self.chat_id = ""
        self.page_token = ""
        self.interval = 5.0
        self.ready_at = 0.0
        self.started_at = datetime.now(timezone.utc)
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.duplicates = 0
        self.ended = False
        self.transient_failures = 0

    @classmethod
    def from_environment(cls, video: str = ""):
        return cls(video or os.environ.get("YOUTUBE_VIDEO_ID", ""),
                   api_key=os.environ.get("YOUTUBE_API_KEY", ""),
                   access_token=os.environ.get("YOUTUBE_ACCESS_TOKEN", ""))

    def _get(self, resource: str, params: dict) -> dict:
        headers = {"Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = "Bearer " + self._access_token
        else:
            headers["X-Goog-Api-Key"] = self._api_key
        request = Request("https://www.googleapis.com/youtube/v3/" + resource + "?" + urlencode(params), headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            # Never propagate URLs, headers, response bodies or credential values.
            code = error.code
            reason = "HTTP error"
            try:
                payload = json.load(error)
                api_error = payload.get("error", {}) if isinstance(payload, dict) else {}
                reasons = api_error.get("errors", []) if isinstance(api_error, dict) else []
                if reasons and isinstance(reasons[0], dict) and isinstance(reasons[0].get("reason"), str):
                    reason = reasons[0]["reason"]
                elif isinstance(api_error, dict) and isinstance(api_error.get("status"), str):
                    reason = api_error["status"]
            except (ValueError, OSError, AttributeError):
                pass
            error.close()
            retryable = code in {408, 429} or code >= 500
            raise ChatError(f"YouTube HTTP {code} | motivo={reason} | exceção=HTTPError", retryable,
                            status=code, exception_type="HTTPError", reason=reason) from None
        except (TimeoutError, socket.timeout) as error:
            raise ChatError(f"YouTube timeout | exceção={type(error).__name__}", True,
                            exception_type=type(error).__name__, reason="timeout") from None
        except URLError as error:
            reason = type(error.reason).__name__ if error.reason is not None else "network"
            raise ChatError(f"YouTube rede indisponível | exceção=URLError | motivo={reason}", True,
                            exception_type="URLError", reason=reason) from None
        except (json.JSONDecodeError, ValueError) as error:
            raise ChatError(f"YouTube resposta inválida | exceção={type(error).__name__}", True,
                            exception_type=type(error).__name__, reason="invalid_json") from None
        except OSError as error:
            raise ChatError(f"YouTube rede indisponível | exceção={type(error).__name__}", True,
                            exception_type=type(error).__name__, reason="os_error") from None

    def _remember(self, message_id: str) -> bool:
        if message_id in self.seen:
            self.duplicates += 1
            return False
        self.seen[message_id] = None
        if len(self.seen) > 10000:
            self.seen.popitem(last=False)
        return True

    def poll(self) -> list[YouTubeComment]:
        if self.ended or time.monotonic() < self.ready_at:
            return []
        try:
            if not self.chat_id:
                data = self._transport("videos", {"part": "liveStreamingDetails", "id": self.video})
                items = data.get("items", [])
                self.chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId", "") if items else ""
                if not self.chat_id:
                    raise ChatError("Live sem chat ativo acessível; confira o link e a transmissão.")
            params = {"part": "id,snippet,authorDetails", "liveChatId": self.chat_id, "maxResults": 200}
            if self.page_token:
                params["pageToken"] = self.page_token
            data = self._transport("liveChat/messages", params)
            interval = data.get("pollingIntervalMillis", 5000)
            if not isinstance(interval, (int, float)) or interval < 0:
                raise ChatError("Intervalo inválido na resposta do YouTube.", True)
            if interval == 0:
                raise ChatError("Intervalo inválido na resposta do YouTube.", True)
            # The API owns this cadence. Do not retain the old screen-capture floor.
            self.interval = interval / 1000
            self.ready_at = time.monotonic() + self.interval
            self.page_token = data.get("nextPageToken", "")
            if data.get("offlineAt"):
                self.ended = True
                return []
            if not self.page_token:
                raise ChatError("YouTube não retornou continuação do chat; leitura interrompida.")
            records = []
            received_at = time.monotonic()
            for item in data.get("items", []):
                if not isinstance(item, dict):
                    continue
                snippet, author = item.get("snippet", {}), item.get("authorDetails", {})
                if not isinstance(snippet, dict) or not isinstance(author, dict):
                    continue
                if snippet.get("type") != "textMessageEvent" or snippet.get("liveChatId") != self.chat_id:
                    continue
                mid = item.get("id")
                name = author.get("displayName")
                details = snippet.get("textMessageDetails", {})
                text = details.get("messageText") if isinstance(details, dict) else None
                if not all(isinstance(v, str) and v.strip() for v in (mid, name, text)):
                    continue
                try:
                    published = datetime.fromisoformat(snippet.get("publishedAt", "").replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - published).total_seconds()
                    if published < self.started_at or age > 15 or age < -5:
                        continue
                except (ValueError, TypeError, AttributeError):
                    continue
                if not self._remember(mid):
                    continue
                normalized = unicodedata.normalize("NFKD", text)
                normalized = "".join(c for c in normalized if not unicodedata.combining(c))
                normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
                records.append(YouTubeComment("youtube:" + mid, name, text, normalized, published_at=published.timestamp(), received_at=received_at))
            return records
        except ChatError as error:
            if error.retryable:
                self.transient_failures += 1
                self.interval = min(60.0, max(2.0, self.interval * 2))
                self.ready_at = time.monotonic() + self.interval
            raise error
        else:
            self.transient_failures = 0
