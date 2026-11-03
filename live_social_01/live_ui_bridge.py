"""Local, read-only bridge from the isolated Live Social process to the OBS UI.

Only presentation fields are retained in memory.  It never receives frames, raw
OCR output, credentials, or any JARVIS tool capability.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OFFICIAL_LIVE_ORIGIN = "https://jarvis-web-edee3.web.app"
YOUTUBE_DOM_ORIGIN = "https://www.youtube.com"
YOUTUBE_STUDIO_DOM_ORIGIN = "https://studio.youtube.com"
DOM_CHAT_EVENT_PATHS = {"/dom-chat", "/dom-chat/event"}
_instances_lock = threading.RLock()
_instances = {}


class LiveUiBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 18766, voice_api=None, dom_chat_api=None,
                 on_diagnostic=None, consumer_active=None) -> None:
        self.host, self.port = host, port
        self.voice_api = voice_api
        self.dom_chat_api = dom_chat_api
        self.on_diagnostic = on_diagnostic or (lambda *_: None)
        self.consumer_active = consumer_active or (lambda: False)
        self._lock = threading.Lock()
        self._payload = {"state": "AGUARDANDO", "author": "", "comment": "Aguardando comentários da Live", "response": "", "timestamp": ""}
        self._server: ThreadingHTTPServer | None = None
        self._owns_server = False
        self.instance_id = f"{os.getpid()}:{id(self):x}"

    def start(self) -> None:
        if self._server is not None:
            return
        key = (self.host, self.port)
        with _instances_lock:
            owner = _instances.get(key)
            if owner and owner._server:
                if owner.dom_chat_api is self.dom_chat_api:
                    self._server, self._owns_server = owner._server, False
                    self.instance_id = owner.instance_id
                    self.on_diagnostic("DOM_BRIDGE_SERVER_ALREADY_RUNNING", self.instance_id)
                    return
                self.on_diagnostic("DOM_BRIDGE_SERVER_ALREADY_RUNNING", "fila pertence a outra instância")
                raise RuntimeError("Porta 8766 já pertence a outra instância Live Social; fila DOM não compartilhada.")
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def _allowed_origin(self) -> str | None:
                origin = self.headers.get("Origin", "")
                if self.path in DOM_CHAT_EVENT_PATHS | {"/dom-chat/health"} and origin in {YOUTUBE_DOM_ORIGIN, YOUTUBE_STUDIO_DOM_ORIGIN}:
                    return origin
                if origin == OFFICIAL_LIVE_ORIGIN:
                    return origin
                return origin if re.fullmatch(r"http://(?:127\.0\.0\.1|localhost)(?::\d+)?", origin) else None

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                origin = self._allowed_origin()
                if origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                origin = self._allowed_origin()
                if not origin:
                    self.send_error(403)
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.headers.get("Origin") and not self._allowed_origin():
                    self.send_error(403)
                    return
                if self.path == "/status":
                    self._send_json(200, bridge.snapshot())
                    return
                if self.path == "/dom-chat/health" and self.headers.get("Origin") in {YOUTUBE_DOM_ORIGIN, YOUTUBE_STUDIO_DOM_ORIGIN} and bridge.dom_chat_api:
                    self._send_json(200, {"ready": True, "consumer_active": bool(bridge.consumer_active()),
                                          "instance_id": bridge.instance_id})
                    return
                if self.path == "/voice" and bridge.voice_api:
                    try:
                        self._send_json(200, bridge.voice_api.status())
                    except ValueError as error:
                        self._send_json(503, {"error": str(error)})
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path in DOM_CHAT_EVENT_PATHS:
                    if self.headers.get("Origin") not in {YOUTUBE_DOM_ORIGIN, YOUTUBE_STUDIO_DOM_ORIGIN} or not bridge.dom_chat_api:
                        self.send_error(403)
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 <= length <= 2048:
                            raise ValueError("Evento DOM inválido.")
                        event = json.loads(self.rfile.read(length) or b"{}")
                        if not isinstance(event, dict):
                            raise ValueError("Evento DOM inválido.")
                        event_id = event.get("event_id") or event.get("message_id") or "—"
                        bridge.on_diagnostic("DOM_BRIDGE_EVENT_RECEIVED", str(event_id))
                        accepted = bridge.dom_chat_api.ingest(event)
                        bridge.on_diagnostic("DOM_BRIDGE_EVENT_QUEUED" if accepted else "DOM_BRIDGE_EVENT_REJECTED", str(event_id))
                        self._send_json(200, {"accepted": bool(accepted), "instance_id": bridge.instance_id})
                    except (ValueError, json.JSONDecodeError) as error:
                        self._send_json(400, {"error": str(error)})
                    return
                if self.path not in {"/voice", "/voice/test"} or not bridge.voice_api:
                    self.send_error(404)
                    return
                if self.headers.get("Origin") and not self._allowed_origin():
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= 2048:
                        raise ValueError("Solicitação de voz inválida.")
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("Solicitação de voz inválida.")
                    result = bridge.voice_api.test() if self.path == "/voice/test" else bridge.voice_api.update(payload)
                    self._send_json(200, result)
                except (ValueError, json.JSONDecodeError) as error:
                    self._send_json(400, {"error": str(error)})

            def log_message(self, *_args) -> None:
                return

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as error:
            healthy, details = self.probe(self.host, self.port)
            if healthy:
                self.on_diagnostic("DOM_BRIDGE_SERVER_ALREADY_RUNNING",
                                   f"health=OK instance={details.get('instance_id', 'unknown')}")
                raise RuntimeError("Bridge saudável já existe em outro processo, mas a fila DOM não é compartilhada entre processos.") from error
            self.on_diagnostic("DOM_BRIDGE_SERVER_ERROR", f"porta {self.port} ocupada por serviço incompatível")
            raise RuntimeError(f"Porta {self.port} ocupada por serviço incompatível ou desconhecido.") from error
        self._owns_server = True
        with _instances_lock:
            _instances[key] = self
        threading.Thread(target=self._server.serve_forever, name="live-ui-bridge", daemon=True).start()
        self.on_diagnostic("DOM_BRIDGE_SERVER_START", f"127.0.0.1:{self.port}")

    @staticmethod
    def probe(host="127.0.0.1", port=8766, timeout=0.5):
        request = urllib.request.Request(
            f"http://{host}:{port}/dom-chat/health", method="GET",
            headers={"Origin": YOUTUBE_STUDIO_DOM_ORIGIN})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status == 200 and payload.get("ready") is True, payload
        except Exception:
            return False, {}

    def stop(self) -> None:
        if self._server is not None and self._owns_server:
            self._server.shutdown()
            self._server.server_close()
            with _instances_lock:
                if _instances.get((self.host, self.port)) is self:
                    _instances.pop((self.host, self.port), None)
        self._server = None
        self._owns_server = False

    def publish(self, *, state: str, author: str | None = None, comment: str | None = None, response: str | None = None) -> None:
        with self._lock:
            self._payload["state"] = state
            if author is not None:
                self._payload["author"] = author
            if comment is not None:
                self._payload["comment"] = comment
            if response is not None:
                self._payload["response"] = response
            self._payload["timestamp"] = datetime.now().isoformat(timespec="seconds")

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._payload)
